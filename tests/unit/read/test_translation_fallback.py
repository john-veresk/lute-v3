"""A per-card fallback uses the configured language without switching the main mode."""

from unittest.mock import Mock
from bs4 import BeautifulSoup
import pytest
from lute.db import db
from lute.translation import service, store
from tests.unit.read.test_codex_translation import RESULT
from tests.unit.read.test_codex_store import _lookup, _result


def test_fallback_uses_configured_language_and_bypasses_personal_checks(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    english.translation_target = "French"
    db.session.commit()
    generate = Mock(return_value=RESULT)
    monkeypatch.setattr(service, "translate", generate)
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": english.id,
            "text": "cat",
            "mode": "refresh",
            "fallback": True,
        },
    )
    assert response.status_code == 202
    result = _result(client, response.json["job_id"])["result"]
    generate.assert_called_once()
    key = generate.call_args.args
    assert key[1] == "French"
    assert key[11:] == ("translation", "")
    assert "vocabulary" not in result
    assert english.translation_mode == "personal"
    assert store.find(db.session, english, "cat") is None
    assert _lookup(client, english, mode="stored", text="cat").json["job_id"] is None


def test_button_and_settings_labels_follow_the_configured_target(client, english):
    english.translation_mode = "personal"
    english.translation_target = "French"
    db.session.commit()
    card = BeautifulSoup(
        client.get(f"/term/editbytext/{english.id}/cat").data, "html.parser"
    )
    assert card.select_one("#codex-fallback").text == "French"
    settings = BeautifulSoup(
        client.get(f"/language/edit/{english.id}").data, "html.parser"
    )
    assert (
        settings.select_one('label[for="translation_target"]').text
        == "Fallback language"
    )
    english.translation_mode = "translation"
    db.session.commit()
    card = BeautifulSoup(
        client.get(f"/term/editbytext/{english.id}/cat").data, "html.parser"
    )
    assert card.select_one("#codex-fallback") is None
    settings = BeautifulSoup(
        client.get(f"/language/edit/{english.id}").data, "html.parser"
    )
    assert (
        settings.select_one('label[for="translation_target"]').text == "Translate into"
    )


@pytest.mark.parametrize("mode,fallback", [("translation", True), ("personal", "yes")])
def test_invalid_fallback_does_not_start_a_model(
    client, english, monkeypatch, mode, fallback
):
    english.translation_mode = mode
    db.session.commit()
    generate = Mock()
    monkeypatch.setattr(service, "translate", generate)
    response = client.post(
        "/translation/jobs",
        json={"language_id": english.id, "text": "cat", "fallback": fallback},
    )
    assert response.status_code == 400
    generate.assert_not_called()


def test_personal_mode_requires_a_fallback_language(client, english):
    response = client.post(
        f"/language/edit/{english.id}",
        data={
            "name": english.name,
            "parser_type": english.parser_type,
            "translation_mode": "personal",
            "translation_target": "",
        },
    )
    assert response.status_code == 200
    assert b"Please enter a translation language" in response.data


def test_fallback_word_cards_can_be_saved_in_personal_mode(
    client, english, monkeypatch
):
    english.translation_mode = "personal"
    english.translation_target = "French"
    db.session.commit()
    word = {
        "text": "cats",
        "translation": "chats",
        "lemma": "cat",
        "is_inflected": True,
        "lemma_translation": "chat",
    }
    result = {
        **RESULT,
        "words": [
            word,
            {
                "text": "sleep",
                "translation": "dormir",
                "lemma": "sleep",
                "is_inflected": False,
                "lemma_translation": "dormir",
            },
        ],
    }
    monkeypatch.setattr(service, "translate", lambda *args: result)
    response = client.post(
        "/translation/jobs",
        json={
            "language_id": english.id,
            "text": "cats sleep",
            "mode": "refresh",
            "fallback": True,
        },
    )
    job_id = response.json["job_id"]
    _result(client, job_id)
    saved = client.post(
        "/translation/words",
        json={"language_id": english.id, "job_id": job_id, "indices": [0]},
    )
    assert saved.status_code == 200
    assert saved.json["saved"][0]["translation"] == "chats"
    assert english.translation_mode == "personal"
