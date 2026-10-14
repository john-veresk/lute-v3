"""Term translations are saved and reused until the reader refreshes them."""

import time
import pytest
from lute.db import db
from lute.translation import service, store
from tests.unit.read.test_codex_translation import RESULT


@pytest.fixture(name="translations")
def fixture_translations(monkeypatch):
    "Fake Codex returning a numbered result per call."
    calls = []

    def translate(*key):
        calls.append(key)
        return {
            **RESULT,
            "options": [{"translation": f"v{len(calls)}", "explanation": ""}],
        }

    monkeypatch.setattr(service, "translate", translate)
    return calls


def _lookup(
    client, language, mode="auto", text="gato", context="El gato duerme.", kind="term"
):
    payload = {
        "language_id": language.id,
        "text": text,
        "context": context,
        "kind": kind,
        "mode": mode,
    }
    return client.post("/translation/jobs", json=payload)


def _result(client, job_id):
    deadline = time.monotonic() + 5
    while True:
        data = client.get(f"/translation/jobs/{job_id}").json
        if data["status"] != "pending" or time.monotonic() > deadline:
            return data
        time.sleep(0.01)


def _first_option(client, response):
    return _result(client, response.json["job_id"])["result"]["options"][0][
        "translation"
    ]


def test_completed_term_is_saved_and_reused(client, spanish, translations):
    first = _lookup(client, spanish)
    assert first.json["saved"] is False
    assert _first_option(client, first) == "v1"
    assert store.find(db.session, spanish, "GATO")["options"][0]["translation"] == "v1"

    again = _lookup(client, spanish, text="Gato", context="Otro gato.")
    assert again.json["saved"] is True
    assert _first_option(client, again) == "v1"
    assert len(translations) == 1


def test_stored_mode_never_translates(client, spanish, translations):
    response = _lookup(client, spanish, mode="stored")
    assert response.status_code == 200
    assert response.json["job_id"] is None
    assert not translations


def test_prefetch_translates_only_unsaved_terms(client, spanish, translations):
    _result(client, _lookup(client, spanish, mode="prefetch").json["job_id"])
    assert _lookup(client, spanish, mode="prefetch").json["job_id"] is None
    assert len(translations) == 1


def test_refresh_replaces_the_saved_result(client, spanish, translations):
    _result(client, _lookup(client, spanish).json["job_id"])
    refreshed = _lookup(client, spanish, mode="refresh")
    assert _first_option(client, refreshed) == "v2"
    assert _first_option(client, _lookup(client, spanish)) == "v2"
    assert len(translations) == 2


def test_saved_phrases_from_another_sentence_are_hidden(client, english, translations):
    phrase = {"text": "looked after", "translation": "присматривал за"}
    store.save(
        db.session,
        english,
        "looked",
        "He looked after the cats.",
        {**RESULT, "phrases": [phrase]},
    )

    same = _result(
        client,
        _lookup(
            client, english, text="looked", context="He looked after the cats."
        ).json["job_id"],
    )
    other = _result(
        client,
        _lookup(client, english, text="looked", context="She looked away.").json[
            "job_id"
        ],
    )
    assert same["result"]["phrases"] == [phrase]
    assert other["result"]["phrases"] == []
    assert not translations


def test_sentences_are_not_saved(client, spanish, translations):
    _result(
        client,
        _lookup(
            client, spanish, text="El gato duerme.", context="", kind="sentence"
        ).json["job_id"],
    )
    assert store.find(db.session, spanish, "El gato duerme.") is None


def test_unknown_mode_is_rejected(client, spanish, translations):
    assert _lookup(client, spanish, mode="later").status_code == 400
    assert not translations
