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
