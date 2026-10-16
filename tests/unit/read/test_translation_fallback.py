"""A per-card fallback uses the configured language without switching the main mode."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from bs4 import BeautifulSoup
import pytest
from sqlalchemy.exc import IntegrityError
from lute.db import db
from lute.translation import service, store
from lute.translation.profile import cache_profile, profile_for
from tests.unit.read.test_codex_translation import RESULT
from tests.unit.read.test_codex_store import _lookup, _result
from tests.unit.read.test_translation_jobs import (
    enqueue,
    get_job,
    make_books,
    worker_for,
)


def test_fallback_uses_configured_language_and_bypasses_personal_checks(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    english.translation_target = "French"
    db.session.commit()
    generate = Mock(return_value=RESULT)
    monkeypatch.setattr(service, "translate", generate)
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": english.id,
            "text": "cat",
            "mode": "refresh",
            "fallback": True,
        },
    )
    assert response.status_code == 202
    result = _result(client, response.json["job_id"])["result"]
    generate.assert_called_once()
    key = generate.call_args.args
    assert key[1] == "French"
    assert key[11:] == ("translation", "")
    assert "vocabulary" not in result
    assert english.translation_mode == "personal"
    assert store.find(db.session, english, "cat") is None
    assert _lookup(client, english, mode="stored", text="cat").json["job_id"] is None


def test_button_and_settings_labels_follow_the_configured_target(client, english):
    english.translation_mode = "personal"
    english.translation_target = "French"
    db.session.commit()
    card = BeautifulSoup(
        client.get(f"/term/editbytext/{english.id}/cat").data, "html.parser"
    )
    assert card.select_one("#codex-fallback").text == "French"
    settings = BeautifulSoup(
        client.get(f"/language/edit/{english.id}").data, "html.parser"
    )
    assert (
        settings.select_one('label[for="translation_target"]').text
        == "Fallback language"
    )
    english.translation_mode = "translation"
    db.session.commit()
    card = BeautifulSoup(
        client.get(f"/term/editbytext/{english.id}/cat").data, "html.parser"
    )
    assert card.select_one("#codex-fallback") is None
    settings = BeautifulSoup(
        client.get(f"/language/edit/{english.id}").data, "html.parser"
    )
    assert (
        settings.select_one('label[for="translation_target"]').text == "Translate into"
    )


@pytest.mark.parametrize("mode,fallback", [("translation", True), ("personal", "yes")])
def test_invalid_fallback_does_not_start_a_model(
    client, english, monkeypatch, mode, fallback
):
    english.translation_mode = mode
    db.session.commit()
    generate = Mock()
    monkeypatch.setattr(service, "translate", generate)
    response = client.post(
        "/translation/jobs",
        json={"language_id": english.id, "text": "cat", "fallback": fallback},
    )
    assert response.status_code == 400
    generate.assert_not_called()


def test_personal_mode_requires_a_fallback_language(client, english):
    response = client.post(
        f"/language/edit/{english.id}",
        data={
            "name": english.name,
            "parser_type": english.parser_type,
            "translation_mode": "personal",
            "translation_target": "",
        },
    )
    assert response.status_code == 200
    assert b"Please enter a translation language" in response.data


def test_fallback_word_cards_can_be_saved_in_personal_mode(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    english.translation_target = "French"
    db.session.commit()
    word = {
        "text": "cats",
        "translation": "chats",
        "lemma": "cat",
        "is_inflected": True,
        "lemma_translation": "chat",
    }
    result = {
        **RESULT,
        "words": [
            word,
            {
                "text": "sleep",
                "translation": "dormir",
                "lemma": "sleep",
                "is_inflected": False,
                "lemma_translation": "dormir",
            },
        ],
    }
    monkeypatch.setattr(service, "translate", lambda *args: result)
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": english.id,
            "text": "cats sleep",
            "mode": "refresh",
            "fallback": True,
        },
    )
    job_id = response.json["job_id"]
    _result(client, job_id)
    saved = client.post(
        "/translation/words",
        json={"language_id": english.id, "job_id": job_id, "indices": [0]},
    )
    assert saved.status_code == 200
    assert saved.json["saved"][0]["translation"] == "chats"
    assert english.translation_mode == "personal"


def paired_result(phrase=False):
    """Both languages describe exactly the same source cards and grammar."""
    personal = {
        "lemma": "" if phrase else "cat",
        "is_inflected": not phrase,
        "lemma_translation": "" if phrase else "cat",
        "lemma_options": [] if phrase else [{"translation": "cat", "explanation": ""}],
        "options": [
            {"translation": "cats sleep" if phrase else "cat", "explanation": ""}
        ],
        "words": [],
        "phrases": [] if phrase else [{"text": "cats sleep", "translation": "cat"}],
    }
    fallback = {
        **personal,
        "lemma_translation": "" if phrase else "кот",
        "lemma_options": [] if phrase else [{"translation": "кот", "explanation": ""}],
        "options": [
            {"translation": "кошки спят" if phrase else "кошки", "explanation": ""}
        ],
        "phrases": (
            [] if phrase else [{"text": "cats sleep", "translation": "кошки спят"}]
        ),
    }
    if phrase:
        personal["words"] = [
            {
                "text": "cats",
                "translation": "cat",
                "lemma": "cat",
                "is_inflected": True,
                "lemma_translation": "cat",
            },
            {
                "text": "sleep",
                "translation": "sleep",
                "lemma": "sleep",
                "is_inflected": False,
                "lemma_translation": "",
            },
        ]
        fallback["words"] = [
            {
                **personal["words"][0],
                "translation": "кошки",
                "lemma_translation": "кот",
            },
            {**personal["words"][1], "translation": "спать"},
        ]
    return {**personal, "fallback": fallback}


@pytest.mark.parametrize("cli", ["codex", "cursor"])
@pytest.mark.parametrize("phrase", [False, True])
def test_personal_cards_prepare_and_persist_fallback_in_one_cli_call(
    client, english, monkeypatch, cli, phrase
):
    english.translation_mode = "personal"
    english.translation_target = "Russian"
    english.translation_cli = cli
    db.session.commit()
    reply = paired_result(phrase)
    calls = []

    def run_cli(command, workdir, selected_cli, prompt=None):
        calls.append(command)
        prompt = command[-1] if selected_cli == "cursor" else prompt
        payload = json.loads(prompt.rsplit("\n", 1)[1])
        assert payload["target_language"] == "English"
        assert payload["fallback_language"] == "Russian"
        if selected_cli == "cursor":
            schema = json.loads(prompt.splitlines()[1])
        else:
            schema = json.loads(Path(workdir, "schema.json").read_text())
        assert schema["properties"]["fallback"] == service.SCHEMA
        assert "fallback" in schema["required"]
        if selected_cli == "cursor":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "result", "result": json.dumps(reply)}),
                stderr="",
            )
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps(reply)
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service, "_executable", lambda _: "/fake/cli")
    monkeypatch.setattr(service, "_run_cli", run_cli)
    text = "cats sleep" if phrase else "cats"
    response = _lookup(client, english, text=text, context="The cats sleep.")
    completed = _result(client, response.json["job_id"])
    assert completed["status"] == "complete", completed
    assert len(calls) == 1
    personal = completed["result"]
    assert personal["fallback_language"] == "Russian"
    assert store.find(db.session, english, text) == personal
    profile = cache_profile("English", "Russian")
    assert store.find(db.session, english, text, profile) == reply["fallback"]

    # Drop the in-memory cache to prove the fallback survives reopening/restarting.
    jobs = client.application.extensions["codex_translation_jobs"]
    with jobs.lock:
        jobs.jobs.clear()
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": english.id,
            "text": text,
            "context": "The cats sleep.",
            "fallback": True,
        },
    )
    assert response.json["saved"] is True
    fallback_job = response.json["job_id"]
    assert _result(client, fallback_job)["result"] == reply["fallback"]
    assert store.find(db.session, english, text) == personal
    assert (
        _lookup(client, english, text=text, context="The cats sleep.").json["saved"]
        is True
    )
    assert len(calls) == 1

    card_type = "words" if phrase else "phrases"
    saved = client.post(
        f"/translation/{card_type}",
        json={
            "language_id": english.id,
            "job_id": fallback_job,
            "indices": [0],
        },
    )
    assert saved.status_code == 200, saved.json
    assert (
        saved.json["saved"][0]["translation"]
        == reply["fallback"][card_type][0]["translation"]
    )


@pytest.mark.parametrize("defect", ["missing", "phrase", "lemma", "word"])
def test_incomplete_or_mismatched_fallback_is_rejected(defect):
    reply = paired_result(phrase=defect == "word")
    words = ["cats", "sleep"] if defect == "word" else []
    if defect == "missing":
        del reply["fallback"]
    elif defect == "phrase":
        reply["fallback"]["phrases"] = []
    elif defect == "lemma":
        reply["fallback"]["lemma"] = "kitten"
    else:
        reply["fallback"]["words"][0]["lemma"] = "kitten"
    with pytest.raises(service.TranslationError, match="invalid translation"):
        service._parse_translation(
            json.dumps(reply), "term", words, ("cats sleep",), "codex", "Russian"
        )


def test_book_job_prepares_fallback_using_snapshotted_language(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    english.translation_target = "Russian"
    book = make_books(english, ["Cats."])[0]
    enqueue(client, [book])
    original_profile = profile_for(db.session, english)
    english.translation_target = "French"
    db.session.commit()
    reply = {**paired_result(), "phrases": []}
    reply["fallback"]["phrases"] = []
    generate = Mock(return_value={**reply, "fallback_language": "Russian"})
    monkeypatch.setattr(service, "translate", generate)
    worker = client.application.extensions["book_translation_worker"]
    assert worker.step()
    generate.assert_called_once()
    assert generate.call_args.args[14] == "Russian"
    assert (
        store.find(db.session, english, "Cats", original_profile)["fallback_language"]
        == "Russian"
    )
    assert (
        store.find(db.session, english, "Cats", cache_profile("English", "Russian"))
        == reply["fallback"]
    )
    assert store.find(db.session, english, "Cats") is None


def test_translation_profiles_migration_preserves_existing_results():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE codextranslations (CtLgID integer, CtTextLC text, CtProfile text, CtResult text);
        CREATE UNIQUE INDEX CtLgIDTextLC ON codextranslations (CtLgID, CtTextLC);
        INSERT INTO codextranslations VALUES (1, 'kissa', 'personal:old', 'old explanation');
    """)
    migration = Path("lute/db/schema/migrations/20261016_translation_profiles.sql")
    connection.executescript(migration.read_text())
    connection.execute(
        "INSERT INTO codextranslations VALUES (1, 'kissa', 'translation:7:FinnishRussian', 'кошка')"
    )
    assert connection.execute(
        "SELECT CtResult FROM codextranslations ORDER BY rowid"
    ).fetchall() == [
        ("old explanation",),
        ("кошка",),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO codextranslations VALUES (1, 'kissa', 'personal:old', 'duplicate')"
        )
    connection.close()


def test_refreshing_fallback_keeps_personal_and_other_target_translations(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    db.session.commit()
    personal = {**paired_result(), "fallback_language": "Russian"}
    store.save(db.session, english, "cats", "The cats sleep.", personal)
    french_profile = cache_profile("English", "French")
    store.save(db.session, english, "cats", "", RESULT, french_profile)
    generate = Mock(return_value=RESULT)
    monkeypatch.setattr(service, "translate", generate)
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": english.id,
            "text": "cats",
            "fallback": True,
            "mode": "refresh",
        },
    )
    assert _result(client, response.json["job_id"])["status"] == "complete"
    generate.assert_called_once()
    assert store.find(db.session, english, "cats") == personal
    assert store.find(db.session, english, "cats", french_profile) == RESULT
    assert (
        store.find(db.session, english, "cats", cache_profile("English", "Russian"))
        == RESULT
    )


def test_existing_personal_book_job_snapshots_fallback_once(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    book = make_books(english, ["Cats sleep."])[0]
    job_id = enqueue(client, [book])[0]
    job = get_job(job_id)
    settings = json.loads(job.settings)
    del settings["fallback_target"]
    job.settings = json.dumps(settings)
    db.session.commit()
    worker, generate = worker_for(client, monkeypatch)
    assert worker.step()
    assert generate.call_args.args[0][14] == "Russian"
    assert json.loads(get_job(job_id).settings)["fallback_target"] == "Russian"
    english.translation_target = "French"
    db.session.commit()
    assert worker.step()
    assert generate.call_args.args[0][14] == "Russian"


def test_profile_insert_conflict_retries_both_variants(english, monkeypatch):
    english.translation_mode = "personal"
    db.session.commit()
    result = {**paired_result(), "fallback_language": "Russian"}
    commit = db.session.commit
    attempts = []

    def commit_with_conflict():
        attempts.append(True)
        if len(attempts) == 1:
            raise IntegrityError("insert", {}, Exception("concurrent insert"))
        commit()

    monkeypatch.setattr(db.session, "commit", commit_with_conflict)
    store.save(db.session, english, "cats", "The cats sleep.", result)
    assert len(attempts) == 2
    assert store.find(db.session, english, "cats") == result
    assert (
        store.find(db.session, english, "cats", cache_profile("English", "Russian"))
        == result["fallback"]
    )
