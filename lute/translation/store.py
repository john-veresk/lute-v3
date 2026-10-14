"""The latest Codex result for each term, reused instead of a new request."""

import json
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from lute.db import db


class StoredTranslation(db.Model):  # pylint: disable=too-few-public-methods
    """A saved Codex result."""

    __tablename__ = "codextranslations"

    id = db.Column("CtID", db.Integer, primary_key=True)
    language_id = db.Column(
        "CtLgID", db.Integer, db.ForeignKey("languages.LgID"), nullable=False
    )
    text_lc = db.Column("CtTextLC", db.Text, nullable=False)
    context = db.Column("CtContext", db.Text, nullable=False, default="")
    result = db.Column("CtResult", db.Text, nullable=False)
    updated = db.Column("CtUpdated", db.DateTime, nullable=False)


def text_key(language, text):
    "Terms match regardless of case and the zero-width spaces between tokens."
    return language.get_lowercase(text.replace("\u200b", "").strip())


def _find_row(session, language, text):
    return (
        session.query(StoredTranslation)
        .filter_by(language_id=language.id, text_lc=text_key(language, text))
        .one_or_none()
    )


def find(session, language, text):
    "The saved result for a term, or None."
    row = _find_row(session, language, text)
    return json.loads(row.result) if row else None


def save(session, language, text, context, result):
    "Keep only the latest result for each term."
    row = _find_row(session, language, text) or StoredTranslation(
        language_id=language.id, text_lc=text_key(language, text)
    )
    row.context = context
    row.result = json.dumps(result, ensure_ascii=False)
    row.updated = datetime.now()
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent lookup just saved this term.
        session.rollback()
