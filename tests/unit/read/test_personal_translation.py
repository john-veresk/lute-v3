"""Personal explanations use the learner's word families and separate caches."""

import json
import sqlite3
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from lute.db import db
from lute.models.language import Language
from lute.models.term import Term
from lute.translation import service, store
from lute.translation.profile import cache_profile, known_words, vocabulary_for
from tests.unit.read.test_codex_store import _lookup, _result
from tests.unit.read.test_codex_translation import RESULT
from tests.unit.read.test_translation_jobs import enqueue, make_books, worker_for


def term(language, text, status=1, parents=()):
    item = Term(language, text)
    item.status = status
    item.parents = list(parents)
    db.session.add(item)
    return item


def test_known_forms_use_only_root_parents_even_when_parent_is_new(english, spanish):
    root = term(english, "go")
    intermediate = term(english, "going", parents=[root])
    term(english, "went", 99, [intermediate])
    term(english, "gone", 5, [root])
    term(english, "cat", 99)
    term(english, "kitten", 98)
    term(english, "learning", 3)
    term(spanish, "gato", 99)
    db.session.commit()

    assert known_words(db.session, english) == ("cat", "go")
    assert root.status == 1


def test_multiple_parents_are_deduplicated_and_foreign_links_are_ignored(
    english, spanish
):
    first = term(english, "see", 99)
    second = term(english, "saw")
    foreign = term(spanish, "sierra", 99)
    term(english, "saws", 99, [first, second, foreign])
    db.session.commit()
    assert known_words(db.session, english) == ("saw", "see")


def test_cyclic_parents_do_not_hang_or_drop_known_vocabulary(english):
    first = term(english, "a", 99)
    second = term(english, "b", 99, [first])
    first.parents = [second]
    db.session.commit()
    assert known_words(db.session, english) == ("a",)


def test_personal_mode_is_saved_without_a_separate_target(client, spanish):
    response = client.post(
        f"/language/edit/{spanish.id}",
        data={
            "name": spanish.name,
            "parser_type": spanish.parser_type,
            "translation_mode": "personal",
            "translation_target": "",
        },
    )
    assert response.status_code == 302
    db.session.refresh(spanish)
    assert spanish.translation_mode == "personal"
    assert spanish.translation_target_name == "Spanish"
    assert Language.from_dict(spanish.to_dict()).translation_mode == "personal"
    page = BeautifulSoup(client.get(f"/language/edit/{spanish.id}").data, "html.parser")
    assert (
        page.select_one("#translation_mode option[selected]").text == "Personal Spanish"
    )
    assert page.select_one("#translation-target-row").has_attr("hidden")
    assert (
        b"Personal Spanish"
        in client.get(f"/translation/panel?language_id={spanish.id}").data
    )


def test_unknown_output_mode_is_rejected(client):
    response = client.post(
        "/language/new",
        data={
            "name": "Invalid",
            "parser_type": "spacedel",
            "translation_mode": "other",
        },
    )
    assert response.status_code == 200
    assert b"Not a valid choice" in response.data


@pytest.mark.parametrize("kind", ["term", "sentence"])
def test_personal_lookup_passes_only_a_local_revision(
    client, english, monkeypatch, kind
):
    root = term(english, "go")
    term(english, "went", 99, [root])
    term(english, "cat", 99)
    english.translation_mode = "personal"
    db.session.commit()
    monkeypatch.setattr(service, "translate", lambda *args: RESULT)
    response = _lookup(client, english, text="walk", kind=kind)
    jobs = client.application.extensions["codex_translation_jobs"]
    key = jobs.key_for(response.json["job_id"])
    assert key[1] == "English"
    assert key[11:] == ("personal", vocabulary_for(db.session, english))
    assert isinstance(key[12], str) and len(key[12]) == 64
    jobs.pool.shutdown(wait=True)


def test_personal_prompt_covers_terms_sentences_and_cards_without_translation_rules():
    prompt = service._prompt(
        "Finnish",
        "Finnish",
        "keskeyttää",
        "Älä keskeytä.",
        "term",
        [],
        (),
        "personal",
    )
    instructions, raw = prompt.rsplit("\n", 1)
    payload = json.loads(raw)
    assert "known_words" not in payload
    assert "revision" not in payload
    assert payload["sentence_context"] == "Älä keskeytä."
    assert "simplified paraphrase" in instructions
    assert "only the meaning in sentence_context" in instructions
    assert "common meanings outside sentence_context" not in instructions
    assert "return a word card for EACH entry" in instructions


@pytest.mark.parametrize("cli", ["codex", "cursor"])
def test_personal_output_reaches_both_cli_prompts(monkeypatch, cli):
    monkeypatch.setattr(service, "_executable", lambda _: "/fake/cli")
    calls = []

    def run(*args):
        calls.append(args)
        return RESULT

    monkeypatch.setattr(service, f"_translate_with_{cli}", run)
    assert (
        service.translate(
            "Finnish",
            "Russian",
            "",
            "kissa",
            "Kissa nukkuu.",
            cli=cli,
            translation_mode="personal",
            vocabulary_revision="local-only-revision-must-not-reach-provider",
        )
        == RESULT
    )
    payload = json.loads(calls[0][5].rsplit("\n", 1)[1])
    assert payload["target_language"] == "Finnish"
    assert "known_words" not in payload
    assert "local-only-revision-must-not-reach-provider" not in calls[0][5]


def test_refresh_replaces_russian_cache_without_changing_existing_card(
    client, english, monkeypatch
):
    card = term(english, "walk")
    card.translation = "гулять"
    db.session.commit()
    store.save(db.session, english, "walk", "I walk.", RESULT)
    english.translation_mode = "personal"
    db.session.commit()
    calls = []
    personal = {
        **RESULT,
        "options": [{"translation": "Go on foot.", "explanation": "I walk home."}],
    }

    def translate(*args):
        calls.append(args)
        return personal

    monkeypatch.setattr(service, "translate", translate)
    assert store.find(db.session, english, "walk") is None
    response = _lookup(client, english, "refresh", "walk", "I walk.")
    generated = _result(client, response.json["job_id"])["result"]
    assert generated["options"] == personal["options"]
    assert store.find(db.session, english, "walk") == generated
    db.session.refresh(card)
    assert card.translation == "гулять"
    assert len(calls) == 2
    assert (
        _lookup(client, english, text="walk", context="I walk.").json["saved"] is True
    )


def test_personal_cache_changes_with_vocabulary_and_sentence(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    db.session.commit()
    monkeypatch.setattr(service, "translate", lambda *args: RESULT)
    first = _lookup(client, english)
    first_id = first.json["job_id"]
    _result(client, first_id)
    assert _lookup(client, english).json["saved"] is True

    term(english, "cat", 99)
    db.session.commit()
    updated = _lookup(client, english)
    assert updated.json["saved"] is False
    assert updated.json["job_id"] != first_id
    _result(client, updated.json["job_id"])
    assert (
        _lookup(client, english, context="Different sentence.").json["saved"] is False
    )
    client.application.extensions["codex_translation_jobs"].pool.shutdown(wait=True)


def test_inflight_result_keeps_its_original_profile(client, english, monkeypatch):
    english.translation_mode = "personal"
    db.session.commit()
    monkeypatch.setattr(service, "translate", lambda *args: RESULT)
    response = _lookup(client, english)
    english.translation_mode = "translation"
    db.session.commit()
    _result(client, response.json["job_id"])
    assert store.find(db.session, english, "gato") is None
    english.translation_mode = "personal"
    assert store.find(db.session, english, "gato")["options"] == RESULT["options"]


def test_parent_suggestion_does_not_prefer_saved_russian_in_personal_mode(
    client, english
):
    root = term(english, "go", 99)
    root.translation = "идти"
    english.translation_mode = "personal"
    db.session.commit()
    data = client.get(f"/translation/parent?language_id={english.id}&text=go").json
    assert data == {"exists": True, "translation": "", "status": 99}
    assert root.translation == "идти"


def test_book_job_snapshots_personal_vocabulary_and_cache_profile(
    client, english, monkeypatch
):
    term(english, "cat", 99)
    english.translation_mode = "personal"
    book = make_books(english, ["Dog."])[0]
    store.save(db.session, english, "Dog", "Dog.", RESULT)
    job_id = enqueue(client, [book])[0]
    term(english, "house", 99)
    english.translation_mode = "translation"
    db.session.commit()
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    translate.assert_called_once()
    row = db.session.get(store.StoredTranslation, 1)
    assert row.profile.startswith("personal:")
    job = client.get("/jobs/state").json["jobs"][0]
    assert job["id"] == job_id
    assert job["settings"]["target_label"] == "Personal English"
    assert "known_words" not in job["settings"]


def test_book_job_passes_snapshot_and_saves_under_snapshot_profile(
    client, english, monkeypatch
):
    term(english, "cat", 99)
    english.translation_mode = "personal"
    book = make_books(english, ["Dog."])[0]
    enqueue(client, [book])
    english.translation_mode = "translation"
    db.session.commit()
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    key = translate.call_args.args[0]
    assert key[1] == "English"
    assert key[11:] == ("personal", vocabulary_for(db.session, english, "personal"))
    assert store.find(db.session, english, "Dog") is None
    english.translation_mode = "personal"
    assert store.find(db.session, english, "Dog") == RESULT


def test_schema_change_preserves_existing_cache_without_rewriting_results():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE languages (LgID integer, LgName text, LgTranslationTarget text);
        INSERT INTO languages VALUES (1, 'Finnish', 'Russian');
        CREATE TABLE codextranslations (CtLgID integer, CtResult text);
        INSERT INTO codextranslations VALUES (1, 'original translation');
    """)
    migration = Path("lute/db/schema/migrations/20261016_personal_translation.sql")
    connection.executescript(migration.read_text())
    profile, result = connection.execute(
        "SELECT CtProfile, CtResult FROM codextranslations"
    ).fetchone()
    assert profile == cache_profile("Finnish", "Russian")
    assert result == "original translation"
    connection.close()
