"""Context phrases stay within the sentence and are saved only by request."""

import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from lute.db import db
from lute.models.term import Term as DBTerm
from lute.term.model import Repository
from lute.translation import service
from lute.translation.routes import _phrase_candidates
from tests.unit.read.test_codex_translation import RESULT

PHRASES = [
    {"text": "looked after", "translation": "присматривал за"},
    {"text": "looked after the cats", "translation": "присматривал за кошками"},
]


def test_candidates_use_whole_words_and_stay_in_one_sentence(english):
    context = "He looked after the cats. Dogs looked away."
    candidates = _phrase_candidates(english, "LOOKED", context)
    assert "looked after" in candidates
    assert "looked after the cats" in candidates
    assert "Dogs looked away" in candidates
    assert all(phrase in context and "." not in phrase for phrase in candidates)
    assert _phrase_candidates(english, "cat", "A catalog of cats.") == ()
    assert _phrase_candidates(english, "looked", "looked.") == ()


def test_candidates_use_the_language_case_rules(turkish):
    assert "IŞIK yanıyor" in _phrase_candidates(turkish, "ışık", "IŞIK yanıyor.")


def test_candidates_support_languages_without_spaces(classical_chinese):
    assert "人人" in _phrase_candidates(classical_chinese, "人", "人人。")


@pytest.mark.parametrize(
    "text,context,kind,has_phrases",
    [
        ("looked", "He looked after the cats.", "term", True),
        ("looked after", "He looked after the cats.", "term", False),
        ("looked looked", "He looked after the cats.", "term", False),
        ("looked", "", "term", False),
        ("looked", "He looked after the cats.", "sentence", False),
    ],
)
def test_only_single_word_jobs_offer_context_phrases(
    client, english, monkeypatch, text, context, kind, has_phrases
):
    db.session.commit()
    monkeypatch.setattr(service, "translate", lambda *args: RESULT)
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": english.id,
            "text": text,
            "context": context,
            "kind": kind,
        },
    )
    assert response.status_code == 202
    jobs = client.application.extensions["codex_translation_jobs"]
    jobs.pool.shutdown(wait=True)
    candidates = jobs.key_for(response.json["job_id"])[9]
    assert bool(candidates) is has_phrases
    if has_phrases:
        assert "looked after" in candidates
    assert db.session.query(DBTerm).count() == 0


def _mock_cli(monkeypatch, phrases, candidates):
    monkeypatch.setattr(service.shutil, "which", lambda value: "/usr/bin/codex")

    def run(command, **kwargs):
        payload = json.loads(kwargs["input"].split("\n", 1)[1])
        assert payload["phrase_candidates"] == list(candidates)
        schema = json.loads(
            Path(command[command.index("--output-schema") + 1]).read_text()
        )
        assert "phrases" in schema["required"]
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps({**RESULT, "phrases": phrases}), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)


def test_cli_returns_only_reviewed_context_phrases(monkeypatch):
    candidates = tuple(phrase["text"] for phrase in PHRASES)
    _mock_cli(monkeypatch, PHRASES, candidates)
    result = service.translate(
        "English",
        "Russian",
        "",
        "looked",
        "He looked after the cats.",
        phrase_texts=candidates,
    )
    assert result["phrases"] == PHRASES


@pytest.mark.parametrize(
    "phrases",
    [
        "invalid",
        [None],
        [{"text": "invented phrase", "translation": "перевод"}],
        [{"text": "looked after", "translation": ""}],
        [{"text": "looked after", "translation": "x" * 501}],
        [{"text": "looked after", "translation": []}],
        [PHRASES[0], PHRASES[0]],
        [PHRASES[0]] * 4,
    ],
)
def test_cli_rejects_invalid_or_invented_phrases(monkeypatch, phrases):
    candidates = ("looked after",)
    _mock_cli(monkeypatch, phrases, candidates)
    with pytest.raises(service.TranslationError):
        service.translate(
            "English",
            "Russian",
            "",
            "looked",
            "He looked after the cats.",
            phrase_texts=candidates,
        )


def _phrase_job(client, language, monkeypatch, phrases=PHRASES):
    language.translation_target = "Russian"
    db.session.commit()
    monkeypatch.setattr(
        service, "translate", lambda *args: {**RESULT, "phrases": phrases}
    )
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": language.id,
            "text": "looked",
            "context": "He looked after the cats.",
        },
    )
    client.application.extensions["codex_translation_jobs"].pool.shutdown(wait=True)
    return response.json["job_id"]


def test_phrases_already_in_the_vocabulary_are_marked_saved(
    client, english, monkeypatch
):
    "A phrase that already has a card starts checked; an unknown placeholder does not."
    job_id = _phrase_job(client, english, monkeypatch)
    client.get(f"/translation/jobs/{job_id}")
    saved = DBTerm(english, "looked after")
    saved.status = 2
    saved.translation = "мой перевод"
    unknown = DBTerm(english, "looked after the cats")
    unknown.status = 0
    db.session.add_all([saved, unknown])
    db.session.commit()
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": english.id,
            "text": "looked",
            "context": "He looked after the cats.",
        },
    )
    assert response.json["saved"] is True
    phrases = {
        phrase["text"]: phrase
        for phrase in client.get(f"/translation/jobs/{response.json['job_id']}").json[
            "result"
        ]["phrases"]
    }
    assert phrases["looked after"]["saved"] is True
    assert "saved" not in phrases["looked after the cats"]


@pytest.mark.parametrize("cli", ["codex", "cursor"])
def test_save_phrase_is_explicit_and_independent_of_the_clicked_word(
    client, english, monkeypatch, cli
):
    english.translation_cli = cli
    if cli == "cursor":
        english.codex_reasoning_effort = "high"
        english.codex_fast_mode = True
    job_id = _phrase_job(client, english, monkeypatch)
    assert db.session.query(DBTerm).count() == 0
    response = client.post(
        "/translation/phrases",
        json={"language_id": english.id, "job_id": job_id, "indices": [1, 1]},
    )
    assert response.status_code == 200
    assert len(response.json["saved"]) == 1
    repo = Repository(db.session)
    term = repo.find(english.id, "looked after the cats")
    assert term.translation == "присматривал за кошками"
    assert term.status == 1
    assert term.parents == []
    assert repo.find(english.id, "looked") is None
    assert repo.find(english.id, "looked after") is None


@pytest.mark.parametrize("translation", ["мой перевод", ""])
def test_phrase_cards_keep_existing_vocabulary_edits(
    client, english, monkeypatch, translation
):
    repo = Repository(db.session)
    term = repo.find_or_new(english.id, "looked after")
    term.translation = translation
    term.parents = ["look after"]
    term.status = 3
    repo.add(term)
    repo.commit()
    existing_parents = Repository(db.session).find(english.id, "looked after").parents
    job_id = _phrase_job(client, english, monkeypatch)
    response = client.post(
        "/translation/phrases",
        json={"language_id": english.id, "job_id": job_id, "indices": [0]},
    )
    assert response.status_code == 200
    term = Repository(db.session).find(english.id, "looked after")
    assert term.translation == (translation or "присматривал за")
    assert term.status == 3
    assert term.parents == existing_parents


def test_save_rejects_a_phrase_outside_the_original_context(
    client, english, monkeypatch
):
    job_id = _phrase_job(
        client,
        english,
        monkeypatch,
        phrases=[PHRASES[0], {"text": "looked around", "translation": "огляделся"}],
    )
    response = client.post(
        "/translation/phrases",
        json={"language_id": english.id, "job_id": job_id, "indices": [0, 1]},
    )
    assert response.status_code == 400
    assert db.session.query(DBTerm).count() == 0


@pytest.mark.parametrize("indices", [[], [0, 10], [True], [0, 1, 2, 3]])
def test_bad_phrase_selection_is_rejected_before_writes(
    client, english, monkeypatch, indices
):
    job_id = _phrase_job(client, english, monkeypatch)
    response = client.post(
        "/translation/phrases",
        json={"language_id": english.id, "job_id": job_id, "indices": indices},
    )
    assert response.status_code == 400
    assert db.session.query(DBTerm).count() == 0


def test_expired_phrase_job_is_rejected(client, english):
    db.session.commit()
    response = client.post(
        "/translation/phrases",
        json={"language_id": english.id, "job_id": "expired", "indices": [0]},
    )
    assert response.status_code == 404
    assert db.session.query(DBTerm).count() == 0


@pytest.mark.parametrize(
    "setting,value", [("codex_reasoning_effort", "low"), ("codex_fast_mode", True)]
)
def test_phrase_cards_require_current_translation_settings(
    client, english, monkeypatch, setting, value
):
    job_id = _phrase_job(client, english, monkeypatch)
    setattr(english, setting, value)
    db.session.commit()
    response = client.post(
        "/translation/phrases",
        json={"language_id": english.id, "job_id": job_id, "indices": [0]},
    )
    assert response.status_code == 400
    assert db.session.query(DBTerm).count() == 0
