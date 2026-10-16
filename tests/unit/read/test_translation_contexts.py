"""Reusable meanings and saved usage notes have independent lifetimes and scope."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from lute.db import db
from lute.models.term import Term
from lute.translation import contexts, service, store
from lute.translation.profile import cache_profile
from tests.unit.read.test_codex_store import _result
from tests.unit.read.test_codex_store import _lookup
from tests.unit.read.test_translation_fallback import paired_result
from tests.unit.read.test_translation_jobs import make_books, enqueue, worker_for


def lookup(
    client,
    language,
    book,
    mode="auto",
    page=1,
    sentence="The cats sleep.",
    fallback=False,
):
    return client.post(
        "/translation/jobs",
        json={
            "language_id": language.id,
            "text": "cats",
            "context": sentence,
            "kind": "term",
            "mode": mode,
            "book_id": book.id,
            "page_num": page,
            "fallback": fallback,
        },
    )


def test_context_window_crosses_pages_and_keeps_selected_sentence(english):
    book = make_books(english, [["Before.", "The cats sleep. After.", "Last."]])[0]
    info = contexts.prepare(db.session, english, book.id, 2, "The cats sleep.")
    assert info["excerpt"] == "Before.\nThe cats sleep.\nAfter."
    assert (
        contexts.prepare(db.session, english, book.id, 2, "After.")["excerpt"]
        == "The cats sleep.\nAfter.\nLast."
    )
    assert (
        contexts.prepare(db.session, english, book.id, 1, "Before.")["excerpt"]
        == "Before.\nThe cats sleep."
    )


def test_repeated_sentences_and_paragraphs_keep_the_correct_occurrence(english):
    book = make_books(
        english, ["Before.\n\nThe cats sleep.\n\nMiddle. The cats sleep. After."]
    )[0]
    first = contexts.prepare(db.session, english, book.id, 1, "The cats sleep.", 1)
    second = contexts.prepare(db.session, english, book.id, 1, "The cats sleep.", 3)
    assert first["excerpt"] == "Before.\nThe cats sleep.\nMiddle."
    assert second["excerpt"] == "Middle.\nThe cats sleep.\nAfter."
    assert (
        contexts.prepare(db.session, english, book.id, 1, "The cats sleep.", 2) is None
    )


def test_deleted_book_does_not_discard_the_dictionary_result(english):
    english.translation_mode = "personal"
    book = make_books(english, ["The cats sleep."])[0]
    info = contexts.prepare(db.session, english, book.id, 1, "The cats sleep.")
    db.session.delete(book)
    db.session.commit()
    store.save(
        db.session,
        english,
        "cats",
        info["sentence"],
        {**paired_result(), "context_note": "Sleeping cats."},
        context_info=info,
    )
    assert (
        store.find(db.session, english, "cats")["options"] == paired_result()["options"]
    )
    assert db.session.query(contexts.ContextNote).count() == 0


def test_learning_more_words_refreshes_hints_without_calling_model(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    db.session.commit()
    saved = {
        **paired_result(),
        "options": [{"translation": "animal", "explanation": ""}],
        "vocabulary": {
            "unknown": [{"text": "animal", "lemma": "animal"}],
            "revised": False,
        },
    }
    store.save(db.session, english, "cats", "The cats sleep.", saved)
    animal = Term(english, "animal")
    animal.status = 99
    db.session.add(animal)
    db.session.commit()
    generate = Mock()
    monkeypatch.setattr(service, "translate", generate)
    response = _lookup(client, english, text="cats", context="The cats run.")
    assert response.json["saved"] is True
    result = _result(client, response.json["job_id"])["result"]
    assert result["vocabulary"]["unknown"] == []
    assert result["options"] == saved["options"]
    generate.assert_not_called()


@pytest.mark.parametrize("cli", ["codex", "cursor"])
def test_usage_is_generated_with_dictionary_and_reused_only_in_its_book(
    client, english, monkeypatch, cli
):
    english.translation_mode = "personal"
    english.translation_cli = cli
    books = make_books(english, ["Before. The cats sleep. After."] * 2)
    calls = []

    def run_cli(command, workdir, selected_cli, prompt=None):
        prompt = command[-1] if selected_cli == "cursor" else prompt
        payload = json.loads(prompt.rsplit("\n", 1)[1])
        assert "sentence_context" not in payload
        assert payload["context_for_note"] == {
            "sentence": "The cats sleep.",
            "excerpt": "Before.\nThe cats sleep.\nAfter.",
        }
        schema = (
            json.loads(prompt.splitlines()[1])
            if selected_cli == "cursor"
            else json.loads(Path(workdir, "schema.json").read_text())
        )
        assert "context_note" in schema["required"]
        assert "context_note" in schema["properties"]["fallback"]["required"]
        calls.append(True)
        reply = paired_result()
        reply["context_note"] = f"The cats are asleep here. {len(calls)}"
        reply["fallback"] = {
            **reply["fallback"],
            "context_note": f"Здесь кошки спят. {len(calls)}",
        }
        if selected_cli == "cursor":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "result", "result": json.dumps(reply)}),
                stderr="",
            )
        Path(workdir, "translation.json").write_text(json.dumps(reply))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service, "_executable", lambda _: "/fake/cli")
    monkeypatch.setattr(service, "_run_cli", run_cli)
    first = _result(client, lookup(client, english, books[0]).json["job_id"])
    assert first["status"] == "complete", first
    assert first["result"]["context_note"].endswith("1")
    assert "context_note" not in store.find(db.session, english, "cats")
    assert "context_note" not in store.find(db.session, english, "cats")["fallback"]
    assert db.session.query(contexts.ContextNote).count() == 2

    other = lookup(client, english, books[1])
    assert other.json["saved"] is True
    assert "context_note" not in _result(client, other.json["job_id"])["result"]
    assert len(calls) == 1, "Opening another book never generates a usage note"
    refreshed = _result(
        client, lookup(client, english, books[1], mode="refresh").json["job_id"]
    )
    assert refreshed["result"]["context_note"].endswith("2")
    assert len(calls) == 2
    original = _result(client, lookup(client, english, books[0]).json["job_id"])[
        "result"
    ]
    assert original["context_note"].endswith("1")
    russian = _result(
        client, lookup(client, english, books[0], fallback=True).json["job_id"]
    )["result"]
    assert russian["context_note"] == "Здесь кошки спят. 1"
    assert len(calls) == 2


def test_book_review_reads_saved_usage_and_terms_review_stays_generic(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    books = make_books(english, ["Before. The cats sleep. After.", "The cats run."])
    word = Term(english, "cats")
    word.translation = "кошки"
    word.status = 1
    db.session.add(word)
    db.session.commit()
    info = contexts.prepare(db.session, english, books[0].id, 1, "The cats sleep.")
    reply = {
        **paired_result(),
        "context_note": "The cats are asleep.",
        "fallback_language": "Russian",
    }
    store.save(db.session, english, "cats", info["sentence"], reply, context_info=info)
    generate = Mock()
    monkeypatch.setattr(service, "translate", generate)
    url = f"/term/review/card/{word.id}"
    assert "book_context" not in client.get(url).json
    card = client.get(f"{url}?book_id={books[0].id}").json
    assert card["book_context"]["note"] == "The cats are asleep."
    assert card["book_context"]["excerpt"] == info["excerpt"]
    assert "book_context" not in client.get(f"{url}?book_id={books[1].id}").json
    word.status = 99
    db.session.commit()
    assert (
        client.get(f"{url}?book_id={books[0].id}").json["book_context"]["note"]
        == "The cats are asleep."
    )
    books[0].texts[0].text = "Before. The cats run. After."
    db.session.commit()
    assert "book_context" not in client.get(f"{url}?book_id={books[0].id}").json
    generate.assert_not_called()


def test_cached_usage_does_not_leak_to_another_sentence_in_same_book(client, english):
    english.translation_mode = "personal"
    book = make_books(english, ["The cats sleep. The cats run."])[0]
    info = contexts.prepare(db.session, english, book.id, 1, "The cats sleep.")
    store.save(
        db.session,
        english,
        "cats",
        info["sentence"],
        {**paired_result(), "context_note": "Sleeping cats."},
        context_info=info,
    )
    response = lookup(client, english, book, sentence="The cats run.")
    assert response.json["saved"] is True
    assert "context_note" not in _result(client, response.json["job_id"])["result"]


@pytest.mark.parametrize(
    "scope",
    [
        {"book_id": True, "page_num": 1},
        {"book_id": 99999, "page_num": 1},
        {"book_id": 1, "page_num": -1},
        {"book_id": 1, "page_num": "1"},
    ],
)
def test_invalid_context_scope_does_not_start_provider(
    client, english, monkeypatch, scope
):
    generate = Mock()
    monkeypatch.setattr(service, "translate", generate)
    response = client.post(
        "/translation/jobs", json={"language_id": english.id, "text": "cats", **scope}
    )
    assert response.status_code == 400
    generate.assert_not_called()


def test_bulk_job_passes_neighboring_sentences_without_extra_lookups(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    book = make_books(english, ["Before. The cats sleep. After."])[0]
    enqueue(client, [book])
    worker, generate = worker_for(client, monkeypatch)
    assert worker.step()
    key = generate.call_args.args[0]
    assert key[15]["book_id"] == book.id
    assert key[15]["excerpt"] == "Before.\nThe cats sleep."
    generate.assert_called_once()


def test_shared_profile_migration_reuses_latest_result_without_discarding_history():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE languages (LgID integer, LgName text);
        INSERT INTO languages VALUES (1, 'Finnish');
        CREATE TABLE codextranslations (CtID integer primary key, CtLgID integer, CtTextLC text, CtContext text, CtResult text, CtUpdated text, CtProfile text);
        CREATE UNIQUE INDEX profiles ON codextranslations (CtLgID, CtTextLC, CtProfile);
        INSERT INTO codextranslations VALUES (1, 1, 'kuusi', 'old context', 'old result', '2026-10-15', 'personal:old');
        INSERT INTO codextranslations VALUES (2, 1, 'kuusi', 'new context', 'latest result', '2026-10-16', 'personal:new');
        INSERT INTO codextranslations VALUES (3, 1, 'kuusi', '', 'ель', '2026-10-16', 'translation:7:FinnishRussian');
    """)
    connection.executescript(
        Path(
            "lute/db/schema/migrations/20261016_translation_shared_personal.sql"
        ).read_text()
    )
    assert connection.execute(
        "SELECT CtResult FROM codextranslations WHERE CtProfile = ?",
        (cache_profile("Finnish", "Finnish", "personal"),),
    ).fetchone() == ("latest result",)
    assert connection.execute("SELECT COUNT(*) FROM codextranslations").fetchone() == (
        4,
    )
    connection.close()
