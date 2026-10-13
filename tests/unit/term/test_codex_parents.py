"""Base-form translations are independent of the child's grammatical form."""

import json
import pytest
from lute.db import db
from lute.models.term import Term as DBTerm
from lute.term.model import Repository
from lute.translation import service


@pytest.fixture
def codex_english(english):
    english.translation_provider = "codex"
    english.translation_target = "Russian"
    db.session.commit()
    return english


def test_save_form_and_parent_with_separate_translations(client, codex_english):
    language = codex_english
    response = client.post(
        f"/read/termform/{language.id}/went",
        data={
            "language_id": language.id,
            "original_text": "went",
            "text": "went",
            "translation": "пошёл",
            "status": 1,
            "parentslist": json.dumps([{"value": "go"}]),
            "suggested_parent_text": "go",
            "suggested_parent_translation": "идти",
        },
    )
    assert response.status_code == 200
    repo = Repository(db.session)
    assert repo.find(language.id, "went").translation == "пошёл"
    assert repo.find(language.id, "went").parents == ["go"]
    assert repo.find(language.id, "go").translation == "идти"


@pytest.mark.parametrize(
    "translation,expected", [("мой перевод", "мой перевод"), ("", "идти")]
)
def test_existing_parent_translation_is_preserved_or_filled(
    codex_english, translation, expected
):
    parent = DBTerm(codex_english, "go")
    parent.translation = translation
    parent.status = 3
    db.session.add(parent)
    db.session.commit()
    repo = Repository(db.session)
    child = repo.find_or_new(codex_english.id, "went")
    child.translation = "пошёл"
    child.parents = ["go"]
    child.suggested_parent_text = "go"
    child.suggested_parent_translation = "идти"
    repo.add(child)
    repo.commit()
    assert repo.find(codex_english.id, "go").translation == expected


def test_removed_parent_does_not_create_an_orphan(codex_english):
    repo = Repository(db.session)
    child = repo.find_or_new(codex_english.id, "went")
    child.translation = "пошёл"
    child.suggested_parent_text = "go"
    child.suggested_parent_translation = "идти"
    repo.add(child)
    repo.commit()
    assert repo.find(codex_english.id, "go") is None


@pytest.mark.parametrize("selected,expected", [("", "мой перевод"), ("y", "идти")])
def test_parent_option_replaces_saved_translation_only_when_selected(
    client, codex_english, selected, expected
):
    parent = DBTerm(codex_english, "go")
    parent.translation = "мой перевод"
    parent.status = 3
    db.session.add(parent)
    db.session.commit()
    response = client.post(
        f"/read/termform/{codex_english.id}/went",
        data={
            "language_id": codex_english.id,
            "original_text": "went",
            "text": "went",
            "translation": "пошёл",
            "status": 1,
            "parentslist": json.dumps([{"value": "go"}]),
            "suggested_parent_text": "go",
            "suggested_parent_translation": "идти",
            "suggested_parent_translation_selected": selected,
        },
    )
    assert response.status_code == 200
    repo = Repository(db.session)
    assert repo.find(codex_english.id, "go").translation == expected
    assert repo.find(codex_english.id, "go").status == 3
    assert repo.find(codex_english.id, "went").translation == "пошёл"


def test_cleared_dictionary_translation_does_not_copy_inflected_translation(
    codex_english,
):
    repo = Repository(db.session)
    child = repo.find_or_new(codex_english.id, "went")
    child.translation = "пошёл"
    child.parents = ["go"]
    child.suggested_parent_text = "go"
    child.suggested_parent_translation = ""
    repo.add(child)
    repo.commit()
    assert not repo.find(codex_english.id, "go").translation


CARDS = [
    {
        "text": "cats",
        "translation": "кошки",
        "lemma": "cat",
        "is_inflected": True,
        "lemma_translation": "кошка",
    },
    {
        "text": "went",
        "translation": "пошли",
        "lemma": "go",
        "is_inflected": True,
        "lemma_translation": "идти",
    },
    {
        "text": "home",
        "translation": "домой",
        "lemma": "home",
        "is_inflected": False,
        "lemma_translation": "дом",
    },
]


def make_phrase_job(client, language, monkeypatch):
    result = {
        "lemma": "",
        "is_inflected": False,
        "lemma_translation": "",
        "options": [{"translation": "Кошки пошли домой", "explanation": ""}],
        "words": CARDS,
    }
    monkeypatch.setattr(service, "translate", lambda *args: result)
    response = client.post(
        "/translation/jobs", json={"language_id": language.id, "text": "cats went home"}
    )
    job_id = response.json["job_id"]
    client.application.extensions["codex_translation_jobs"].pool.shutdown(wait=True)
    return job_id


def test_phrase_lookup_is_read_only_and_saves_only_selected_cards(
    client, codex_english, monkeypatch
):
    job_id = make_phrase_job(client, codex_english, monkeypatch)
    assert db.session.query(DBTerm).count() == 0
    assert (
        client.get(f"/translation/parent?language_id={codex_english.id}&text=cat").json[
            "exists"
        ]
        is False
    )
    assert db.session.query(DBTerm).count() == 0
    response = client.post(
        "/translation/words",
        json={"language_id": codex_english.id, "job_id": job_id, "indices": [0, 0]},
    )
    assert response.status_code == 200
    assert len(response.json["saved"]) == 1
    repo = Repository(db.session)
    assert repo.find(codex_english.id, "cats").translation == "кошки"
    assert repo.find(codex_english.id, "cats").parents == ["cat"]
    assert repo.find(codex_english.id, "cat").translation == "кошка"
    assert repo.find(codex_english.id, "went") is None
    assert repo.find(codex_english.id, "cats went home") is None


def test_word_cards_preserve_existing_user_translations_and_parents(
    client, codex_english, monkeypatch
):
    repo = Repository(db.session)
    child = repo.find_or_new(codex_english.id, "cats")
    child.translation = "мой перевод"
    child.parents = ["feline"]
    child.status = 3
    repo.add(child)
    repo.commit()
    job_id = make_phrase_job(client, codex_english, monkeypatch)
    response = client.post(
        "/translation/words",
        json={"language_id": codex_english.id, "job_id": job_id, "indices": [0]},
    )
    assert response.status_code == 200
    child = Repository(db.session).find(codex_english.id, "cats")
    assert child.translation == "мой перевод"
    assert child.parents == ["feline"]
    assert child.status == 3
    assert Repository(db.session).find(codex_english.id, "cat") is None


def test_invalid_card_selection_is_rejected_before_any_writes(
    client, codex_english, monkeypatch
):
    job_id = make_phrase_job(client, codex_english, monkeypatch)
    response = client.post(
        "/translation/words",
        json={"language_id": codex_english.id, "job_id": job_id, "indices": [0, 10]},
    )
    assert response.status_code == 400
    assert db.session.query(DBTerm).count() == 0


@pytest.mark.parametrize(
    "setting,value", [("codex_reasoning_effort", "low"), ("codex_fast_mode", True)]
)
def test_word_cards_require_current_translation_settings(
    client, codex_english, monkeypatch, setting, value
):
    job_id = make_phrase_job(client, codex_english, monkeypatch)
    setattr(codex_english, setting, value)
    db.session.commit()
    response = client.post(
        "/translation/words",
        json={"language_id": codex_english.id, "job_id": job_id, "indices": [0]},
    )
    assert response.status_code == 400
    assert b"language settings changed" in response.data
    assert db.session.query(DBTerm).count() == 0
