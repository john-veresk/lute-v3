"""Service throttling pauses all CLI work and leaves safe diagnostic records."""

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from lute.db import db
from lute.translation import service, store
from tests.unit.read.test_codex_store import _lookup, _result
from tests.unit.read.test_codex_translation import RESULT

KEY = ("Finnish", "Russian", "test-model", "PRIVATE WORD", "PRIVATE CONTEXT", "term")


@pytest.mark.parametrize("timeout", [False, True])
def test_cli_recognizes_rate_limit_without_leaking_stderr(monkeypatch, timeout):
    monkeypatch.setattr(service.shutil, "which", lambda _: "/usr/bin/codex")

    def run(command, **kwargs):
        stderr = (
            b"SECRET\nERROR: exceeded retry limit, last status: 429 Too Many Requests"
        )
        if timeout:
            raise subprocess.TimeoutExpired(command, 90, stderr=stderr)
        return SimpleNamespace(returncode=1, stderr=stderr)

    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(service.RateLimitError) as caught:
        service.translate(*KEY)
    assert caught.value.http_status == 429
    assert "SECRET" not in str(caught.value)


def test_prompt_mention_of_429_does_not_trigger_cooldown(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1,
            stderr='user\n{"text": "429 Too Many Requests"}\nERROR: other failure',
        ),
    )
    with pytest.raises(service.TranslationError) as caught:
        service.translate(*KEY)
    assert not isinstance(caught.value, service.RateLimitError)


def test_repeated_throttles_back_off_to_two_minutes_and_reset(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: clock[0])

    def throttled(*args):
        raise service.RateLimitError(exit_code=1)

    monkeypatch.setattr(service, "translate", throttled)
    jobs = service.TranslationJobs()
    try:
        for delay in (30, 60, 120, 120):
            with pytest.raises(service.RateLimitError) as caught:
                jobs._run(KEY, "test", "prefetch")
            assert caught.value.retry_after == delay
            with pytest.raises(service.RateLimitError):
                jobs.submit(KEY)
            # Already queued jobs must not launch Codex during the cooldown.
            with pytest.raises(service.RateLimitError):
                jobs._run(KEY, "queued", "auto")
            assert jobs.rate_limit_count <= 3
            clock[0] += delay
        monkeypatch.setattr(service, "translate", lambda *args: RESULT)
        assert jobs._run(KEY, "success", "auto") == RESULT
        monkeypatch.setattr(service, "translate", throttled)
        with pytest.raises(service.RateLimitError) as caught:
            jobs._run(KEY, "after-success", "auto")
        assert caught.value.retry_after == 30
    finally:
        jobs.pool.shutdown(wait=True)


def test_waiting_queue_does_not_invoke_cli_after_429(monkeypatch):
    release, started = threading.Event(), threading.Event()
    calls = []

    def throttled(*args):
        calls.append(args)
        started.set()
        assert release.wait(3)
        raise service.RateLimitError()

    monkeypatch.setattr(service, "translate", throttled)
    jobs = service.TranslationJobs()
    jobs.pool.shutdown(wait=True)
    jobs.pool = ThreadPoolExecutor(max_workers=1)
    try:
        first = jobs.submit(KEY)
        assert started.wait(3)
        queued = jobs.submit((*KEY[:3], "another", *KEY[4:]))
        release.set()
        jobs.pool.shutdown(wait=True)
        assert len(calls) == 1
        assert jobs.get(first)["error_code"] == "rate_limited"
        assert jobs.get(queued)["retry_after"] > 0
    finally:
        release.set()
        jobs.pool.shutdown(wait=True)


def test_http_reports_cooldown_and_stored_results_remain_available(
    client, spanish, monkeypatch
):
    def throttled(*args):
        raise service.RateLimitError()

    monkeypatch.setattr(service, "translate", throttled)
    job = _lookup(client, spanish).json["job_id"]
    result = _result(client, job)
    assert result["error_code"] == "rate_limited"
    assert 0 < result["retry_after"] <= 30
    blocked = _lookup(client, spanish, text="perro")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) == blocked.json["retry_after"]
    assert client.get(f"/translation/jobs/{job}").json["error_code"] == "rate_limited"
    store.save(db.session, spanish, "saved", "", RESULT)
    saved = _lookup(client, spanish, text="saved")
    assert saved.json["saved"] is True
    assert _result(client, saved.json["job_id"])["status"] == "complete"


def test_diagnostics_record_status_and_duration_without_private_data(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(service.shutil, "which", lambda _: "/usr/bin/codex")
    log_path = tmp_path / "codex-translation.log"
    jobs = service.TranslationJobs(log_path)

    def failed(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stderr="SECRET TOKEN\nERROR: last status: 429 Too Many Requests",
        )

    monkeypatch.setattr(service.subprocess, "run", failed)
    try:
        with pytest.raises(service.RateLimitError):
            jobs._run(KEY, "diagnostic", "prefetch")
        contents = log_path.read_text()
        for secret in ("PRIVATE WORD", "PRIVATE CONTEXT", "SECRET TOKEN"):
            assert secret not in contents
        record = json.loads(contents.splitlines()[-1].split(" WARNING ", 1)[1])
        assert record["http_status"] == 429
        assert record["exit_code"] == 1
        assert record["retry_after"] == 30
        assert record["mode"] == "prefetch"
        assert record["elapsed_s"] >= 0
        handler = jobs.logger.handlers[0]
        assert handler.maxBytes == 2_000_000
        assert handler.backupCount == 3
    finally:
        jobs.pool.shutdown(wait=True)


def test_invalid_response_diagnostic_explains_validation_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(service.shutil, "which", lambda _: "/usr/bin/codex")

    def run(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps({**RESULT, "options": []})
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, "run", run)
    jobs = service.TranslationJobs(tmp_path / "invalid.log")
    try:
        with pytest.raises(service.TranslationError):
            jobs._run(KEY, "invalid", "auto")
        contents = (tmp_path / "invalid.log").read_text()
        assert '"category": "invalid_response"' in contents
        assert '"detail": "Invalid translation"' in contents
    finally:
        jobs.pool.shutdown(wait=True)
