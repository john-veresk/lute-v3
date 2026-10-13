"""Review selection, live cards, and persistence through the existing term API."""

import json
from datetime import datetime, timedelta
import pytest
from bs4 import BeautifulSoup
from lute.db import db
from lute.models.term import Term, TermTag
from lute.term.review import Service, card_data
from tests.utils import make_book


def save_terms(language, definitions):
    """Create explicit saved translations for review scenarios."""
    terms = {}
    for text, translation, status in definitions:
        term = Term(language, text)
        term.translation = translation
        term.status = status
        db.session.add(term)
        terms[text] = term
    db.session.commit()
    return terms


def queue_from(response):
    """Read the review page's transient configuration."""
    assert response.status_code == 200
    document = BeautifulSoup(response.data, "html.parser")
    return json.loads(document.select_one("#review-queue").string)


def test_selected_terms_are_exact_and_never_expand_parents(client, spanish):
    terms = save_terms(
        spanish, [("gatos", "cats", 2), ("gato", "cat", 3), ("perro", "dog", 1)]
    )
    terms["gatos"].add_parent(terms["gato"])
    db.session.commit()
    queue = queue_from(
        client.post(
            "/term/review",
            data={"selected_ids": f'{terms["gatos"].id},{terms["gatos"].id}'},
        )
    )
    assert queue == {"term_ids": [terms["gatos"].id], "untranslated": 0}


def test_all_filtered_results_include_other_table_pages(client, spanish):
    terms = save_terms(
        spanish,
        [(f"word{i}", "matching translation", 2) for i in range(35)]
        + [("other", "different", 4)],
    )
    queue = queue_from(
        client.post(
            "/term/review",
            data={
                "start": "25",
                "length": "10",
                "filtLanguage": str(spanish.id),
                "filtStatusMin": "2",
                "filtStatusMax": "2",
                "search[value]": "matching",
            },
        )
    )
    assert set(queue["term_ids"]) == {
        term.id for name, term in terms.items() if name != "other"
    }
    assert len(queue["term_ids"]) == 35


def test_status_filters_and_unknown_exclusion(client, spanish):
    terms = save_terms(
        spanish,
        [
            ("unknown", "?", 0),
            ("learning", "learn", 3),
            ("known", "know", 99),
            ("ignored", "ignore", 98),
        ],
    )
    response = client.post(
        "/term/review", data={"filtLanguage": str(spanish.id), "filtStatusMin": "0"}
    )
    assert set(queue_from(response)["term_ids"]) == {
        terms["learning"].id,
        terms["known"].id,
    }
    response = client.post(
        "/term/review",
        data={
            "filtLanguage": str(spanish.id),
            "filtStatusMin": "0",
            "filtIncludeIgnored": "true",
        },
    )
    assert set(queue_from(response)["term_ids"]) == {
        terms[name].id for name in ["learning", "known", "ignored"]
    }


def test_reading_pane_filter_includes_only_direct_parents(client, spanish):
    terms = save_terms(
        spanish, [("gatos", "cats", 2), ("gato", "cat", 2), ("felino", "feline", 2)]
    )
    terms["gatos"].add_parent(terms["gato"])
    terms["gato"].add_parent(terms["felino"])
    db.session.commit()
    queue = queue_from(
        client.post("/term/review", data={"filtTermIDs": str(terms["gatos"].id)})
    )
    assert set(queue["term_ids"]) == {terms["gatos"].id, terms["gato"].id}


def test_parent_and_tag_search_and_parent_only_filter(client, spanish):
    terms = save_terms(
        spanish, [("gatos", "cats", 2), ("gato", "cat", 2), ("perro", "dog", 2)]
    )
    terms["gatos"].add_parent(terms["gato"])
    tag = TermTag("animals")
    terms["gato"].add_term_tag(tag)
    db.session.commit()
    queue = queue_from(
        client.post(
            "/term/review",
            data={"filtLanguage": str(spanish.id), "search[value]": "animals"},
        )
    )
    assert queue["term_ids"] == [terms["gato"].id]
    queue = queue_from(
        client.post(
            "/term/review",
            data={"filtLanguage": str(spanish.id), "filtParentsOnly": "true"},
        )
    )
    assert set(queue["term_ids"]) == {terms["gato"].id, terms["perro"].id}


def test_age_filter_uses_the_same_selection_as_terms(client, spanish):
    terms = save_terms(spanish, [("old", "old", 1), ("new", "new", 1)])
    db.session.execute(
        db.text("UPDATE words SET WoCreated = :created WHERE WoID = :id"),
        {
            "created": (datetime.now() - timedelta(days=10)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "id": terms["old"].id,
        },
    )
    db.session.commit()
    queue = queue_from(
        client.post(
            "/term/review",
            data={
                "filtLanguage": str(spanish.id),
                "filtAgeMin": "5",
                "filtAgeMax": "15",
            },
        )
    )
    assert queue["term_ids"] == [terms["old"].id]


def test_entire_book_includes_unread_pages_and_deduplicated_direct_parents(
    client, spanish, english
):
    terms = save_terms(
        spanish,
        [
            ("gatos", "cats", 2),
            ("gato", "cat", 3),
            ("animal", "animal", 1),
            ("felino", "feline", 2),
            ("perro", "dog", 4),
            ("un perro", "a dog", 2),
            ("gatos perro", "must not cross pages", 2),
            ("outside", "outside", 1),
            ("known", "known", 99),
            ("ignored", "ignored", 98),
            ("unknown", "unknown", 0),
        ],
    )
    save_terms(english, [("gatos", "English false match", 1)])
    terms["gatos"].add_parent(terms["gato"])
    terms["gatos"].add_parent(terms["animal"])
    terms["gato"].add_parent(terms["felino"])
    book = make_book(
        "My book",
        ["Gatos gatos", "perro un perro gatos known ignored unknown"],
        spanish,
    )
    other_book = make_book("Other", "outside", spanish)
    db.session.add_all([book, other_book])
    db.session.commit()
    before_count = db.session.query(Term).count()
    queue = queue_from(client.get(f"/term/review?book_id={book.id}&page_num=2"))
    assert set(queue["term_ids"]) == {
        terms[name].id for name in ["gatos", "gato", "animal", "perro", "un perro"]
    }
    assert len(queue["term_ids"]) == 5
    assert db.session.query(Term).count() == before_count
    db.session.refresh(book)
    assert book.current_tx_id == 0
    assert all(
        page.read_date is None and page.start_date is None and not page.sentences
        for page in book.texts
    )
    page = client.get(f"/read/{book.id}/page/2")
    document = BeautifulSoup(page.data, "html.parser")
    link = document.select_one("#trainBookTerms")
    assert link["href"] == f"/term/review?book_id={book.id}&page_num=2"
    assert link["target"] == "_blank"
    review_page = client.get(link["href"])
    assert f"/read/{book.id}/page/2".encode() in review_page.data
    assert b"My book" in review_page.data


def test_book_parent_statuses_are_filtered_independently(spanish):
    terms = save_terms(
        spanish,
        [("child", "child", 1), ("parent", "parent", 99), ("ignored", "ignored", 98)],
    )
    terms["child"].add_parent(terms["parent"])
    terms["child"].add_parent(terms["ignored"])
    book = make_book("Book", "child", spanish)
    db.session.add(book)
    db.session.commit()
    assert Service(db.session).from_book(book)["term_ids"] == [terms["child"].id]


def test_own_translation_wins_and_parent_meanings_are_labelled(spanish):
    terms = save_terms(
        spanish,
        [
            ("child", "own\nmeaning", 1),
            ("first", "first meaning", 1),
            ("second", "second meaning", 1),
        ],
    )
    terms["child"].add_parent(terms["second"])
    terms["child"].add_parent(terms["first"])
    db.session.commit()
    assert card_data(terms["child"])["meanings"] == [
        {"parent": None, "translation": "own\nmeaning"}
    ]
    terms["child"].translation = " \n "
    assert card_data(terms["child"])["meanings"] == [
        {"parent": "first", "translation": "first meaning"},
        {"parent": "second", "translation": "second meaning"},
    ]
    db.session.commit()
    assert Service(db.session).from_terms({}, [terms["child"].id]) == {
        "term_ids": [terms["child"].id],
        "untranslated": 0,
    }


def test_no_translation_is_counted_and_empty_queue_renders(client, spanish):
    terms = save_terms(
        spanish, [("empty", " \n ", 1), ("parent", "", 1), ("unknown", "", 0)]
    )
    terms["empty"].add_parent(terms["parent"])
    db.session.commit()
    queue = queue_from(
        client.post(
            "/term/review",
            data={"selected_ids": ",".join(str(term.id) for term in terms.values())},
        )
    )
    assert queue == {"term_ids": [], "untranslated": 2}


@pytest.mark.parametrize("value", ["abc", "-1", "0", "1,", "1); DROP TABLE words;--"])
def test_invalid_selections_are_rejected(client, value):
    assert client.post("/term/review", data={"selected_ids": value}).status_code == 400
    assert client.post("/term/review", data={"filtTermIDs": value}).status_code == 400


def test_missing_book_invalid_book_and_missing_card(client):
    assert client.get("/term/review?book_id=999999").status_code == 404
    assert client.get("/term/review?book_id=bad").status_code == 400
    assert client.get("/term/review/card/999999").status_code == 404


def test_live_card_has_safe_data_and_current_language_direction(client, spanish):
    terms = save_terms(spanish, [("gato", '<script>alert("test")</script>\ncat', 1)])
    spanish.right_to_left = True
    db.session.commit()
    term = terms["gato"]
    response = client.get(f"/term/review/card/{term.id}")
    assert response.json["direction"] == "rtl"
    assert response.json["meanings"][0]["translation"] == term.translation
    assert response.headers["Cache-Control"] == "no-store"
    page = client.post("/term/review", data={"selected_ids": str(term.id)})
    assert b'<script>alert("test")</script>' not in page.data
    term.translation = None
    db.session.commit()
    assert client.get(f"/term/review/card/{term.id}").status_code == 422
    term.status = 0
    db.session.commit()
    assert client.get(f"/term/review/card/{term.id}").status_code == 410


@pytest.mark.parametrize("status", [1, 2, 3, 4, 5, 98, 99])
def test_review_save_updates_synchronized_family_and_live_cards(
    client, spanish, status
):
    terms = save_terms(
        spanish, [("gatos", "cats", 2), ("gato", "cat", 2), ("gatitos", "kittens", 2)]
    )
    for name in ["gatos", "gatitos"]:
        terms[name].add_parent(terms["gato"])
        terms[name].sync_status = True
    db.session.commit()
    response = client.post(
        "/term/ajax_edit_from_index",
        json={"term_id": terms["gatos"].id, "update_type": "status", "values": status},
    )
    assert response.status_code == 200
    assert response.json["status"] == status
    db.session.expire_all()
    for term in terms.values():
        assert client.get(f"/term/review/card/{term.id}").json["status"] == status
