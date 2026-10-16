"""Codex is the only translation source; languages have no website dictionaries."""

import json
import pytest
from bs4 import BeautifulSoup
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
    form = BeautifulSoup(page, "html.parser")
    for row in ("codex-effort-row", "codex-fast-row"):
        assert not form.select_one(f"#{row}").has_attr("hidden")
    assert not form.select_one("#codex_reasoning_effort").has_attr("disabled")
    assert not form.select_one("#codex_fast_mode").has_attr("disabled")
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
    assert spanish.translation_cli == "codex"


def test_language_can_switch_to_cursor_agent(client, spanish):
    page = client.get(f"/language/edit/{spanish.id}").data
    assert b'id="translation_cli"' in page
    assert b'value="codex"' in page
    assert b'value="cursor"' in page
    assert b"Cursor Agent" in page
    response = client.post(
        f"/language/edit/{spanish.id}",
        data={
            "name": spanish.name,
            "parser_type": spanish.parser_type,
            "translation_target": "Russian",
            "translation_cli": "cursor",
            "codex_model": "composer-2.5",
            "codex_reasoning_effort": "low",
        },
    )
    assert response.status_code == 302
    db.session.refresh(spanish)
    assert spanish.translation_cli == "cursor"
    assert spanish.codex_model == "composer-2.5"
    assert Language.from_dict(spanish.to_dict()).translation_cli == "cursor"
    saved = client.get(f"/language/edit/{spanish.id}").data
    assert b'<option selected value="cursor">Cursor Agent</option>' in saved
    card = client.get(f"/term/editbytext/{spanish.id}/gato").data
    assert b"Translate again with Cursor" in card
    assert b">composer-2.5<" in card


def test_unknown_translation_cli_is_rejected(client):
    response = client.post(
        "/language/new",
        data={
            "name": "Bad CLI",
            "parser_type": "spacedel",
            "translation_target": "Russian",
            "translation_cli": "grok",
        },
    )
    assert response.status_code == 200
    assert b"Not a valid choice" in response.data


@pytest.mark.parametrize("submitted_options", [{}, {"codex_reasoning_effort": "max"}])
def test_cursor_settings_hide_and_preserve_codex_options(
    client, spanish, submitted_options
):
    spanish.codex_reasoning_effort = "low"
    spanish.codex_fast_mode = True
    db.session.commit()
    response = client.post(
        f"/language/edit/{spanish.id}",
        data={
            "name": spanish.name,
            "parser_type": spanish.parser_type,
            "translation_target": "Russian",
            "translation_cli": "cursor",
            "codex_model": "cursor-grok-4.6-medium",
            **submitted_options,
        },
    )
    assert response.status_code == 302
    db.session.refresh(spanish)
    assert spanish.codex_reasoning_effort == "low"
    assert spanish.codex_fast_mode is True
    assert spanish.translation_reasoning_effort == ""
    assert spanish.translation_fast_mode is False
    page = BeautifulSoup(client.get(f"/language/edit/{spanish.id}").data, "html.parser")
    for row in ("codex-effort-row", "codex-fast-row"):
        assert page.select_one(f"#{row}").has_attr("hidden")
    assert page.select_one("#codex_reasoning_effort").has_attr("disabled")
    assert page.select_one("#codex_fast_mode").has_attr("disabled")
    assert page.select_one("#codex_model")["value"] == "cursor-grok-4.6-medium"


def test_cursor_agent_does_not_apply_codex_effort_metadata(
    client, app_context, monkeypatch, tmp_path
):
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
            "name": "Cursor effort",
            "parser_type": "spacedel",
            "translation_target": "Russian",
            "translation_cli": "cursor",
            "codex_model": "test-luna",
            "codex_reasoning_effort": "high",
        },
    )
    assert response.status_code == 302
    language = db.session.query(Language).filter_by(name="Cursor effort").one()
    assert language.translation_cli == "cursor"
    assert language.codex_reasoning_effort == ""
    assert language.codex_fast_mode is False


def test_new_language_timer_is_checked_by_default(client):
    assert b'checked id="codex_show_timer"' in client.get("/language/new").data


def test_legacy_reader_pretranslation_setting_is_not_exposed(client, spanish):
    assert spanish.codex_pretranslate is False
    assert b'id="codex_pretranslate"' not in client.get("/language/new").data
    response = client.post(
        f"/language/edit/{spanish.id}",
        data={
            "name": spanish.name,
            "parser_type": spanish.parser_type,
            "translation_target": "Russian",
            "codex_pretranslate": "y",
        },
    )
    assert response.status_code == 302
    db.session.refresh(spanish)
    assert spanish.codex_pretranslate is False
    assert Language.from_dict(spanish.to_dict()).codex_pretranslate is False


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
