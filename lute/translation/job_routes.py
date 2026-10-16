"""Management UI and commands for server-side book translation jobs."""

import json
from sqlalchemy.orm import selectinload
from flask import Blueprint, current_app, jsonify, render_template, request
from lute.db import db
from lute.models.book import Book, Text
from lute.translation.bulk import ACTIVE, BookTranslationJob, language_settings, utcnow
from lute.translation.settings import updated_settings
from lute.translation.service import REASONING_EFFORTS

bp = Blueprint("jobs", __name__, url_prefix="/jobs")


def _page_info(books):
    """Read page counts and current page numbers without loading book contents."""
    ids = [book.id for book in books]
    counts = dict(
        db.session.query(Text.bk_id, db.func.count(Text.id))
        .filter(Text.bk_id.in_(ids))
        .group_by(Text.bk_id)
        .all()
    )
    pages = dict(
        db.session.query(Text.id, Text.order)
        .filter(
            Text.id.in_([book.current_tx_id for book in books if book.current_tx_id])
        )
        .all()
    )
    return counts, pages


def _worker():
    return current_app.extensions["book_translation_worker"]


@bp.route("/<int:job_id>/settings", methods=["GET", "PATCH"])
def settings(job_id):
    """Change an existing job's CLI/model at the next word boundary."""
    worker = _worker()
    with worker.lock:
        job = db.session.get(BookTranslationJob, job_id)
        if job is None:
            return jsonify(error="Job not found"), 404
        if request.method == "PATCH":
            if job.status not in ACTIVE:
                return jsonify(error="Finished jobs cannot be changed"), 409
            try:
                updated = updated_settings(
                    json.loads(job.settings), request.get_json(silent=True)
                )
            except ValueError as exc:
                return jsonify(error=str(exc)), 400
            job.settings = json.dumps(updated, ensure_ascii=False)
            job.updated_at = utcnow()
            db.session.commit()
        return jsonify(
            job=job.payload(), applies_after_current_word=worker.inflight == job_id
        )


@bp.get("")
def index():
    return render_template("jobs/index.html", reasoning_efforts=REASONING_EFFORTS)


@bp.get("/state")
def state():
    """Polling is read-only: work continues without any connected clients."""
    with _worker().lock:
        jobs = (
            db.session.query(BookTranslationJob, BookTranslationJob.items.isnot(None))
            .order_by(BookTranslationJob.position, BookTranslationJob.id)
            .all()
        )
        books = (
            db.session.query(Book)
            .options(selectinload(Book.book_tags), selectinload(Book.language))
            .order_by(Book.title, Book.id)
            .all()
        )
        counts, pages = _page_info(books)
        return jsonify(
            jobs=[job.payload(prepared) for job, prepared in jobs],
            books=[
                {
                    "id": book.id,
                    "title": book.title,
                    "language": book.language.name,
                    "archived": book.archived,
                    "supported": book.is_supported,
                    "page_count": counts.get(book.id, 0),
                    "start_page": pages.get(book.current_tx_id, 1),
                    "tags": sorted(tag.text for tag in book.book_tags),
                }
                for book in books
            ],
        )


@bp.post("")
def enqueue():
    """Atomically enqueue selected books once, preserving the selection order."""
    data = request.get_json(silent=True)
    ids = data.get("book_ids") if isinstance(data, dict) else None
    if (
        not isinstance(ids, list)
        or not ids
        or len(ids) > 500
        or any(type(i) is not int for i in ids)
    ):
        return jsonify(error="Select between 1 and 500 books."), 400
    start_pages = data.get("start_pages", {})
    if not isinstance(start_pages, dict):
        return jsonify(error="Invalid starting pages."), 400
    ids = list(dict.fromkeys(ids))
    with _worker().lock:
        books = {
            book.id: book for book in db.session.query(Book).filter(Book.id.in_(ids))
        }
        if len(books) != len(ids):
            return jsonify(error="One of the selected books no longer exists."), 404
        if any(not book.is_supported for book in books.values()):
            return (
                jsonify(error="One of the selected language parsers is unavailable."),
                400,
            )
        counts, pages = _page_info(list(books.values()))
        starts = {}
        for book_id, book in books.items():
            default = pages.get(book.current_tx_id, 1)
            start = start_pages.get(str(book_id), default)
            if type(start) is not int or not 1 <= start <= counts.get(book.id, 0):
                return (
                    jsonify(
                        error=f"Starting page for {book.title} must be between 1 and {counts.get(book.id, 0)}."
                    ),
                    400,
                )
            starts[book_id] = start
        existing = {
            book_id
            for (book_id,) in db.session.query(BookTranslationJob.book_id).filter(
                BookTranslationJob.status.in_(ACTIVE)
            )
        }
        position = (
            db.session.query(db.func.max(BookTranslationJob.position)).scalar() or 0
        )
        added = []
        for book_id in ids:
            if book_id in existing:
                continue
            position += 1
            book = books[book_id]
            job = BookTranslationJob(
                book_id=book.id,
                title=book.title,
                position=position,
                start_page=starts[book.id],
                settings=json.dumps(
                    language_settings(book.language), ensure_ascii=False
                ),
            )
            db.session.add(job)
            added.append(job)
        db.session.commit()
        result = [job.payload() for job in added]
    _worker().notify()
    return jsonify(jobs=result), 201


@bp.post("/<int:job_id>/<action>")
def control(job_id, action):
    """Pause/resume/cancel at word boundaries, or move a waiting book."""
    worker = _worker()
    with worker.lock:
        job = db.session.get(BookTranslationJob, job_id)
        if job is None:
            return jsonify(error="Job not found."), 404
        if action == "pause" and job.status in ("queued", "running", "waiting"):
            job.status = "paused"
            job.retry_at = None
        elif action == "resume" and job.status in ("paused", "error"):
            # A paused in-flight word must finish before it can be retried.
            if worker.inflight == job_id:
                return (
                    jsonify(
                        error="The current word is still finishing. Resume shortly."
                    ),
                    409,
                )
            job.status = "queued"
            job.error = ""
            job.attempts = 0
            job.retry_at = None
        elif action == "cancel" and job.status in ACTIVE:
            job.status = "cancelled"
            job.retry_at = None
            job.finished_at = utcnow()
        elif action in ("up", "down") and job.status in ("queued", "paused", "error"):
            waiting = (
                db.session.query(BookTranslationJob)
                .filter(BookTranslationJob.status.in_(("queued", "paused", "error")))
                .order_by(BookTranslationJob.position, BookTranslationJob.id)
                .all()
            )
            index = waiting.index(job)
            adjacent = index + (-1 if action == "up" else 1)
            if 0 <= adjacent < len(waiting):
                other = waiting[adjacent]
                job.position, other.position = other.position, job.position
                other.updated_at = utcnow()
        else:
            return (
                jsonify(
                    error="This action is unavailable for the job's current status."
                ),
                409,
            )
        job.updated_at = utcnow()
        db.session.commit()
        result = job.payload()
    worker.notify()
    return jsonify(result)
