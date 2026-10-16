"""Book-specific usage notes, separate from reusable dictionary explanations."""

import hashlib
import json
import re
from datetime import datetime
from lute.db import db
from lute.models.book import Book, Text


class ContextNote(db.Model):  # pylint: disable=too-few-public-methods
    """One saved explanation for an occurrence of a term in a book."""

    __tablename__ = "translationcontexts"

    id = db.Column(db.Integer, primary_key=True)
    language_id = db.Column(db.Integer, db.ForeignKey("languages.LgID"), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey("books.BkID"), nullable=False)
    text_lc = db.Column(db.Text, nullable=False)
    profile = db.Column(db.Text, nullable=False)
    context_key = db.Column(db.String(64), nullable=False)
    page = db.Column(db.Integer, nullable=False)
    sentence_index = db.Column(db.Integer, nullable=False)
    sentence = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.Text, nullable=False)
    note = db.Column(db.Text, nullable=False)
    updated = db.Column(db.DateTime, nullable=False)


def sentences(language, text):
    """Use the language parser's sentence boundaries, including paragraphs."""
    parts = []
    for token in language.get_parsed_tokens(text):
        parts.append(token.token)
        if token.is_end_of_sentence:
            sentence = "".join(parts).replace("\u200b", "").replace("¶", "\n").strip()
            if sentence:
                yield sentence
            parts = []
    sentence = "".join(parts).replace("\u200b", "").replace("¶", "\n").strip()
    if sentence:
        yield sentence


def windows(language, pages):
    """Selected sentence plus one neighbor on either side, across page boundaries."""
    entries = [
        (page.order, position, text)
        for page in pages
        for position, text in enumerate(sentences(language, page.text))
    ]
    for index, (page, position, sentence) in enumerate(entries):
        parts = []
        if index:
            parts.append(entries[index - 1][2][-4000:])
        parts.append(sentence[:4000])
        if index + 1 < len(entries):
            parts.append(entries[index + 1][2][:4000])
        yield {
            "page": page,
            "sentence_index": position,
            "sentence": sentence,
            "excerpt": "\n".join(parts),
        }


def _normalized(text):
    return re.sub(r"\s+", " ", text.replace("\u200b", "").replace("¶", " ")).strip()


def prepare(session, language, book_id, page, sentence, sentence_index=None):
    """Validate a reader's book/page and build its local context on the server."""
    if type(book_id) is not int or type(page) is not int or page < 1:
        raise ValueError("Invalid book or page")
    if sentence_index is not None and (
        type(sentence_index) is not int or sentence_index < 0
    ):
        raise ValueError("Invalid sentence position")
    book = session.get(Book, book_id)
    if book is None or book.language_id != language.id:
        raise ValueError("Invalid book or language")
    pages = (
        session.query(Text)
        .filter(Text.bk_id == book_id, Text.order.between(max(1, page - 1), page + 1))
        .order_by(Text.order)
        .all()
    )
    if not any(item.order == page for item in pages):
        raise ValueError("Invalid book page")
    for entry in windows(language, pages):
        if (
            entry["page"] == page
            and _normalized(entry["sentence"]) == _normalized(sentence)
            and (sentence_index is None or entry["sentence_index"] == sentence_index)
        ):
            return {"book_id": book_id, **entry}
    return None


def profile_key(profile):
    """Usage notes survive changes to the reader's known vocabulary."""
    return "personal" if profile.startswith("personal:") else profile


def _context_key(info):
    return hashlib.sha256(
        json.dumps(
            [info["page"], info["sentence_index"], info["sentence"], info["excerpt"]],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _query(session, language_id, text_lc, profile, info):
    return session.query(ContextNote).filter_by(
        language_id=language_id,
        text_lc=text_lc,
        profile=profile_key(profile),
        book_id=info["book_id"],
        context_key=_context_key(info),
    )


def save(session, language_id, text_lc, profile, info, note):
    """Join the dictionary result's transaction; never commit independently."""
    if info is None or note is None:
        return
    if session.get(Book, info["book_id"]) is None:
        return
    row = _query(session, language_id, text_lc, profile, info).one_or_none()
    if row is None:
        row = ContextNote(
            language_id=language_id,
            text_lc=text_lc,
            profile=profile_key(profile),
            book_id=info["book_id"],
            context_key=_context_key(info),
        )
    row.page = info["page"]
    row.sentence_index = info["sentence_index"]
    row.sentence = info["sentence"]
    row.excerpt = info["excerpt"]
    row.note = note
    row.updated = datetime.now()
    session.add(row)


def find(session, language_id, text_lc, profile, info):
    """Only the matching book occurrence supplies a usage note."""
    if info is None:
        return None
    row = _query(session, language_id, text_lc, profile, info).one_or_none()
    return row.note if row and row.note else None


def for_review(session, language, text_lc, profile, book_id):
    """Review reads the most recently generated occurrence in this book."""
    rows = (
        session.query(ContextNote)
        .filter_by(
            language_id=language.id,
            text_lc=text_lc,
            profile=profile_key(profile),
            book_id=book_id,
        )
        .filter(ContextNote.note != "")
        .order_by(ContextNote.updated.desc(), ContextNote.id.desc())
    )
    for row in rows:
        try:
            info = prepare(
                session, language, book_id, row.page, row.sentence, row.sentence_index
            )
        except ValueError:
            continue
        if info is not None and _context_key(info) == row.context_key:
            return {
                "sentence": row.sentence,
                "excerpt": row.excerpt,
                "note": row.note,
                "page": row.page,
            }
    return None


def dictionary_result(result):
    """Keep occurrence-specific notes out of the shared dictionary result."""
    clean = {
        key: value
        for key, value in result.items()
        if key not in ("context_note", "context_excerpt")
    }
    if clean.get("fallback"):
        clean["fallback"] = dictionary_result(clean["fallback"])
    return clean
