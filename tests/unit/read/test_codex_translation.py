"""Validate the CLI boundary, background jobs, and HTTP translation API."""

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from lute.db import db
from lute.translation import service

RESULT = {
    "lemma": "kissa",
    "is_inflected": False,
    "lemma_translation": "кошка",
    "words": [],
    "options": [
        {"translation": "кошка", "explanation": "В этом предложении"},
        {"translation": "кот", "explanation": "Самец"},
    ],
}


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
    assert client.post("/translation/jobs", json=payload).status_code == 400
    spanish.translation_provider = "codex"
    spanish.translation_target = "Russian"
    db.session.commit()
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
