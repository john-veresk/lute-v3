"""Codex is a complete replacement for website dictionaries."""

from lute.db import db
from lute.models.language import Language


def test_save_codex_without_dictionaries(client, app_context):
    response = client.post(
        "/language/new",
        data={
            "name": "Codex Finnish",
            "parser_type": "spacedel",
            "translation_provider": "codex",
            "translation_target": "Russian",
            "codex_model": "custom-model",
        },
    )
    assert response.status_code == 302
    language = db.session.query(Language).filter_by(name="Codex Finnish").one()
    assert language.dictionaries == []
    assert language.codex_model == "custom-model"
    assert language.sentence_dict_uris[0]["dicttype"] == "codex"
    assert Language.from_dict(language.to_dict()).to_dict() == language.to_dict()


def test_websites_still_require_dictionaries(client):
    response = client.post(
        "/language/new",
        data={
            "name": "No dictionaries",
            "parser_type": "spacedel",
            "translation_provider": "dictionaries",
        },
    )
    assert response.status_code == 200
    assert b"Please add an active Terms dictionary" in response.data


def test_codex_requires_target_language(client):
    response = client.post(
        "/language/new",
        data={
            "name": "No target",
            "parser_type": "spacedel",
            "translation_provider": "codex",
            "translation_target": "",
        },
    )
    assert b"Please enter a translation language" in response.data


def test_switching_provider_preserves_website_settings(client, spanish):
    before = spanish.to_dict()["dictionaries"]
    response = client.post(
        f"/language/edit/{spanish.id}",
        data={
            "name": spanish.name,
            "parser_type": spanish.parser_type,
            "translation_provider": "codex",
            "translation_target": "Russian",
        },
    )
    assert response.status_code == 302
    db.session.refresh(spanish)
    assert spanish.to_dict()["dictionaries"] == before
    assert spanish.active_dict_uris("terms") == [
        {"url": "/translation/panel", "dicttype": "codex"}
    ]
