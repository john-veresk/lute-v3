"""Translation-only upgrades preserve normal translations and unrelated settings."""

import json
import sqlite3
from pathlib import Path
import pytest
from lute.models.language import Language
from lute.translation import service
from tests.unit.read.test_codex_translation import RESULT

MIGRATIONS = Path("lute/db/schema/migrations")


@pytest.fixture(name="legacy_db")
def fixture_legacy_db():
    """Tables from before removing the personal output mode."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE languages (LgID INTEGER PRIMARY KEY, LgName TEXT,
          LgTranslationTarget TEXT, LgCodexModel TEXT, LgTranslationCli TEXT);
        INSERT INTO languages VALUES (1, 'Finnish', 'Russian', 'custom-model', 'cursor');
        CREATE TABLE words (WoID INTEGER PRIMARY KEY, WoTranslation TEXT);
        INSERT INTO words VALUES (1, 'saved vocabulary text');
    """)
    for name in (
        "20261014_codex_translation_store.sql",
        "20261016_personal_translation.sql",
        "20261016_translation_profiles.sql",
        "20261016_translation_contexts.sql",
        "20261016_translation_contexts_position.sql",
        "20261016_book_translation_jobs.sql",
        "20261016_book_translation_timing.sql",
    ):
        connection.executescript((MIGRATIONS / name).read_text())
    yield connection
    connection.close()


@pytest.mark.parametrize("fallback", ["English", "Russian", "", None])
def test_upgrade_removes_personal_data_and_keeps_ordinary_data(legacy_db, fallback):
    """Only personal jobs restart; caches and checkpoints for normal jobs survive."""
    connection = legacy_db
    normal = {
        "language_id": 1,
        "source": "Finnish",
        "target": "Russian",
        "model": "custom-model",
        "cli": "cursor",
        "effort": "",
    }
    personal = {
        **normal,
        "target": "Finnish",
        "translation_mode": "personal",
        "target_label": "Personal Finnish",
        "known_words": ["kissa"],
        "vocabulary_revision": "old",
    }
    if fallback is not None:
        personal["fallback_target"] = fallback
    connection.execute("UPDATE languages SET LgTranslationMode = 'personal'")
    for job_id, settings, status in (
        (1, normal, "running"),
        (2, personal, "running"),
        (3, personal, "complete"),
    ):
        connection.execute(
            """INSERT INTO booktranslationjobs
            (id, title, status, position, settings, total, done, translated,
             items, start_page, created_at, updated_at)
            VALUES (?, 'Book', ?, ?, ?, 10, 2, 2, '[]', 3, '2026-10-16', '2026-10-16')""",
            (job_id, status, job_id, json.dumps(settings)),
        )
        connection.execute(
            """INSERT INTO booktranslationwordtimings
            (job_id, word_index, word, page, status, duration_seconds)
            VALUES (?, 0, 'kissa', 3, 'translated', 12)""",
            (job_id,),
        )
    for profile, result in (
        ("translation:7:FinnishRussian", RESULT),
        (
            "translation:7:FinnishEnglish",
            {
                **RESULT,
                "fallback": RESULT,
                "fallback_language": "Russian",
                "vocabulary": {},
            },
        ),
        ("personal:7:Finnish", RESULT),
        ("personal:old", RESULT),
    ):
        connection.execute(
            """INSERT INTO codextranslations (CtLgID, CtTextLC, CtResult, CtUpdated, CtProfile)
            VALUES (1, 'kissa', ?, '2026-10-16', ?)""",
            (json.dumps(result), profile),
        )
    for profile in ("personal", "personal:old", "translation:7:FinnishRussian"):
        connection.execute(
            """INSERT INTO translationcontexts
            (language_id, book_id, text_lc, profile, context_key, page, sentence,
             excerpt, note, updated) VALUES (1, 1, 'kissa', ?, 'key', 3,
             'Kissa nukkuu.', 'Kissa nukkuu.', 'usage note', '2026-10-16')""",
            (profile,),
        )
    original_job = dict(
        connection.execute("SELECT * FROM booktranslationjobs WHERE id = 1").fetchone()
    )
    original_timing = dict(
        connection.execute(
            "SELECT * FROM booktranslationwordtimings WHERE job_id = 1"
        ).fetchone()
    )
    connection.executescript(
        (MIGRATIONS / "20261016_z_translation_only.sql").read_text()
    )
    assert "LgTranslationMode" not in {
        row[1] for row in connection.execute("PRAGMA table_info(languages)")
    }
    language = connection.execute("SELECT * FROM languages").fetchone()
    assert tuple(language) == (1, "Finnish", "Russian", "custom-model", "cursor")
    assert (
        connection.execute("SELECT WoTranslation FROM words").fetchone()[0]
        == "saved vocabulary text"
    )
    cached = connection.execute(
        "SELECT CtProfile, CtResult FROM codextranslations ORDER BY CtID"
    ).fetchall()
    assert [(row[0], json.loads(row[1])) for row in cached] == [
        ("translation:7:FinnishRussian", RESULT),
        ("translation:7:FinnishEnglish", RESULT),
    ]
    assert [
        row[0] for row in connection.execute("SELECT profile FROM translationcontexts")
    ] == ["translation:7:FinnishRussian"]
    job = dict(
        connection.execute("SELECT * FROM booktranslationjobs WHERE id = 1").fetchone()
    )
    assert {**job, "settings": json.loads(job["settings"])} == {
        **original_job,
        "settings": normal,
    }
    assert (
        dict(
            connection.execute(
                "SELECT * FROM booktranslationwordtimings WHERE job_id = 1"
            ).fetchone()
        )
        == original_timing
    )
    job = connection.execute(
        "SELECT * FROM booktranslationjobs WHERE id = 2"
    ).fetchone()
    assert job["status"] == "paused"
    assert (job["done"], job["translated"], job["start_page"], job["items"]) == (
        0,
        0,
        3,
        "[]",
    )
    assert json.loads(job["settings"]) == {**normal, "target": fallback or "Russian"}
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM booktranslationwordtimings WHERE job_id = 2"
        ).fetchone()[0]
        == 0
    )
    completed = connection.execute(
        "SELECT status, done FROM booktranslationjobs WHERE id = 3"
    ).fetchone()
    assert tuple(completed) == ("complete", 2)


def test_language_form_and_cards_offer_only_the_target_language(client, spanish):
    page = client.get(f"/language/edit/{spanish.id}").data
    assert b"Translate into" in page
    assert b"translation_mode" not in page
    assert b"Fallback language" not in page
    assert "translation_mode" not in spanish.to_dict()
    imported = Language.from_dict({**spanish.to_dict(), "translation_mode": "personal"})
    assert imported.translation_target == spanish.translation_target
    assert not hasattr(imported, "translation_mode")
    for url in (
        f"/term/editbytext/{spanish.id}/gato",
        f"/translation/panel?language_id={spanish.id}",
    ):
        card = client.get(url).data
        assert b"codex-fallback" not in card
        assert b"codex-vocabulary" not in card
        assert b"translating into Russian" in card


@pytest.mark.parametrize("kind", ["term", "sentence"])
def test_only_target_language_translation_prompt_is_used(kind):
    prompt = service._prompt(
        "Finnish", "English", "kissa", "Kissa nukkuu.", kind, [], ()
    )
    instructions, payload = prompt.rsplit("\n", 1)
    assert "Translate the selected text into target_language" in instructions
    assert "simplified paraphrase" not in instructions
    assert "fallback" not in instructions
    assert json.loads(payload)["target_language"] == "English"
    assert "fallback" not in service._response_schema()["properties"]
