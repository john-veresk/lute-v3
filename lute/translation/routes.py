"""Translation panels and background jobs."""

from flask import Blueprint, current_app, jsonify, render_template, request
from lute.db import db
from lute.models.language import Language
from lute.models.term import Term as DBTerm
from lute.term.model import Repository
from lute.translation import store
from lute.translation.cards import save_card
from lute.translation.service import TranslationError, TranslationJobs

bp = Blueprint("translation", __name__, url_prefix="/translation")

# auto: a saved result, otherwise translate.  stored: only a saved result.
# prefetch: translate only terms without a saved result.  refresh: always translate.
LOOKUP_MODES = ("auto", "stored", "prefetch", "refresh")


def _jobs():
    return current_app.extensions["codex_translation_jobs"]


def _phrase_candidates(language, word, context):
    """Bounded, verbatim spans of 2–6 words around a single selected word."""
    tokens = language.get_parsed_tokens(context)
    selected = language.get_lowercase(word)
    candidates = []
    for start, token in enumerate(tokens):
        if not token.is_word:
            continue
        parts = []
        count = 0
        contains_word = False
        for following in tokens[start:]:
            if following.is_end_of_sentence:
                break
            parts.append(following.token)
            if not following.is_word:
                continue
            count += 1
            if count > 6:
                break
            contains_word |= language.get_lowercase(following.token) == selected
            phrase = "".join(parts)
            if (
                contains_word
                and count > 1
                and len(phrase) <= 250
                and phrase in context
                and phrase not in candidates
            ):
                candidates.append(phrase)
                if len(candidates) == 80:
                    return tuple(candidates)
    return tuple(candidates)


@bp.record_once
def setup(state):
    """One bounded job manager per application."""
    state.app.extensions["codex_translation_jobs"] = TranslationJobs()


@bp.route("/panel")
def panel():
    """Sentence and page translations, shown in the term frame."""
    language = db.session.get(Language, request.args.get("language_id", type=int))
    return render_template("read/codex_panel.html", language=language)


@bp.route("/jobs", methods=["POST"])
def submit():
    """Queue a Codex translation of a term or sentence, or reuse a saved one."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Expected a JSON object"), 400
    lang_id = data.get("language_id")
    if not isinstance(lang_id, int):
        return jsonify(error="Invalid language"), 400
    language = db.session.get(Language, lang_id)
    if language is None:
        return jsonify(error="Language not found"), 404
    text = data.get("text", "")
    context = data.get("context", "")
    kind = data.get("kind", "term")
    mode = data.get("mode", "auto")
    if mode not in LOOKUP_MODES:
        return jsonify(error="Invalid lookup mode"), 400
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
    phrase_texts = ()
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
        if sum(token.is_word for token in tokens) == 1 and context.strip():
            phrase_texts = _phrase_candidates(
                language, words[0], context.replace("\u200b", "")
            )
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
        phrase_texts,
    )
    saved = None
    if kind == "term" and mode != "refresh":
        saved = store.find(db.session, language, clean_text)
    if saved is not None and mode != "prefetch":
        job_id = _jobs().adopt(key, _fit_to_context(saved, phrase_texts), language.id)
        return jsonify(job_id=job_id, saved=True), 202
    if saved is not None or mode == "stored":
        return jsonify(job_id=None), 200
    try:
        job_id = _jobs().submit(key, fresh=mode == "refresh", language_id=language.id)
    except TranslationError as exc:
        return jsonify(error=str(exc)), 429
    return jsonify(job_id=job_id, saved=False), 202


def _fit_to_context(result, phrase_texts):
    "A result saved from another sentence only offers phrases found in this one."
    phrases = [p for p in result.get("phrases", []) if p["text"] in phrase_texts]
    return {**result, "phrases": phrases}


@bp.route("/jobs/<job_id>")
def poll(job_id):
    """Polling never waits for Codex."""
    result = _jobs().get(job_id)
    if result is None:
        return jsonify(error="Translation expired. Try again."), 404
    if result["status"] == "complete":
        _save_new_result(job_id, result["result"])
        result = {**result, "result": _mark_saved_words(job_id, result["result"])}
    return jsonify(result)


def _mark_saved_words(job_id, result):
    "Words already in the vocabulary stay checked and are not saved again."
    words = result.get("words") or []
    language_id = _jobs().language_id_for(job_id)
    language = db.session.get(Language, language_id) if language_id else None
    if language is None or not words:
        return result
    lowered = [language.get_lowercase(word["text"]) for word in words]
    saved = {
        text
        for (text,) in db.session.query(DBTerm.text_lc).filter(
            DBTerm.language_id == language.id,
            DBTerm.text_lc.in_(lowered),
            DBTerm.status != 0,
        )
    }
    return {
        **result,
        "words": [
            (
                {**word, "saved": True}
                if language.get_lowercase(word["text"]) in saved
                else word
            )
            for word in words
        ],
    }


def _save_new_result(job_id, result):
    "Every new term translation goes into the translation store."
    claim = _jobs().claim_unsaved(job_id)
    if claim is None:
        return
    key, language_id = claim
    language = db.session.get(Language, language_id)
    if language is not None and key[5] == "term":
        store.save(db.session, language, key[3], key[4], result)


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
    """Save explicitly selected word cards and their parents."""
    return _save_cards("words")


@bp.route("/phrases", methods=["POST"])
def save_phrase_cards():
    """Save only the explicitly selected contextual phrases."""
    return _save_cards("phrases")


def _save_cards(card_type):
    """Save reviewed cards together, preserving existing vocabulary edits."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("language_id"), int):
        return jsonify(error="Invalid card request"), 400
    language = db.session.get(Language, data["language_id"])
    job_id = data.get("job_id")
    indices = data.get("indices")
    if (
        language is None
        or not isinstance(job_id, str)
        or not isinstance(indices, list)
        or not 1 <= len(indices) <= (3 if card_type == "phrases" else 40)
    ):
        return jsonify(error="Invalid card request"), 400
    key = _jobs().key_for(job_id)
    result = _jobs().get(job_id)
    if key is None or result is None:
        return jsonify(error="Translation expired. Translate again."), 404
    if (
        key[:3] != (language.name, language.translation_target, language.codex_model)
        or key[7:9] != (language.codex_reasoning_effort, language.codex_fast_mode)
        or key[5] != "term"
        or result["status"] != "complete"
    ):
        return (
            jsonify(
                error="This translation is not ready or its language settings changed. Translate again."
            ),
            400,
        )
    cards = result["result"].get(card_type, [])
    if any(type(index) is not int or not 0 <= index < len(cards) for index in indices):
        return jsonify(error="Invalid selected cards"), 400
    if card_type == "phrases" and any(
        cards[index]["text"] not in key[9] for index in indices
    ):
        return jsonify(error="Phrase does not match the sentence context"), 400
    repo = Repository(db.session)
    saved = [
        {"index": index, **save_card(repo, language, cards[index], card_type)}
        for index in dict.fromkeys(indices)
    ]
    repo.commit()
    return jsonify(saved=saved)
