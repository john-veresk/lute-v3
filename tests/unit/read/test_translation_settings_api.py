"""CLI/model updates preserve job checkpoints and in-flight translation results."""

import json
import threading
import pytest
from lute.db import db
from tests.unit.read.test_translation_jobs import (
    RESULT,
    enqueue,
    get_job,
    make_books,
    worker_for,
)


def test_language_settings_are_partial_and_do_not_change_queued_jobs(client, spanish):
    spanish.codex_reasoning_effort = "high"
    spanish.codex_fast_mode = True
    book = make_books(spanish, ["Gato."])[0]
    job_id = enqueue(client, [book])[0]
    original = get_job(job_id).settings
    url = f"/language/{spanish.id}/translation-settings"
    response = client.patch(
        url, json={"cli": "cursor", "model": "cursor-grok-4.6-medium"}
    )
    assert response.status_code == 200
    assert response.json == {
        "language_id": spanish.id,
        "cli": "cursor",
        "model": "cursor-grok-4.6-medium",
        "effort": "",
    }
    assert client.get(url).json == response.json
    db.session.refresh(spanish)
    assert spanish.codex_reasoning_effort == "high"
    assert spanish.codex_fast_mode is True
    assert spanish.translation_target == "Russian"
    assert get_job(job_id).settings == original
    response = client.patch(url, json={"model": "cursor-grok-4.6-medium-fast"})
    assert response.json["cli"] == "cursor"
    assert response.json["model"] == "cursor-grok-4.6-medium-fast"


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"cli": "unknown"},
        {"cli": []},
        {"model": None},
        {"model": "--help"},
        {"model": "a b"},
        {"model": "a" * 101},
        {"effort": "invalid"},
        {"effort": []},
        {"target": "English"},
        {"cli": "cursor", "effort": "high"},
    ],
)
def test_invalid_settings_are_atomic_for_both_endpoints(client, spanish, data):
    book = make_books(spanish, ["Gato."])[0]
    job_id = enqueue(client, [book])[0]
    url = f"/language/{spanish.id}/translation-settings"
    original = client.get(url).json
    job_settings = get_job(job_id).settings
    for endpoint in (url, f"/jobs/{job_id}/settings"):
        assert client.patch(endpoint, json=data).status_code == 400
    assert client.get(url).json == original
    assert get_job(job_id).settings == job_settings


def test_job_settings_preserve_checkpoint_and_pause(client, spanish, monkeypatch):
    book = make_books(spanish, ["Gato perro."])[0]
    job_id = enqueue(client, [book])[0]
    worker, translate = worker_for(client, monkeypatch)
    worker.step()
    client.post(f"/jobs/{job_id}/pause")
    before = client.get(f"/jobs/{job_id}/settings").json["job"]
    response = client.patch(
        f"/jobs/{job_id}/settings",
        json={"cli": "cursor", "model": "cursor-grok-4.6-medium"},
    )
    assert response.status_code == 200
    job = response.json["job"]
    for field in ("done", "total", "translated", "skipped", "start_page", "status"):
        assert job[field] == before[field]
    assert response.json["applies_after_current_word"] is False
    db.session.refresh(spanish)
    assert spanish.translation_cli == "codex"
    assert not worker.step()
    client.post(f"/jobs/{job_id}/resume")
    worker.step()
    key = translate.call_args.args[0]
    assert key[2:4] == ("cursor-grok-4.6-medium", "perro")
    assert key[7] == ""
    assert key[10] == "cursor"
    assert get_job(job_id).status == "complete"
    assert (
        client.patch(f"/jobs/{job_id}/settings", json={"model": ""}).status_code == 409
    )


def test_change_during_translation_applies_to_next_word(client, spanish, monkeypatch):
    book = make_books(spanish, ["Gato perro."])[0]
    job_id = enqueue(client, [book])[0]
    worker, translate = worker_for(client, monkeypatch)
    started, release = threading.Event(), threading.Event()
    keys = []

    def blocking_translate(key, _language_id):
        keys.append(key)
        started.set()
        assert release.wait(5)
        return RESULT

    translate.side_effect = blocking_translate
    thread = threading.Thread(target=worker.step)
    thread.start()
    try:
        assert started.wait(5)
        response = client.patch(
            f"/jobs/{job_id}/settings", json={"cli": "cursor", "model": "new-model"}
        )
        assert response.status_code == 200
        assert response.json["applies_after_current_word"] is True
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert get_job(job_id).done == 1
    assert json.loads(get_job(job_id).settings)["model"] == "new-model"
    worker.step()
    assert keys[0][10] == "codex"
    assert keys[1][2] == "new-model"
    assert keys[1][10] == "cursor"
    assert get_job(job_id).done == 2


def test_codex_effort_validation_and_missing_records(client, spanish, monkeypatch):
    monkeypatch.setattr(
        "lute.translation.settings.available_model_efforts", lambda: {"test": ["low"]}
    )
    url = f"/language/{spanish.id}/translation-settings"
    assert (
        client.patch(url, json={"model": "test", "effort": "high"}).status_code == 400
    )
    assert client.patch(url, json={"model": "test", "effort": "low"}).status_code == 200
    for url in ("/language/999999/translation-settings", "/jobs/999999/settings"):
        assert client.get(url).status_code == 404
        assert client.patch(url, json={"model": ""}).status_code == 404


def test_cancelled_job_settings_are_readable_but_immutable(client, spanish):
    book = make_books(spanish, ["Gato."])[0]
    job_id = enqueue(client, [book])[0]
    client.post(f"/jobs/{job_id}/cancel")
    assert client.get(f"/jobs/{job_id}/settings").status_code == 200
    assert (
        client.patch(f"/jobs/{job_id}/settings", json={"model": ""}).status_code == 409
    )
