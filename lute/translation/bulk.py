"""Persistent book translation queue, executed by a single server worker."""

import json
import threading
from datetime import datetime, timedelta, timezone
from flask import current_app
from sqlalchemy.orm import deferred
from lute.db import db
from lute.models.book import Book
from lute.models.language import Language
from lute.models.term import Term
from lute.translation import store
from lute.translation.service import RateLimitError, TranslationError

ACTIVE = ("queued", "running", "waiting", "paused", "error")


def utcnow():
    """Naive UTC timestamps match the SQLite DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BookTranslationJob(db.Model):
    """Durable work list and checkpoint; vocabulary itself is never modified."""

    __tablename__ = "booktranslationjobs"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(
        db.Integer, db.ForeignKey("books.BkID", ondelete="SET NULL"), nullable=True
    )
    title = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="queued")
    start_page = db.Column(db.Integer, nullable=False, default=1)
    errors = db.Column(db.Text, nullable=False, default="[]")
    position = db.Column(db.Integer, nullable=False)
    settings = db.Column(db.Text, nullable=False)
    items = deferred(db.Column(db.Text, nullable=True))
    total = db.Column(db.Integer, nullable=False, default=0)
    done = db.Column(db.Integer, nullable=False, default=0)
    translated = db.Column(db.Integer, nullable=False, default=0)
    skipped = db.Column(db.Integer, nullable=False, default=0)
    current_word = db.Column(db.Text, nullable=False, default="")
    current_context = db.Column(db.Text, nullable=False, default="")
    current_page = db.Column(db.Integer, nullable=True)
    error = db.Column(db.Text, nullable=False, default="")
    error_count = db.Column(db.Integer, nullable=False, default=0)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    retry_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def payload(self, prepared=None):
        """Public state, without the potentially large work list."""
        fields = (
            "id",
            "book_id",
            "title",
            "status",
            "position",
            "total",
            "done",
            "translated",
            "skipped",
            "current_word",
            "current_context",
            "current_page",
            "error",
            "error_count",
            "attempts",
            "start_page",
        )
        result = {field: getattr(self, field) for field in fields}
        for field in (
            "created_at",
            "started_at",
            "finished_at",
            "updated_at",
            "retry_at",
        ):
            value = getattr(self, field)
            result[field] = value.isoformat() + "Z" if value else None
        result["prepared"] = self.items is not None if prepared is None else prepared
        result["settings"] = json.loads(self.settings)
        result["errors"] = json.loads(self.errors)
        return result


def language_settings(language):
    """Snapshot settings so a queued book has predictable translation options."""
    return {
        "language_id": language.id,
        "source": language.name,
        "target": language.translation_target,
        "model": language.codex_model,
        "effort": language.codex_reasoning_effort,
        "cli": language.translation_cli or "codex",
    }


def collect_words(book, start_page=1):
    """Unique unknown words in reading order, with their first sentence context."""
    language = book.language
    known = {
        text.replace("\u200b", "")
        for (text,) in db.session.query(Term.text_lc).filter(
            Term.language_id == language.id, Term.status != 0
        )
    }
    seen = set()
    words = []
    for page in book.texts:
        if page.order < start_page:
            continue
        sentence = []

        def append_sentence():
            context = (
                "".join(token.token for token in sentence).replace("\u200b", "").strip()
            )
            for token in sentence:
                key = store.text_key(language, token.token)
                if not token.is_word or key in seen or key in known:
                    continue
                seen.add(key)
                words.append(
                    {"text": token.token, "context": context[:4000], "page": page.order}
                )

        for token in language.get_parsed_tokens(page.text):
            sentence.append(token)
            if token.is_end_of_sentence:
                append_sentence()
                sentence = []
        append_sentence()
    return words


class BookTranslationWorker:
    """Own execution on the server; HTTP requests only mutate queue state."""

    def __init__(self, app):
        self.app = app
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.thread = None
        self.inflight = None
        self.cached_job_id = None
        self.cached_items = None

    def start(self):
        """Recover interrupted jobs as paused, requiring an explicit resume."""
        with self.app.app_context(), self.lock:
            for job in db.session.query(BookTranslationJob).filter(
                BookTranslationJob.status.in_(("running", "waiting"))
            ):
                job.status = "paused"
                job.retry_at = None
                job.error = (
                    "Server restarted. Resume to continue from the saved position."
                )
                job.updated_at = utcnow()
            db.session.commit()
        self.thread = threading.Thread(
            target=self._run, name="lute-book-jobs", daemon=True
        )
        self.thread.start()

    def stop(self):
        """Stop between requests; useful for orderly shutdown and tests."""
        self.stopped.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=5)

    def notify(self):
        self.wake.set()

    def _run(self):
        while not self.stopped.is_set():
            self.wake.clear()
            try:
                worked = self.step()
            except Exception:  # pylint: disable=broad-exception-caught
                # An unexpected database failure must not kill the worker.
                self.app.logger.exception("Book translation worker failed")
                worked = False
            if not worked:
                self.wake.wait(1)

    def _prepare(self, job):
        book = db.session.get(Book, job.book_id) if job.book_id else None
        if book is None:
            raise TranslationError(
                "Book was deleted. Cancel this job.", category="invalid_book"
            )
        if not book.is_supported:
            raise TranslationError(
                "The book's language parser is unavailable.", category="invalid_book"
            )
        if self.cached_job_id != job.id:
            self.cached_job_id = job.id
            self.cached_items = json.loads(job.items) if job.items is not None else None
        if self.cached_items is None:
            if not 1 <= job.start_page <= book.page_count:
                raise TranslationError(
                    "The starting page no longer exists. Cancel and add the book again.",
                    category="invalid_book",
                )
            items = collect_words(book, job.start_page)
            job.items = json.dumps(items, ensure_ascii=False)
            job.total = len(items)
            self.cached_items = items
        job.started_at = job.started_at or utcnow()
        return book.language

    def step(self):
        """Execute one word, without holding a database transaction during CLI work."""
        with self.app.app_context():
            with self.lock:
                query = db.session.query(BookTranslationJob)
                job = query.filter(
                    BookTranslationJob.status.in_(("running", "waiting"))
                ).first()
                if job is None:
                    job = (
                        query.filter_by(status="queued")
                        .order_by(BookTranslationJob.position, BookTranslationJob.id)
                        .first()
                    )
                if job is None or (job.retry_at and job.retry_at > utcnow()):
                    return False
                job_id = job.id
                self.inflight = job_id
                try:
                    language = self._prepare(job)
                    items = self.cached_items
                    if job.done >= len(items):
                        job.status = "complete"
                        job.finished_at = utcnow()
                        job.current_word = ""
                        job.current_context = ""
                        job.updated_at = utcnow()
                        db.session.commit()
                        self.inflight = None
                        return True
                    word = items[job.done]
                    job.current_word = word["text"]
                    job.current_context = word["context"]
                    job.current_page = word["page"]
                    job.status = "running"
                    job.retry_at = None
                    job.updated_at = utcnow()
                    settings = json.loads(job.settings)
                    skipped = self._skip(language, word["text"])
                    key = (
                        settings["source"],
                        settings["target"],
                        settings["model"],
                        word["text"],
                        word["context"],
                        "term",
                        (),
                        settings["effort"],
                        False,
                        (),
                        settings["cli"],
                    )
                    db.session.commit()
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    db.session.rollback()
                    self._failure(job_id, exc)
                    self.inflight = None
                    return True
                finally:
                    db.session.remove()

            result = None
            failure = None
            try:
                if not skipped:
                    result = self._translate(key, settings["language_id"])
            except Exception as exc:  # pylint: disable=broad-exception-caught
                failure = exc
            with self.lock:
                try:
                    job = db.session.get(BookTranslationJob, job_id)
                    if failure:
                        self._failure(job_id, failure)
                    else:
                        # Save even when paused/cancelled during the in-flight request.
                        language = db.session.get(Language, settings["language_id"])
                        if result is not None and language is not None:
                            store.save(
                                db.session,
                                language,
                                word["text"],
                                word["context"],
                                result,
                            )
                        job.done += 1
                        job.skipped += int(skipped)
                        job.translated += int(not skipped)
                        job.attempts = 0
                        job.error = ""
                        job.updated_at = utcnow()
                        if job.status == "running" and job.done == job.total:
                            job.status = "complete"
                            job.current_word = ""
                            job.current_context = ""
                            job.finished_at = utcnow()
                        db.session.commit()
                finally:
                    self.inflight = None
            return True

    @staticmethod
    def _skip(language, text):
        if store.find(db.session, language, text) is not None:
            return True
        return (
            db.session.query(Term.id)
            .filter(
                Term.language_id == language.id,
                Term.text_lc == Term(language, text).text_lc,
                Term.status != 0,
            )
            .first()
            is not None
        )

    def _translate(self, key, language_id):
        jobs = current_app.extensions["codex_translation_jobs"]
        lookup = jobs.submit(key, language_id=language_id, mode="bulk")
        # Future.result runs on the existing bounded translation pool. The book
        # worker waits, leaving HTTP threads free and reserving capacity for reading.
        return jobs.wait(lookup)

    @staticmethod
    def _failure(job_id, exc):
        job = db.session.get(BookTranslationJob, job_id)
        job.error = (
            str(exc)
            if isinstance(exc, TranslationError)
            else "Translation failed. Retry to continue."
        )
        errors = json.loads(job.errors)
        errors.append(
            {
                "at": utcnow().isoformat() + "Z",
                "word": job.current_word,
                "message": job.error,
            }
        )
        job.errors = json.dumps(errors[-50:], ensure_ascii=False)
        job.error_count += 1
        if not isinstance(exc, RateLimitError):
            job.attempts += 1
        job.updated_at = utcnow()
        if job.status not in ("paused", "cancelled"):
            if isinstance(exc, RateLimitError):
                job.status = "waiting"
                job.retry_at = utcnow() + timedelta(seconds=max(1, exc.retry_after))
            elif (
                isinstance(exc, TranslationError)
                and exc.category
                not in (
                    "cli_missing",
                    "authentication_or_access",
                    "unsupported_model",
                    "invalid_book",
                )
                and job.attempts < 3
            ):
                job.status = "waiting"
                job.retry_at = utcnow() + timedelta(
                    seconds=5 if job.attempts == 1 else 15
                )
            else:
                job.status = "error"
                job.retry_at = None
        db.session.commit()
