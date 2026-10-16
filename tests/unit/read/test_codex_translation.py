"""Validate the CLI boundary, background jobs, and HTTP translation API."""

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from bs4 import BeautifulSoup
import pytest
from lute.db import db
from lute.models.term import Term as DBTerm
from lute.translation import service

RESULT = {
    "lemma": "kissa",
    "is_inflected": False,
    "lemma_translation": "кошка",
    "lemma_options": [],
    "words": [],
    "phrases": [],
    "options": [
        {"translation": "кошка", "explanation": "В этом предложении"},
        {"translation": "кот", "explanation": "Самец"},
    ],
}


@pytest.mark.parametrize("bundled_available", [False, True])
def test_codex_prefers_bundled_cli_and_falls_back_to_path(
    monkeypatch, tmp_path, bundled_available
):
    bundled = tmp_path / "ChatGPT.app" / "codex"
    bundled.parent.mkdir()
    bundled.write_text("#!/bin/sh\n")
    bundled.chmod(0o755 if bundled_available else 0o644)
    path_cli = tmp_path / "codex"
    path_cli.write_text("#!/bin/sh\n")
    path_cli.chmod(0o755)
    monkeypatch.delenv("LUTE_CODEX_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(service, "_bundled_codex_paths", lambda: [bundled])
    assert service._executable("codex") == str(
        bundled if bundled_available else path_cli
    )


@pytest.mark.parametrize("cli", ["codex", "cursor"])
def test_explicit_cli_override_takes_precedence(monkeypatch, cli):
    name = f"/custom/{cli}"
    env = "LUTE_CODEX_CLI" if cli == "codex" else "LUTE_CURSOR_AGENT_CLI"
    monkeypatch.setenv(env, name)

    def which(value):
        assert value == name
        return name

    monkeypatch.setattr(service.shutil, "which", which)
    assert service._executable(cli) == name


def test_missing_explicit_codex_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("LUTE_CODEX_CLI", "/missing/codex")
    with pytest.raises(service.TranslationError) as caught:
        service._executable("codex")
    assert caught.value.category == "cli_missing"


def test_bundled_cli_discovery_is_mac_only(monkeypatch, tmp_path):
    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    assert (
        tmp_path / "Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
        in (service._bundled_codex_paths())
    )
    monkeypatch.setattr(service.sys, "platform", "linux")
    assert service._bundled_codex_paths() == []


@pytest.mark.parametrize(
    "status,translation",
    [(0, ""), (1, ""), (99, ""), (1, "мой перевод"), (99, "мой перевод"), (1, " \n ")],
)
@pytest.mark.parametrize("route", ["read_id", "read_text", "term_id", "term_text"])
def test_term_form_preserves_translation_for_codex_autostart(
    client, spanish, status, translation, route
):
    term = DBTerm(spanish, "gato")
    term.status = status
    term.translation = translation
    db.session.add(term)
    db.session.commit()
    url = {
        "read_id": f"/read/edit_term/{term.id}",
        "read_text": f"/read/termform/{spanish.id}/gato",
        "term_id": f"/term/edit/{term.id}",
        "term_text": f"/term/editbytext/{spanish.id}/gato",
    }[route]
    response = client.get(url)
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert page.select_one("#translation").get_text().strip() == translation.strip()
    assert db.session.get(DBTerm, term.id).status == status


@pytest.mark.parametrize("route", ["read/termform", "term/editbytext"])
def test_new_term_form_keeps_automatic_translation(client, spanish, route):
    response = client.get(f"/{route}/{spanish.id}/gato")
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert page.select_one("#translation").get_text().strip() == ""


def test_cursor_effort_options_follow_the_model_family():
    options = service.cursor_model_efforts(
        [
            "claude-opus-4-8",
            "claude-opus-4-8-low",
            "claude-opus-4-8-high",
            "claude-opus-4-8-low-fast",
            "claude-opus-4-8-high-fast",
            "gpt-5.5-extra-high",
            "composer-2.5",
        ]
    )
    high = options["claude-opus-4-8-high"]
    assert high["effort"] == "high"
    assert high["efforts"] == ["low", "high"]
    assert high["variants"][""] == "claude-opus-4-8"
    assert high["variants"]["low"] == "claude-opus-4-8-low"
    assert options["claude-opus-4-8-high-fast"]["variants"]["low"] == (
        "claude-opus-4-8-low-fast"
    )
    assert options["gpt-5.5-extra-high"]["effort"] == "xhigh"
    assert options["composer-2.5"]["efforts"] == []
    assert service.cursor_model_argument("claude-opus-4-8-high", "high", False) == (
        "claude-opus-4-8-high"
    )


@pytest.mark.parametrize(
    "model,effort,fast_mode,expected",
    [
        ("cursor-grok-4.6-medium", "medium", True, "cursor-grok-4.6-medium-fast"),
        ("cursor-grok-4.6-medium", "high", False, "cursor-grok-4.6-high"),
        ("cursor-grok-4.6-medium", "high", True, "cursor-grok-4.6-high-fast"),
        ("cursor-grok-4.6-medium-fast", "high", False, "cursor-grok-4.6-high-fast"),
        ("composer-2.5", "", True, "composer-2.5-fast"),
        ("gemini-3.7-flash-high", "high", True, "gemini-3.7-flash-high"),
        ("custom-model[effort=low]", "high", True, "custom-model[effort=low]"),
    ],
)
def test_cursor_known_aliases_use_advertised_variants(
    monkeypatch, model, effort, fast_mode, expected
):
    monkeypatch.setattr(
        service,
        "available_cursor_models",
        lambda: [
            "cursor-grok-4.6-medium",
            "cursor-grok-4.6-medium-fast",
            "cursor-grok-4.6-high",
            "cursor-grok-4.6-high-fast",
            "composer-2.5",
            "composer-2.5-fast",
            "gemini-3.7-flash-high",
        ],
    )
    assert service.cursor_model_argument(model, effort, fast_mode) == expected


def test_cursor_unsupported_model_error_is_actionable_and_does_not_leak_output():
    error = service._cli_error(
        "Cannot use this model: PRIVATE MODEL. Available models: PRIVATE LIST",
        1,
        "cursor",
    )
    assert error.category == "unsupported_model"
    assert error.exit_code == 1
    assert "language settings" in str(error)
    assert "PRIVATE" not in str(error)
    assert error.detail == ""


def test_cursor_model_list_ignores_labels_and_color(monkeypatch):
    colored = (
        "\x1b[2mAvailable models\x1b[22m\n\n"
        "\x1b[32mcomposer-2.5\x1b[39m \x1b[2m- Composer 2.5\x1b[22m \x1b[2m(default)\x1b[22m\n"
        "\x1b[36mgpt-5.2\x1b[39m \x1b[2m- GPT-5.2\x1b[22m\n"
        "not a model line\n"
        "Tip: use --model <id>\n"
    )
    assert service.parse_cursor_models(colored) == ["composer-2.5", "gpt-5.2"]
    assert service.available_cursor_models() == []


@pytest.mark.parametrize(
    "model,effort,fast_mode,expected",
    [
        ("composer-2.5", "", False, "composer-2.5"),
        ("composer-2.5", "low", False, "composer-2.5[effort=low]"),
        ("composer-2.5", "high", True, "composer-2.5[effort=high,fast=true]"),
        ("composer-2.5", "", True, "composer-2.5[fast=true]"),
        ("cursor-grok-4.6-medium", "medium", True, "cursor-grok-4.6-medium-fast"),
    ],
)
@pytest.mark.parametrize("translation_mode", ["translation", "personal"])
def test_cursor_agent_prints_json_from_ask_mode(
    monkeypatch, model, effort, fast_mode, expected, translation_mode
):
    def which(name):
        assert name == "cursor-agent"
        return "/usr/bin/cursor-agent"

    monkeypatch.setattr(service.shutil, "which", which)
    monkeypatch.setattr(
        service,
        "available_cursor_models",
        lambda: ["cursor-grok-4.6-medium", "cursor-grok-4.6-medium-fast"],
    )

    def run(command, **kwargs):
        assert command[0] == "/usr/bin/cursor-agent"
        assert command[command.index("--output-format") + 1] == "json"
        assert command[command.index("--mode") + 1] == "ask"
        assert command[command.index("--sandbox") + 1] == "enabled"
        assert "--print" in command
        assert "--trust" in command
        assert command[command.index("--model") + 1] == expected
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 90
        assert not kwargs.get("shell")
        assert "Kissa nukkuu." in command[-1]
        assert json.loads(command[-1].splitlines()[1]) == service.SCHEMA
        payload = json.loads(command[-1].rsplit("\n", 1)[1])
        assert payload["target_language"] == (
            "Finnish" if translation_mode == "personal" else "Russian"
        )
        reply = "```json\n" + json.dumps(RESULT) + "\n```"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": reply,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(service.subprocess, "run", run)
    assert (
        service.translate(
            "Finnish",
            "Russian",
            model,
            "kissa",
            "Kissa nukkuu.",
            reasoning_effort=effort,
            fast_mode=fast_mode,
            cli="cursor",
            translation_mode=translation_mode,
        )
        == RESULT
    )


def test_cursor_agent_errors_do_not_leak_the_reply(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/bin/cursor-agent")

    def run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "subtype": "error",
                    "is_error": True,
                    "result": "SECRET prompt",
                }
            ),
            stderr="ERROR: last status: 429 Too Many Requests",
        )

    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(service.RateLimitError) as error:
        service.translate("Finnish", "Russian", "", "kissa", "", cli="cursor")
    assert "SECRET" not in str(error.value)
    assert "Cursor Agent" in str(error.value)


def test_missing_cursor_agent_is_actionable(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    with pytest.raises(service.TranslationError) as error:
        service.translate("Finnish", "Russian", "", "kissa", "", cli="cursor")
    assert "cursor-agent login" in str(error.value)


def test_translation_cache_changes_with_cli(client, spanish, monkeypatch):
    monkeypatch.setattr(service, "translate", lambda *args: RESULT)
    jobs = client.application.extensions["codex_translation_jobs"]
    payload = {"language_id": spanish.id, "text": "gato"}
    try:
        first = client.post("/translation/jobs", json=payload).json["job_id"]
        spanish.translation_cli = "cursor"
        db.session.commit()
        second = client.post("/translation/jobs", json=payload).json["job_id"]
        assert second != first
        assert jobs.key_for(second)[10] == "cursor"
    finally:
        jobs.pool.shutdown(wait=True)


def test_cli_uses_selected_model_and_structured_output(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda value: "/usr/bin/codex")

    def run(command, **kwargs):
        assert command[command.index("--model") + 1] == "test-model"
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert "--ephemeral" in command
        assert kwargs["timeout"] == 90
        assert not kwargs.get("shell")
        assert "Kissa nukkuu." in kwargs["input"]
        assert "Russian" in kwargs["input"]
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps(RESULT), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)
    assert (
        service.translate("Finnish", "Russian", "test-model", "kissa", "Kissa nukkuu.")
        == RESULT
    )


@pytest.mark.parametrize(
    "effort,fast_mode", [("low", True), ("max", False), ("", False)]
)
def test_cli_overrides_reasoning_and_speed(monkeypatch, effort, fast_mode):
    monkeypatch.setattr(service.shutil, "which", lambda value: "/usr/bin/codex")

    def run(command, **kwargs):
        overrides = [command[i + 1] for i, value in enumerate(command) if value == "-c"]
        assert f'service_tier="{"priority" if fast_mode else "default"}"' in overrides
        if effort:
            assert f'model_reasoning_effort="{effort}"' in overrides
        else:
            assert not any(
                value.startswith("model_reasoning_effort=") for value in overrides
            )
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps(RESULT)
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)
    assert (
        service.translate(
            "Finnish",
            "Russian",
            "test-model",
            "kissa",
            "",
            reasoning_effort=effort,
            fast_mode=fast_mode,
        )
        == RESULT
    )


def test_effort_metadata_is_optional_and_filters_invalid_levels(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert service.available_models() == []
    assert service.available_model_efforts() == {}
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "test-model",
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "max"},
                            {"effort": []},
                            None,
                        ],
                    }
                ]
            }
        )
    )
    assert service.available_model_efforts() == {"test-model": ["low", "max"]}


@pytest.mark.parametrize(
    "setting,value", [("codex_reasoning_effort", "low"), ("codex_fast_mode", True)]
)
def test_translation_cache_changes_with_settings(
    client, spanish, monkeypatch, setting, value
):
    monkeypatch.setattr(service, "translate", lambda *args: RESULT)
    db.session.commit()
    jobs = client.application.extensions["codex_translation_jobs"]
    payload = {"language_id": spanish.id, "text": "gato"}
    try:
        first = client.post("/translation/jobs", json=payload).json["job_id"]
        assert client.post("/translation/jobs", json=payload).json["job_id"] == first
        setattr(spanish, setting, value)
        db.session.commit()
        second = client.post("/translation/jobs", json=payload).json["job_id"]
        assert second != first
        assert jobs.key_for(second)[7:9] == (
            spanish.codex_reasoning_effort,
            spanish.codex_fast_mode,
        )
    finally:
        jobs.pool.shutdown(wait=True)


@pytest.mark.parametrize("failure", ["missing", "timeout", "exit", "invalid"])
def test_cli_errors_are_actionable_and_do_not_leak_logs(monkeypatch, failure):
    monkeypatch.setattr(
        service.shutil,
        "which",
        lambda value: None if failure == "missing" else "/usr/bin/codex",
    )

    def run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 90)
        if failure == "invalid":
            Path(command[command.index("--output-last-message") + 1]).write_text("{}")
        return SimpleNamespace(
            returncode=1 if failure == "exit" else 0, stderr="SECRET"
        )

    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(service.TranslationError) as error:
        service.translate("Finnish", "Russian", "", "kissa", "")
    assert "SECRET" not in str(error.value)


def test_background_jobs_deduplicate_and_cache(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def translate(*args):
        started.set()
        release.wait(3)
        return RESULT

    monkeypatch.setattr(service, "translate", translate)
    jobs = service.TranslationJobs()
    key = ("Finnish", "Russian", "", "kissa", "", "term")
    try:
        job = jobs.submit(key)
        assert started.wait(3)
        assert jobs.get(job) == {"status": "pending"}
        assert jobs.submit(key) == job
        release.set()
        jobs.pool.shutdown(wait=True)
        assert jobs.get(job)["result"] == RESULT
        assert jobs.submit(key) == job
        assert jobs.get("unknown") is None
    finally:
        release.set()
        jobs.pool.shutdown(wait=True)


def test_translation_api(client, spanish, monkeypatch):
    monkeypatch.setattr(service, "translate", lambda *args: RESULT)
    payload = {"language_id": spanish.id, "text": "gato", "context": "El gato duerme."}
    assert (
        client.post("/translation/jobs", json={**payload, "language_id": 999})
    ).status_code == 404
    response = client.post("/translation/jobs", json=payload)
    assert response.status_code == 202
    job = response.json["job_id"]
    client.application.extensions["codex_translation_jobs"].pool.shutdown(wait=True)
    assert client.get(f"/translation/jobs/{job}").json["result"] == RESULT
    assert (
        client.post(
            "/translation/jobs", json={**payload, "text": "x" * 4001}
        ).status_code
        == 400
    )
    assert client.post("/translation/jobs", json=[]).status_code == 400


def test_timer_visibility_does_not_invalidate_translation_cache(
    client, spanish, monkeypatch
):
    monkeypatch.setattr(service, "translate", lambda *args: RESULT)
    db.session.commit()
    jobs = client.application.extensions["codex_translation_jobs"]
    payload = {"language_id": spanish.id, "text": "gato"}
    try:
        job_id = client.post("/translation/jobs", json=payload).json["job_id"]
        spanish.codex_show_timer = False
        db.session.commit()
        assert client.post("/translation/jobs", json=payload).json["job_id"] == job_id
    finally:
        jobs.pool.shutdown(wait=True)


def test_cli_rejects_invented_phrase_words(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda value: "/usr/bin/codex")

    def run(command, **kwargs):
        result = {**RESULT, "words": [{"text": "invented"}]}
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps(result), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(service.TranslationError):
        service.translate(
            "English", "Russian", "", "cats went", "", "term", ("cats", "went")
        )


@pytest.mark.parametrize(
    "lemma_options",
    [
        [],
        "invalid",
        [None],
        [{"translation": "", "explanation": ""}],
        [{"translation": "x" * 501, "explanation": ""}],
        [{"translation": "идти", "explanation": []}],
    ],
)
def test_cli_rejects_invalid_parent_options(monkeypatch, lemma_options):
    monkeypatch.setattr(service.shutil, "which", lambda value: "/usr/bin/codex")

    def run(command, **kwargs):
        result = {
            **RESULT,
            "lemma": "go",
            "is_inflected": True,
            "lemma_translation": "идти",
            "lemma_options": lemma_options,
        }
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps(result), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(service.TranslationError):
        service.translate("English", "Russian", "", "went", "")


def test_cli_returns_dictionary_form_options(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda value: "/usr/bin/codex")
    result = {
        **RESULT,
        "lemma": "go",
        "is_inflected": True,
        "lemma_translation": "идти",
        "lemma_options": [
            {"translation": "идти", "explanation": "Пешком"},
            {"translation": "ехать", "explanation": "На транспорте"},
        ],
    }

    def run(command, **kwargs):
        schema = json.loads(
            Path(command[command.index("--output-schema") + 1]).read_text()
        )
        assert "lemma_options" in schema["required"]
        assert "lemma_options" in kwargs["input"]
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps(result), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)
    assert service.translate("English", "Russian", "", "went", "") == result


@pytest.mark.parametrize("count", [1, 6])
@pytest.mark.parametrize("is_inflected", [False, True])
def test_cli_preserves_one_or_many_meanings(monkeypatch, count, is_inflected):
    monkeypatch.setattr(service.shutil, "which", lambda value: "/usr/bin/codex")
    meanings = [
        ("бежал", "бежать", "Двигаться бегом"),
        ("управлял", "управлять", "Руководить организацией"),
        ("работал", "работать", "Функционировать, о механизме"),
        ("проводил", "проводить", "Организовывать мероприятие"),
        ("баллотировался", "баллотироваться", "Участвовать в выборах"),
        ("протекал", "протекать", "Течь, о жидкости"),
    ][:count]
    result = {
        **RESULT,
        "lemma": "run",
        "is_inflected": is_inflected,
        "lemma_translation": meanings[0][1],
        "options": [
            {"translation": past if is_inflected else base, "explanation": explanation}
            for past, base, explanation in meanings
        ],
        "lemma_options": (
            [
                {"translation": base, "explanation": explanation}
                for _, base, explanation in meanings
            ]
            if is_inflected
            else []
        ),
    }

    def run(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps(result), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)
    text = "ran" if is_inflected else "run"
    assert service.translate("English", "Russian", "", text, "") == result


@pytest.mark.parametrize("options", [[], "invalid"])
def test_cli_requires_nonempty_translation_options(monkeypatch, options):
    monkeypatch.setattr(service.shutil, "which", lambda value: "/usr/bin/codex")

    def run(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps({**RESULT, "options": options}), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(service.TranslationError):
        service.translate("Finnish", "Russian", "", "kissa", "")
