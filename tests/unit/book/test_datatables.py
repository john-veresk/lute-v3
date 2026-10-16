"""
Book tests.
"""

from datetime import datetime
import pytest
from lute.models.language import Language
from lute.models.book import BookTag
from lute.book.datatables import get_data_tables_list
from lute.db import db
from lute.db.demo import Service as DemoService
from tests.utils import make_book


@pytest.fixture(name="_dt_params")
def fixture_dt_params():
    "Sample query params."
    columns = [
        {"data": "0", "name": "BkID", "searchable": False, "orderable": False},
        {"data": "1", "name": "BkTitle", "searchable": True, "orderable": True},
        {"data": "2", "name": "IsCompleted", "searchable": False, "orderable": False},
    ]
    params = {
        "draw": "1",
        "columns": columns,
        "order": [{"column": "1", "dir": "asc"}],
        "start": "0",  # Start from page 0
        "length": "10",
        "search": {"value": "", "regex": False},
        "filtLanguage": "0",  # Ha!
    }
    return params


def test_smoke_book_datatables_query_runs(app_context, _dt_params):
    """
    Smoke test only, ensure query runs.
    """
    demosvc = DemoService(db.session)
    demosvc.load_demo_data()
    get_data_tables_list(_dt_params, False, db.session)
    # print(d['data'])
    a = 1
    assert a == 1, "dummy check"


def test_book_query_only_returns_supported_language_books(app_context, _dt_params):
    """
    Smoke test only, ensure query runs.
    """
    demosvc = DemoService(db.session)
    demosvc.load_demo_data()
    for lang in db.session.query(Language).all():
        lang.parser_type = "unknown"
        db.session.add(lang)
    db.session.commit()
    d = get_data_tables_list(_dt_params, False, db.session)
    assert len(d["data"]) == 0, "no books should be active"


def test_book_data_says_completed_if_last_page_has_been_read(
    app_context, _dt_params, english
):
    "Add a visual cue to completed books."
    b = make_book("title", "Hello.", english)
    db.session.add(b)
    db.session.commit()
    _dt_params["search"] = {"value": "title", "regex": False}
    d = get_data_tables_list(_dt_params, False, db.session)
    actual = d["data"][0]
    assert actual["BkID"] == b.id, "correct book"
    assert actual["IsCompleted"] == 0, "not completed"
    t = b.texts[0]
    t.read_date = datetime.now()
    db.session.add(t)
    db.session.commit()
    d = get_data_tables_list(_dt_params, False, db.session)
    actual = d["data"][0]
    assert actual["BkID"] == b.id, "correct book"
    assert actual["IsCompleted"] == 1, "completed"


def _make_tagged_book(title, tags, language):
    "Book with the given BookTags."
    b = make_book(title, "Hello.", language)
    for t in tags:
        b.add_book_tag(t)
    db.session.add(b)
    return b


def _listed_titles(params):
    return [
        row["BkTitle"]
        for row in get_data_tables_list(params, False, db.session)["data"]
    ]


def test_tag_filter_lists_books_having_all_selected_tags(
    app_context, _dt_params, english
):
    "Selecting several tags narrows the listing."
    news = BookTag.make_book_tag("news")
    easy = BookTag.make_book_tag("easy")
    _make_tagged_book("both", [news, easy], english)
    _make_tagged_book("only news", [news], english)
    _make_tagged_book("untagged", [], english)
    db.session.commit()

    _dt_params["filtTagIDs"] = ""
    assert {"both", "only news", "untagged"} <= set(_listed_titles(_dt_params))

    _dt_params["filtTagIDs"] = f"{news.id}"
    assert _listed_titles(_dt_params) == ["both", "only news"]

    _dt_params["filtTagIDs"] = f"{news.id},{easy.id}"
    assert _listed_titles(_dt_params) == ["both"]
