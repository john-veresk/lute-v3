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
from tests.unit.read.test_codex_store import _result
from tests.unit.read.test_codex_translation import RESULT
from tests.unit.read.test_translation_jobs import make_books, enqueue, worker_for


def lookup(
    client,
    language,
    book,
    mode="auto",
    page=1,
    sentence="The cats sleep.",
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
    book = make_books(english, ["The cats sleep."])[0]
    info = contexts.prepare(db.session, english, book.id, 1, "The cats sleep.")
    db.session.delete(book)
    db.session.commit()
    store.save(
        db.session,
        english,
        "cats",
        info["sentence"],
        {**RESULT, "context_note": "Sleeping cats."},
        context_info=info,
    )
    assert store.find(db.session, english, "cats")["options"] == RESULT["options"]
    assert db.session.query(contexts.ContextNote).count() == 0


@pytest.mark.parametrize("cli", ["codex", "cursor"])
def test_usage_is_generated_with_dictionary_and_reused_only_in_its_book(
    client, english, monkeypatch, cli
):
    english.translation_cli = cli
    books = make_books(english, ["Before. The cats sleep. After."] * 2)
    calls = []

    def run_cli(command, workdir, selected_cli, prompt=None):
        prompt = command[-1] if selected_cli == "cursor" else prompt
        payload = json.loads(prompt.rsplit("\n", 1)[1])
        assert payload["sentence_context"] == "The cats sleep."
        assert payload["target_language"] == english.translation_target
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
        calls.append(True)
        reply = dict(RESULT)
        reply["context_note"] = f"The cats are asleep here. {len(calls)}"
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
    assert db.session.query(contexts.ContextNote).count() == 1

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


def test_book_review_reads_saved_usage_and_terms_review_stays_generic(
    client, english, monkeypatch
):
    books = make_books(english, ["Before. The cats sleep. After.", "The cats run."])
    word = Term(english, "cats")
    word.translation = "кошки"
    word.status = 1
    db.session.add(word)
    db.session.commit()
    info = contexts.prepare(db.session, english, books[0].id, 1, "The cats sleep.")
    reply = {
        **RESULT,
        "context_note": "The cats are asleep.",
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
    book = make_books(english, ["The cats sleep. The cats run."])[0]
    info = contexts.prepare(db.session, english, book.id, 1, "The cats sleep.")
    store.save(
        db.session,
        english,
        "cats",
        info["sentence"],
        {**RESULT, "context_note": "Sleeping cats."},
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
    book = make_books(english, ["Before. The cats sleep. After."])[0]
    enqueue(client, [book])
    worker, generate = worker_for(client, monkeypatch)
    assert worker.step()
    key = generate.call_args.args[0]
    assert key[11]["book_id"] == book.id
    assert key[11]["excerpt"] == "Before.\nThe cats sleep."
    generate.assert_called_once()


def test_existing_context_table_gets_sentence_positions_without_losing_notes():
    connection = sqlite3.connect(":memory:")
    migrations = Path("lute/db/schema/migrations")
    connection.executescript(
        (migrations / "20261016_translation_contexts.sql").read_text()
    )
    connection.execute("""INSERT INTO translationcontexts
        (language_id, book_id, text_lc, profile, context_key, page, sentence,
         excerpt, note, updated) VALUES (1, 1, 'cats', 'translation:7:EnglishRussian', 'old', 1,
         'The cats sleep.', 'The cats sleep.', 'Sleeping cats.', '2026-10-16')""")
    connection.executescript(
        (migrations / "20261016_translation_contexts_position.sql").read_text()
    )
    assert connection.execute(
        "SELECT note, sentence_index FROM translationcontexts"
    ).fetchall() == [("Sleeping cats.", -1)]
    connection.execute(
        "UPDATE translationcontexts SET sentence_index = 0 WHERE context_key = 'old'"
    )
    assert connection.execute(
        "SELECT sentence_index FROM translationcontexts"
    ).fetchone() == (0,)
    connection.close()
