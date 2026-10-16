"""The latest Codex result for each term, reused instead of a new request."""

import json
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from lute.db import db
from lute.translation.profile import cache_profile, profile_for


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


def _find_row(session, language, text, profile):
    return (
        session.query(StoredTranslation)
        .filter_by(
            language_id=language.id, text_lc=text_key(language, text), profile=profile
        )
        .one_or_none()
    )


def find(session, language, text, profile=None):
    "The saved result for a term and output profile, shared across books."
    profile = profile if profile is not None else profile_for(session, language)
    row = _find_row(session, language, text, profile)
    if row is None:
        return None
    return json.loads(row.result)


def save(session, language, text, context, result, profile=None):
    "Keep the latest result per term and output profile, including its fallback."
    profile = profile if profile is not None else profile_for(session, language)
    for attempt in range(2):
        try:
            with session.no_autoflush:
                _save_row(session, language, text, context, result, profile)
                if result.get("fallback") and result.get("fallback_language"):
                    _save_row(
                        session,
                        language,
                        text,
                        context,
                        result["fallback"],
                        cache_profile(language.name, result["fallback_language"]),
                    )
            session.commit()
            return
        except IntegrityError:
            # Another lookup may have inserted only one of the two profiles.
            # Reload both rows and retry so neither variant is silently lost.
            session.rollback()
            if attempt:
                raise


def _save_row(session, language, text, context, result, profile):
    row = _find_row(session, language, text, profile) or StoredTranslation(
        language_id=language.id, text_lc=text_key(language, text), profile=profile
    )
    row.context = context
    row.result = json.dumps(result, ensure_ascii=False)
    row.updated = datetime.now()
    session.add(row)
