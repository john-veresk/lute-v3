"""Codex is the only translation source; languages have no website dictionaries."""

import json
import pytest
from lute.db import db
from lute.models.language import Language


def test_save_codex_settings(client, app_context):
    response = client.post(
        "/language/new",
        data={
            "name": "Codex Finnish",
            "parser_type": "spacedel",
            "translation_target": "Russian",
            "codex_model": "custom-model",
            "codex_reasoning_effort": "low",
            "codex_fast_mode": "y",
            "codex_show_timer": "y",
        },
    )
    assert response.status_code == 302
    language = db.session.query(Language).filter_by(name="Codex Finnish").one()
    assert language.dictionaries == []
    assert language.codex_model == "custom-model"
    assert language.codex_reasoning_effort == "low"
    assert language.codex_fast_mode is True
    assert language.codex_show_timer is True
    assert Language.from_dict(language.to_dict()).to_dict() == language.to_dict()
    page = client.get(f"/language/edit/{language.id}").data
    assert b'<option selected value="low">low</option>' in page
    assert b'checked id="codex_fast_mode"' in page
    assert b'checked id="codex_show_timer"' in page
    assert (
        b'id="codex-timer"'
        in client.get(f"/translation/panel?language_id={language.id}").data
    )

    response = client.post(
        f"/language/edit/{language.id}",
        data={
            "name": language.name,
            "parser_type": "spacedel",
            "translation_target": "Russian",
            "codex_model": "custom-model",
            "codex_reasoning_effort": "",
        },
    )
    assert response.status_code == 302
    db.session.refresh(language)
    assert language.codex_reasoning_effort == ""
    assert language.codex_fast_mode is False
    assert language.codex_show_timer is False
    assert (
        b'id="codex-timer"'
        not in client.get(f"/translation/panel?language_id={language.id}").data
    )
    assert Language.from_dict(language.to_dict()).codex_show_timer is False


@pytest.mark.parametrize("effort", ["ultra", 'low";invalid=true'])
def test_unsupported_effort_is_rejected(client, monkeypatch, tmp_path, effort):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "test-luna",
                        "supported_reasoning_levels": [{"effort": "low"}],
                    }
                ]
            }
        )
    )
    response = client.post(
        "/language/new",
        data={
            "name": "Invalid effort",
            "parser_type": "spacedel",
            "translation_target": "Russian",
            "codex_model": "test-luna",
            "codex_reasoning_effort": effort,
        },
    )
    assert response.status_code == 200
    assert (
        b"This model does not support" in response.data
        or b"Not a valid choice" in response.data
    )


def test_existing_languages_default_to_cli_effort_and_standard_speed(spanish):
    assert spanish.codex_reasoning_effort == ""
    assert spanish.codex_fast_mode is False
    assert spanish.codex_show_timer is True


def test_new_language_timer_is_checked_by_default(client):
    assert b'checked id="codex_show_timer"' in client.get("/language/new").data


def test_settings_have_no_dictionary_controls(client, spanish):
    page = client.get(f"/language/edit/{spanish.id}").data
    assert b"translation_provider" not in page
    assert b"dictionary_entities" not in page


def test_codex_requires_target_language(client):
    response = client.post(
        "/language/new",
        data={
            "name": "No target",
            "parser_type": "spacedel",
            "translation_target": "",
        },
    )
    assert b"Please enter a translation language" in response.data


def test_saving_settings_keeps_stored_dictionary_data(client, spanish):
    before = spanish.to_dict()["dictionaries"]
    response = client.post(
        f"/language/edit/{spanish.id}",
        data={
            "name": spanish.name,
            "parser_type": spanish.parser_type,
            "translation_target": "Russian",
        },
    )
    assert response.status_code == 302
    db.session.refresh(spanish)
    assert spanish.to_dict()["dictionaries"] == before
