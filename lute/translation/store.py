"""The latest Codex result for each term, reused instead of a new request."""

import json
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from lute.db import db
from lute.translation.profile import profile_for


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
    profile = db.Column("CtProfile", db.Text, nullable=False, default="")


def text_key(language, text):
    "Terms match regardless of case and the zero-width spaces between tokens."
    return language.get_lowercase(text.replace("\u200b", "").strip())


def _find_row(session, language, text):
    return (
        session.query(StoredTranslation)
        .filter_by(language_id=language.id, text_lc=text_key(language, text))
        .one_or_none()
    )


def find(session, language, text, profile=None, context=None):
    "The saved result for a term, or None."
    row = _find_row(session, language, text)
    if row is None or row.profile != (
        profile if profile is not None else profile_for(session, language)
    ):
        return None
    if (
        row.profile.startswith("personal:")
        and context is not None
        and row.context != context
    ):
        return None
    return json.loads(row.result)


def save(session, language, text, context, result, profile=None):
    "Keep only the latest result for each term."
    row = _find_row(session, language, text) or StoredTranslation(
        language_id=language.id, text_lc=text_key(language, text)
    )
    row.context = context
    row.result = json.dumps(result, ensure_ascii=False)
    row.updated = datetime.now()
    row.profile = profile if profile is not None else profile_for(session, language)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent lookup just saved this term.
        session.rollback()
