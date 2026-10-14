"""Save in the term card also creates the phrase cards the reader checked."""

import json
from lute.db import db
from lute.models.term import Term as DBTerm
from lute.term.model import Repository


def _save(client, language, phrases, text="looked"):
    return client.post(
        f"/read/termform/{language.id}/{text}",
        data={
            "language_id": language.id,
            "original_text": text,
            "text": text,
            "translation": "смотрел",
            "status": 1,
            "parentslist": json.dumps([{"value": "look"}]),
            "suggested_parent_text": "look",
            "suggested_parent_translation": "смотреть",
            "codex_phrases": json.dumps(phrases),
        },
    )


def test_save_creates_the_word_its_parent_and_checked_phrases(client, english):
    phrase = {"text": "looked after", "translation": "присматривал за"}
    assert _save(client, english, [phrase]).status_code == 200
    repo = Repository(db.session)
    assert repo.find(english.id, "looked").parents == ["look"]
    assert repo.find(english.id, "look").translation == "смотреть"
    saved = repo.find(english.id, "looked after")
    assert saved.translation == "присматривал за"
    assert saved.status == 1


def test_save_without_checked_phrases_creates_only_the_word(client, english):
    assert _save(client, english, []).status_code == 200
    texts = {t.text for t in db.session.query(DBTerm).all()}
    assert texts == {"looked", "look"}


def test_save_keeps_an_existing_phrase_translation(client, english):
    repo = Repository(db.session)
    existing = repo.find_or_new(english.id, "looked after")
    existing.translation = "мой перевод"
    existing.status = 3
    repo.add(existing)
    repo.commit()
    _save(client, english, [{"text": "looked after", "translation": "другое"}])
    saved = Repository(db.session).find(english.id, "looked after")
    assert saved.translation == "мой перевод"
    assert saved.status == 3


def test_invalid_phrase_selection_saves_nothing(client, english):
    response = _save(client, english, [{"text": "looked after"}])
    assert response.status_code == 200
    assert b"Invalid phrase selection" in response.data
    assert db.session.query(DBTerm).count() == 0
