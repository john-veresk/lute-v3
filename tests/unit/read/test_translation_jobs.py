"""Persistent queue commands and server execution, without invoking a real CLI."""

import json
import threading
import time
from datetime import timedelta
from unittest.mock import Mock
import pytest
from lute.db import db
from lute.models.term import Term
from lute.models.language import Language
from lute.models.book import BookTag
from lute.translation import store
from lute.translation.bulk import BookTranslationJob, BookTranslationWorker, utcnow
from lute.translation.service import RateLimitError, TranslationError
from tests.unit.read.test_codex_translation import RESULT
from tests.utils import make_book


def make_books(language, contents):
    books = [
        make_book(f"Book {i}", content, language) for i, content in enumerate(contents)
    ]
    db.session.add_all(books)
    db.session.commit()
    return books


def enqueue(client, books, **kwargs):
    response = client.post(
        "/jobs", json={"book_ids": [book.id for book in books], **kwargs}
    )
    assert response.status_code == 201, response.json
    return [job["id"] for job in response.json["jobs"]]


def get_job(job_id):
    db.session.expire_all()
    return db.session.get(BookTranslationJob, job_id)


def worker_for(client, monkeypatch):
    worker = client.application.extensions["book_translation_worker"]
    translate = Mock(return_value=RESULT)
    monkeypatch.setattr(worker, "_translate", translate)
    return worker, translate


def test_jobs_navigation_and_server_only_page(client, spanish, monkeypatch):
    worker, translate = worker_for(client, monkeypatch)
    monkeypatch.setattr(
        worker, "step", Mock(side_effect=AssertionError("HTTP cannot execute jobs"))
    )
    page = client.get("/jobs").data.decode()
    assert page.index('id="menu_review"') < page.index('id="menu_jobs"')
    assert 'href="/jobs" aria-current="page"' in page
    assert "translation-jobs.js" in page
    assert "pretranslate.js" not in page
    assert client.get("/jobs/state").status_code == 200
    translate.assert_not_called()


def test_enqueue_starts_at_reading_progress_and_allows_override(
    client, spanish, monkeypatch
):
    books = make_books(
        spanish, [["Primero.", "Segundo.", "Tercero."], ["Antes.", "Después."]]
    )
    books[0].current_tx_id = books[0].texts[1].id
    books[1].current_tx_id = books[1].texts[1].id
    db.session.commit()
    choices = {book["id"]: book for book in client.get("/jobs/state").json["books"]}
    assert choices[books[0].id]["start_page"] == 2
    assert choices[books[1].id]["page_count"] == 2
    ids = enqueue(client, books, start_pages={str(books[1].id): 1})
    assert get_job(ids[0]).start_page == 2
    assert get_job(ids[1]).start_page == 1
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    assert translate.call_args.args[0][3:5] == ("Segundo", "Segundo.")
    assert get_job(ids[0]).current_page == 2
    assert get_job(ids[0]).total == 2
    assert get_job(ids[0]).done == 1
    assert books[0].texts[1].start_date is None
    assert books[0].texts[1].read_date is None


@pytest.mark.parametrize("page", [0, -1, 3, True, "2", None, 1.5])
def test_invalid_start_pages_are_atomic(client, spanish, page):
    books = make_books(spanish, [["Uno.", "Dos."], "Tres."])
    response = client.post(
        "/jobs",
        json={
            "book_ids": [book.id for book in books],
            "start_pages": {str(books[0].id): page},
        },
    )
    assert response.status_code == 400
    assert db.session.query(BookTranslationJob).count() == 0


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"book_ids": []},
        {"book_ids": [True]},
        {"book_ids": ["1"]},
        {"book_ids": [1], "start_pages": []},
    ],
)
def test_invalid_submissions(client, body):
    assert client.post("/jobs", json=body).status_code == 400


def test_queue_duplicates_order_pause_resume_cancel(client, spanish, monkeypatch):
    books = make_books(spanish, ["Uno.", "Dos.", "Tres."])
    ids = enqueue(client, books)
    assert enqueue(client, books) == []
    assert client.post(f"/jobs/{ids[2]}/up").status_code == 200
    assert client.post(f"/jobs/{ids[2]}/up").status_code == 200
    ordered = [job["id"] for job in client.get("/jobs/state").json["jobs"]]
    assert ordered == [ids[2], ids[0], ids[1]]
    assert client.post(f"/jobs/{ids[2]}/pause").json["status"] == "paused"
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    assert translate.call_args.args[0][3] == "Uno"
    assert get_job(ids[0]).status == "complete"
    assert client.post(f"/jobs/{ids[2]}/resume").json["status"] == "queued"
    worker.step()
    assert translate.call_args.args[0][3] == "Tres"
    assert client.post(f"/jobs/{ids[1]}/cancel").json["status"] == "cancelled"
    assert not worker.step()
    assert client.post(f"/jobs/{ids[0]}/resume").status_code == 409
    assert client.post(f"/jobs/{ids[0]}/nonsense").status_code == 409
    assert client.post("/jobs/999999/pause").status_code == 404


def test_only_unknown_unique_words_are_translated_with_context(
    client, spanish, monkeypatch
):
    book = make_books(spanish, [["Gato gato. Perro.", "Casa. Hola. Adiós."]])[0]
    for word, status in [("Perro", 1), ("Casa", 98), ("Hola", 99)]:
        term = Term(spanish, word)
        term.status = status
        db.session.add(term)
    db.session.commit()
    store.save(db.session, spanish, "Adiós", "", RESULT)
    job_id = enqueue(client, [book])[0]
    worker, translate = worker_for(client, monkeypatch)
    while worker.step():
        pass
    job = get_job(job_id)
    assert (job.total, job.done, job.translated, job.skipped) == (2, 2, 1, 1)
    assert job.status == "complete"
    assert translate.call_count == 1
    key = translate.call_args.args[0]
    assert key[3:5] == ("Gato", "Gato gato.")
    assert key[8] is False
    assert store.find(db.session, spanish, "gato") == RESULT
    assert db.session.query(Term).filter_by(language_id=spanish.id).count() == 3


@pytest.mark.parametrize("status", [1, 2, 3, 4, 5, 98, 99])
def test_learning_and_known_words_are_excluded(client, spanish, status):
    book = make_books(spanish, ["Gato."])[0]
    term = Term(spanish, "Gato")
    term.status = status
    db.session.add(term)
    db.session.commit()
    job_id = enqueue(client, [book])[0]
    worker = client.application.extensions["book_translation_worker"]
    worker.step()
    assert get_job(job_id).total == 0
    assert get_job(job_id).status == "complete"


def test_rechecks_unknown_status_before_each_word(client, spanish, monkeypatch):
    book = make_books(spanish, ["Gato perro."])[0]
    job_id = enqueue(client, [book])[0]
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    term = Term(spanish, "perro")
    term.status = 5
    db.session.add(term)
    db.session.commit()
    worker.step()
    assert translate.call_count == 1
    assert get_job(job_id).skipped == 1


def test_failure_retries_same_word_and_keeps_history(client, spanish, monkeypatch):
    book = make_books(spanish, ["Gato perro."])[0]
    job_id = enqueue(client, [book])[0]
    worker, translate = worker_for(client, monkeypatch)
    translate.side_effect = TranslationError("Network failed")
    for attempt in range(1, 4):
        worker.step()
        job = get_job(job_id)
        assert job.done == 0
        assert job.current_word == "Gato"
        assert job.attempts == attempt
        assert job.status == ("error" if attempt == 3 else "waiting")
        if attempt < 3:
            assert not worker.step()
            job = get_job(job_id)
            job.retry_at = utcnow() - timedelta(seconds=1)
            db.session.commit()
    assert len(json.loads(get_job(job_id).errors)) == 3
    assert client.post(f"/jobs/{job_id}/resume").status_code == 200
    translate.side_effect = None
    worker.step()
    worker.step()
    job = get_job(job_id)
    assert job.status == "complete"
    assert job.done == 2
    assert job.error_count == 3
    assert len(job.payload()["errors"]) == 3


def test_rate_limit_pauses_server_queue_without_advancing(client, spanish, monkeypatch):
    books = make_books(spanish, ["Gato.", "Perro."])
    ids = enqueue(client, books)
    worker, translate = worker_for(client, monkeypatch)
    translate.side_effect = RateLimitError(30)
    worker.step()
    job = get_job(ids[0])
    assert job.status == "waiting"
    assert job.done == 0
    assert job.retry_at > utcnow()
    assert not worker.step()
    assert get_job(ids[1]).status == "queued"
    job = get_job(ids[0])
    job.retry_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    translate.side_effect = None
    worker.step()
    assert get_job(ids[0]).done == 1
    assert translate.call_args.args[0][3] == "Gato"


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_commands_during_cli_finish_word_and_save_result(
    client, spanish, monkeypatch, action
):
    book = make_books(spanish, ["Gato perro."])[0]
    job_id = enqueue(client, [book])[0]
    worker = client.application.extensions["book_translation_worker"]
    started = threading.Event()
    release = threading.Event()

    def translate(*_args):
        started.set()
        assert release.wait(5)
        return RESULT

    monkeypatch.setattr(worker, "_translate", translate)
    thread = threading.Thread(target=worker.step)
    thread.start()
    try:
        assert started.wait(5)
        assert client.post(f"/jobs/{job_id}/{action}").status_code == 200
        if action == "pause":
            assert client.post(f"/jobs/{job_id}/resume").status_code == 409
    finally:
        release.set()
        thread.join(5)
    job = get_job(job_id)
    assert job.status == ("paused" if action == "pause" else "cancelled")
    assert job.done == 1
    assert store.find(db.session, spanish, "Gato") == RESULT
    assert not worker.step()


def test_server_worker_runs_without_client_polling(client, spanish, monkeypatch):
    book = make_books(spanish, ["Gato perro."])[0]
    language_id = spanish.id
    job_id = enqueue(client, [book])[0]
    monkeypatch.setattr("lute.translation.service.translate", lambda *_args: RESULT)
    worker = client.application.extensions["book_translation_worker"]
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and get_job(job_id).status != "complete":
            db.session.remove()
            time.sleep(0.02)
        assert get_job(job_id).status == "complete"
        assert get_job(job_id).done == 2
        assert (
            store.find(db.session, db.session.get(Language, language_id), "perro")
            == RESULT
        )
    finally:
        worker.stop()
        client.application.extensions["codex_translation_jobs"].pool.shutdown(wait=True)


def test_restart_preserves_checkpoint_and_requires_resume(client, spanish, monkeypatch):
    book = make_books(spanish, ["Gato perro."])[0]
    job_id = enqueue(client, [book])[0]
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    assert get_job(job_id).done == 1
    restarted = BookTranslationWorker(client.application)
    restarted.start()
    try:
        job = get_job(job_id)
        assert job.status == "paused"
        assert job.done == 1
        assert "restarted" in job.error
    finally:
        restarted.stop()
    client.application.extensions["book_translation_worker"] = restarted
    monkeypatch.setattr(restarted, "_translate", translate)
    assert client.post(f"/jobs/{job_id}/resume").status_code == 200
    restarted.step()
    assert get_job(job_id).done == 2
    assert translate.call_count == 2
    assert translate.call_args.args[0][3] == "perro"


def test_deleted_book_reports_error_and_queue_continues(client, spanish, monkeypatch):
    books = make_books(spanish, ["Gato.", "Perro."])
    ids = enqueue(client, books)
    db.session.delete(books[0])
    db.session.commit()
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    # Preparation errors stop immediately rather than retrying unavailable books.
    assert get_job(ids[0]).status == "error"
    assert "deleted" in get_job(ids[0]).error
    worker.step()
    assert get_job(ids[1]).status == "complete"
    assert translate.call_count == 1


def test_state_includes_book_tags(client, spanish):
    book = make_books(spanish, ["Gato."])[0]
    book.book_tags = [BookTag.make_book_tag("news"), BookTag.make_book_tag("study")]
    db.session.commit()
    choice = next(
        book_info
        for book_info in client.get("/jobs/state").json["books"]
        if book_info["id"] == book.id
    )
    assert choice["tags"] == ["news", "study"]


@pytest.mark.parametrize("cli", ["codex", "cursor"])
def test_job_snapshots_language_options_and_uses_standard_processing(
    client, spanish, monkeypatch, cli
):
    spanish.codex_model = "original-model"
    spanish.codex_reasoning_effort = "low"
    spanish.codex_fast_mode = True
    spanish.translation_cli = cli
    book = make_books(spanish, ["Gato."])[0]
    enqueue(client, [book])
    spanish.codex_model = "new-model"
    spanish.translation_target = "English"
    db.session.commit()
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    key = translate.call_args.args[0]
    assert key[1:3] == ("Russian", "original-model")
    assert key[7:9] == ("low" if cli == "codex" else "", False)
    assert key[10] == cli


def test_resuming_earlier_book_does_not_interrupt_running_book(
    client, spanish, monkeypatch
):
    books = make_books(spanish, ["Gato.", "Perro casa."])
    ids = enqueue(client, books)
    client.post(f"/jobs/{ids[0]}/pause")
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    client.post(f"/jobs/{ids[0]}/resume")
    worker.step()
    assert translate.call_args.args[0][3] == "casa"
    assert get_job(ids[1]).status == "complete"
    assert get_job(ids[0]).done == 0


@pytest.mark.parametrize(
    "category", ["cli_missing", "authentication_or_access", "unsupported_model"]
)
def test_permanent_errors_do_not_retry_automatically(
    client, spanish, monkeypatch, category
):
    book = make_books(spanish, ["Gato."])[0]
    job_id = enqueue(client, [book])[0]
    worker, translate = worker_for(client, monkeypatch)
    translate.side_effect = TranslationError("Fix CLI configuration", category=category)
    worker.step()
    assert get_job(job_id).status == "error"
    assert get_job(job_id).done == 0
    assert not worker.step()


def test_automatic_recovery_clears_current_error_but_keeps_history(
    client, spanish, monkeypatch
):
    book = make_books(spanish, ["Gato."])[0]
    job_id = enqueue(client, [book])[0]
    worker, translate = worker_for(client, monkeypatch)
    translate.side_effect = TranslationError("Temporary network error")
    worker.step()
    job = get_job(job_id)
    job.retry_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    translate.side_effect = None
    worker.step()
    job = get_job(job_id)
    assert job.status == "complete"
    assert job.error == ""
    assert job.error_count == 1
    assert job.payload()["errors"][0]["message"] == "Temporary network error"
