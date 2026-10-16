"""The latest Codex result for each term, reused instead of a new request."""

import json
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from lute.db import db
from lute.translation import contexts
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


def _find_row(session, language, text, profile):
    return (
        session.query(StoredTranslation)
        .filter_by(
            language_id=language.id, text_lc=text_key(language, text), profile=profile
        )
        .one_or_none()
    )


def find(session, language, text, profile=None, context_info=None):
    "The saved result for a term and output profile, shared across books."
    profile = profile if profile is not None else profile_for(session, language)
    row = _find_row(session, language, text, profile)
    if row is None:
        return None
    result = json.loads(row.result)
    note = contexts.find(
        session, language.id, text_key(language, text), profile, context_info
    )
    if note:
        result["context_note"] = note
        result["context_excerpt"] = context_info["excerpt"]
    return result


def save(session, language, text, context, result, profile=None, context_info=None):
    "Keep the latest result per term and output profile, for the selected target language."
    profile = profile if profile is not None else profile_for(session, language)
    for attempt in range(2):
        try:
            with session.no_autoflush:
                _save_row(
                    session, language, text, context, result, profile, context_info
                )
            session.commit()
            return
        except IntegrityError:
            # Another lookup may have inserted the same translation. Reload and retry.
            session.rollback()
            if attempt:
                raise


def _save_row(session, language, text, context, result, profile, context_info):
    row = _find_row(session, language, text, profile) or StoredTranslation(
        language_id=language.id, text_lc=text_key(language, text), profile=profile
    )
    row.context = context
    row.result = json.dumps(contexts.dictionary_result(result), ensure_ascii=False)
    row.updated = datetime.now()
    session.add(row)
    contexts.save(
        session,
        language.id,
        text_key(language, text),
        profile,
        context_info,
        result.get("context_note"),
    )
