"""Translation panels and background jobs."""

from flask import Blueprint, current_app, jsonify, render_template, request
from lute.db import db
from lute.models.language import Language
from lute.term.model import Repository
from lute.translation.service import TranslationError, TranslationJobs

bp = Blueprint("translation", __name__, url_prefix="/translation")


def _jobs():
    return current_app.extensions["codex_translation_jobs"]


@bp.record_once
def setup(state):
    """One bounded job manager per application."""
    state.app.extensions["codex_translation_jobs"] = TranslationJobs()


@bp.route("/panel")
def panel():
    """The Codex tab occupies the existing dictionary iframe."""
    language = db.session.get(Language, request.args.get("language_id", type=int))
    return render_template("read/codex_panel.html", language=language)


@bp.route("/jobs", methods=["POST"])
def submit():
    """Only translate for languages that explicitly select Codex."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Expected a JSON object"), 400
    lang_id = data.get("language_id")
    if not isinstance(lang_id, int):
        return jsonify(error="Invalid language"), 400
    language = db.session.get(Language, lang_id)
    if language is None:
        return jsonify(error="Language not found"), 404
    if language.translation_provider != "codex":
        return (
            jsonify(
                error="Select Codex CLI translation in the language settings first"
            ),
            400,
        )
    text = data.get("text", "")
    context = data.get("context", "")
    kind = data.get("kind", "term")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > (32000 if kind == "sentence" else 4000)
        or not isinstance(context, str)
        or len(context) > 4000
        or kind not in ("term", "sentence")
    ):
        return (
            jsonify(
                error="Invalid text or context (limit: 4000 characters per term/context, 32000 per page)"
            ),
            400,
        )
    clean_text = text.replace("\u200b", "").strip()
    word_texts = ()
    if kind == "term":
        tokens = language.get_parsed_tokens(clean_text)
        seen = set()
        words = []
        for token in tokens:
            normalized = language.get_lowercase(token.token)
            if token.is_word and normalized not in seen:
                words.append(token.token)
                seen.add(normalized)
        # Keep long selections usable without generating an unbounded set of cards.
        if 1 < len(words) <= 40:
            word_texts = tuple(words)
    key = (
        language.name,
        language.translation_target,
        language.codex_model,
        clean_text,
        context,
        kind,
        word_texts,
        language.codex_reasoning_effort,
        language.codex_fast_mode,
    )
    try:
        job_id = _jobs().submit(key)
    except TranslationError as exc:
        return jsonify(error=str(exc)), 429
    return jsonify(job_id=job_id), 202


@bp.route("/jobs/<job_id>")
def poll(job_id):
    """Polling never waits for Codex."""
    result = _jobs().get(job_id)
    if result is None:
        return jsonify(error="Translation expired. Try again."), 404
    return jsonify(result)


@bp.route("/parent")
def parent():
    """Read an existing lemma without creating vocabulary on lookup."""
    lang_id = request.args.get("language_id", type=int)
    language = db.session.get(Language, lang_id) if lang_id else None
    text = request.args.get("text", "").strip()
    if language is None or not text or len(text) > 500:
        return jsonify(error="Invalid parent or language"), 400
    term = Repository(db.session).find(lang_id, text)
    if term is None:
        return jsonify(exists=False, translation="", status=0)
    return jsonify(exists=True, translation=term.translation or "", status=term.status)


@bp.route("/words", methods=["POST"])
def save_word_cards():
    """Save explicitly selected phrase cards and their parents in one transaction."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("language_id"), int):
        return jsonify(error="Invalid word card request"), 400
    language = db.session.get(Language, data["language_id"])
    job_id = data.get("job_id")
    indices = data.get("indices")
    if (
        language is None
        or language.translation_provider != "codex"
        or not isinstance(job_id, str)
        or not isinstance(indices, list)
        or not 1 <= len(indices) <= 40
    ):
        return jsonify(error="Invalid word card request"), 400
    key = _jobs().key_for(job_id)
    result = _jobs().get(job_id)
    if key is None or result is None:
        return jsonify(error="Translation expired. Translate the phrase again."), 404
    if (
        key[:3] != (language.name, language.translation_target, language.codex_model)
        or key[7:] != (language.codex_reasoning_effort, language.codex_fast_mode)
        or key[5] != "term"
        or result["status"] != "complete"
    ):
        return (
            jsonify(
                error="This translation is not ready or its language settings changed. Translate again."
            ),
            400,
        )
    cards = result["result"]["words"]
    if any(type(index) is not int or not 0 <= index < len(cards) for index in indices):
        return jsonify(error="Invalid selected words"), 400
    repo = Repository(db.session)
    saved = []
    for index in dict.fromkeys(indices):
        card = cards[index]
        term = repo.find_or_new(language.id, card["text"])
        already_saved = term.id is not None and term.status != 0
        if not (term.translation or "").strip():
            term.translation = card["translation"]
        if term.status == 0:
            term.status = 1
        is_inflected = card["is_inflected"] and language.get_lowercase(
            card["lemma"]
        ) != language.get_lowercase(card["text"])
        if is_inflected and not term.parents:
            parent_term = repo.find(language.id, card["lemma"])
            term.parents = [card["lemma"]]
            if not already_saved:
                term.sync_status = True
                if parent_term is not None and parent_term.status != 0:
                    term.status = parent_term.status
        if is_inflected:
            term.suggested_parent_text = card["lemma"]
            term.suggested_parent_translation = card["lemma_translation"]
        repo.add(term)
        saved.append(
            {
                "index": index,
                "text": card["text"],
                "translation": term.translation,
                "already_saved": already_saved,
            }
        )
    repo.commit()
    return jsonify(saved=saved)
