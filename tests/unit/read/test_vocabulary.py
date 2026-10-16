"""Offline lookup respects statuses, explicit families and Finnish inflection."""

import json
import sys
import pytest
from lute.db import db
from lute.models.language import Language
from lute.models.term import Term
from lute.translation.vocabulary import Vocabulary
from lute.cli.vocabulary import main


@pytest.fixture(name="finnish")
def fixture_finnish(app_context):
    language = Language()
    language.name = "Finnish"
    db.session.add(language)
    db.session.commit()
    return language


def add(language, text, status=99, parents=()):
    term = Term(language, text)
    term.status = status
    term.parents = list(parents)
    db.session.add(term)
    return term


def test_finnish_forms_and_lexicalized_adverb(finnish):
    for word in ("minä", "olla", "tehdä", "tarve"):
        add(finnish, word)
    db.session.commit()
    entries = Vocabulary(db.session, finnish).lookup(
        ["Minulla", "ollut", "tehnyt", "tarpeeksi"]
    )
    assert [(e["lemma"], e["known"]) for e in entries] == [
        ("minä", True),
        ("olla", True),
        ("tehdä", True),
        ("tarpeeksi", False),
    ]


def test_parent_families_override_morphology_and_remain_local(finnish, english):
    root = add(finnish, "tulla", 1)
    add(finnish, "tuli", 99, [root])
    add(finnish, "tullut", 1, [root])
    add(english, "foreign", 99)
    db.session.commit()
    entries = Vocabulary(db.session, finnish).lookup(
        ["tulla", "tuli", "tullut", "foreign"]
    )
    assert [e["known"] for e in entries] == [True, True, True, False]
    assert entries[2]["parents"] == ["tulla"]
    assert root.status == 1


def test_learning_status_overrides_inferred_lemma_but_placeholder_does_not(finnish):
    add(finnish, "minä")
    add(finnish, "minulla", 1)
    add(finnish, "minulle", 0)
    db.session.commit()
    entries = Vocabulary(db.session, finnish).lookup(["minulla", "minulle"])
    assert [e["known"] for e in entries] == [False, True]


def test_check_ignores_punctuation_numbers_and_selected_target(finnish):
    add(finnish, "minä")
    add(finnish, "olla")
    add(finnish, "Pia", 98)
    db.session.commit()
    report = Vocabulary(db.session, finnish).check(
        "Minulla on 2. Pia! Tarpeeksi? Huusin.", exclude=["huusin"]
    )
    assert [e["text"] for e in report["unknown"]] == ["tarpeeksi"]
    assert [e["text"] for e in report["ignored"]] == ["pia", "huusin"]


def test_tools_are_read_only_and_share_search_and_batch_logic(
    client, finnish, monkeypatch
):
    add(finnish, "minä")
    add(finnish, "tarpeeksi", 1)
    db.session.commit()
    before = db.session.query(Term).count()
    monkeypatch.setattr(
        "lute.translation.service.translate",
        lambda *args: pytest.fail("No model calls"),
    )
    lookup = client.post(
        "/translation/vocabulary",
        json={"language_id": finnish.id, "words": ["minulla", "tarpeeksi"]},
    )
    assert [e["known"] for e in lookup.json["matches"]] == [True, False]
    search = client.get(f"/translation/vocabulary?language_id={finnish.id}&q=tarpe")
    assert search.json["matches"][0]["text"] == "tarpeeksi"
    check = client.post(
        "/translation/vocabulary/check",
        json={"language_id": finnish.id, "text": "Minulla tarpeeksi."},
    )
    assert [e["text"] for e in check.json["unknown"]] == ["tarpeeksi"]
    assert db.session.query(Term).count() == before


@pytest.mark.parametrize("words", [None, [], [None], ["x" * 251]])
def test_batch_rejects_invalid_words(client, finnish, words):
    assert (
        client.post(
            "/translation/vocabulary", json={"language_id": finnish.id, "words": words}
        ).status_code
        == 400
    )


def test_standalone_cli_reads_the_requested_database(app, finnish, monkeypatch, capsys):
    add(finnish, "minä")
    db.session.commit()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vocabulary",
            "--database",
            app.env_config.dbfilename,
            "lookup",
            "Finnish",
            "minulla",
            "tarpeeksi",
        ],
    )
    main()
    entries = json.loads(capsys.readouterr().out)
    assert [e["known"] for e in entries] == [True, False]
