"""A generic first prompt, local checks, and exactly one bounded revision."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from lute.db import db
from lute.models.language import Language
from lute.translation import service, store
from tests.unit.read.test_vocabulary import add
from tests.unit.read.test_codex_store import _lookup, _result


def answer(text):
    return {
        "lemma": "ehtiä",
        "is_inflected": False,
        "lemma_translation": "",
        "lemma_options": [],
        "options": [{"translation": text, "explanation": ""}],
        "words": [],
        "phrases": [],
    }


@pytest.fixture(name="learner")
def fixture_learner(app_context):
    language = Language()
    language.name = "Finnish"
    language.translation_mode = "personal"
    db.session.add(language)
    for word in ("minä", "olla", "ei", "aika", "tehdä"):
        add(language, word)
    db.session.commit()
    return language


def test_familiar_answer_needs_only_one_generation(client, learner, monkeypatch):
    generate = Mock(return_value=answer("Minulla ei ollut aikaa."))
    monkeypatch.setattr(service, "translate", generate)
    response = _lookup(client, learner, text="ehtinyt")
    result = _result(client, response.json["job_id"])["result"]
    generate.assert_called_once()
    assert result["vocabulary"]["unknown"] == []
    assert result["vocabulary"]["revised"] is False


@pytest.mark.parametrize(
    "second", ["Minulla ei ollut aikaa.", "Minulla oli riittävästi aikaa."]
)
def test_one_revision_is_accepted_even_with_new_unknown_words(
    client, learner, monkeypatch, second
):
    generate = Mock(
        side_effect=[answer("Minulla ei ollut tarpeeksi aikaa."), answer(second)]
    )
    monkeypatch.setattr(service, "translate", generate)
    response = _lookup(client, learner, text="ehtinyt")
    result = _result(client, response.json["job_id"])["result"]
    assert generate.call_count == 2
    assert result["options"][0]["translation"] == second
    assert result["vocabulary"]["revised"] is True
    assert bool(result["vocabulary"]["unknown"]) == ("riittävästi" in second)
    feedback = generate.call_args_list[1].args[13]
    assert feedback["unfamiliar_words"] == [{"text": "tarpeeksi", "lemma": "tarpeeksi"}]
    assert "known_words" not in feedback
    assert set(feedback["familiar_words"]) <= {"minä", "ei", "olla", "aika"}


def test_learning_target_in_example_is_not_an_unfamiliar_obstacle(
    client, learner, monkeypatch
):
    result = answer("Minulla ei ollut aikaa.")
    result["options"][0]["explanation"] = "En ehtinyt."
    add(learner, "en")
    db.session.commit()
    generate = Mock(return_value=result)
    monkeypatch.setattr(service, "translate", generate)
    response = _lookup(client, learner, text="ehtinyt")
    assert (
        _result(client, response.json["job_id"])["result"]["vocabulary"]["unknown"]
        == []
    )
    generate.assert_called_once()


@pytest.mark.parametrize("needs_revision", [False, True])
def test_phrase_with_empty_lemma_completes_and_is_saved(
    client, learner, monkeypatch, needs_revision
):
    for word in ("panna", "se", "sinne", "ovi", "luona", "huone", "alas", "alhaalla"):
        add(learner, word)
    db.session.commit()
    phrase = "jätin eteisen lattialle"
    context = "Kannoin sen turvaistuimessa sisälle ja jätin eteisen lattialle."
    result = {
        **answer("Panin sen lattialle."),
        "lemma": "",
        "words": [
            {
                "text": text,
                "translation": translation,
                "lemma": lemma,
                "is_inflected": True,
                "lemma_translation": base_translation,
            }
            for text, translation, lemma, base_translation in (
                ("jätin", "Panin sen sinne.", "jättää", "Panna."),
                ("eteisen", "Oven luona.", "eteinen", "Huone."),
                ("lattialle", "Alas.", "lattia", "Alhaalla."),
            )
        ],
    }
    calls = []

    def run_cli(command, workdir, cli, prompt=None):
        payload = json.loads(prompt.rsplit("\n", 1)[1])
        calls.append(payload)
        assert payload["words_to_translate"] == phrase.split()
        assert payload["fallback_language"] == "Russian"
        assert "known_words" not in payload
        if len(calls) == 2:
            assert "fallback" not in payload["revision"]["previous_result"]
        output = {**result, "fallback": result}
        if needs_revision and len(calls) == 1:
            output = {
                **output,
                "options": [
                    {"translation": "Panin sen varovasti lattialle.", "explanation": ""}
                ],
            }
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps(output), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service, "_executable", lambda _: "/fake/codex")
    monkeypatch.setattr(service, "_run_cli", run_cli)
    response = _lookup(client, learner, mode="refresh", text=phrase, context=context)
    completed = _result(client, response.json["job_id"])
    assert completed["status"] == "complete", completed
    generated = completed["result"]
    assert generated["lemma"] == ""
    assert generated["words"] == result["words"]
    assert generated["fallback_language"] == "Russian"
    assert generated["fallback"]["words"] == result["words"]
    assert generated["vocabulary"]["unknown"] == []
    assert generated["vocabulary"]["revised"] is needs_revision
    assert len(calls) == (2 if needs_revision else 1)
    assert store.find(db.session, learner, phrase, context=context) == generated


def test_revision_payload_contains_only_output_feedback_not_a_full_dictionary():
    feedback = {
        "previous_result": answer("Tarpeeksi."),
        "unfamiliar_words": [{"text": "tarpeeksi", "lemma": "tarpeeksi"}],
        "familiar_words": [],
    }
    prompt = service._prompt(
        "Finnish", "Finnish", "ehtiä", "", "term", [], (), "personal", feedback
    )
    payload = json.loads(prompt.rsplit("\n", 1)[1])
    assert payload["revision"] == feedback
    assert "known_words" not in payload
