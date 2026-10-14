"""Codex is part of the term card; the reader has no dictionary tabs."""

import pytest
from lute.db import db
from tests.utils import make_book


@pytest.mark.parametrize("route", ["read/termform", "term/editbytext"])
def test_term_card_includes_codex_and_image_search(client, spanish, route):
    page = client.get(f"/{route}/{spanish.id}/gato").data
    for element_id in (b"codex-refresh", b"codex-options", b"term-image-btn"):
        assert b'id="' + element_id + b'"' in page
    assert b"dict-tabs.js" not in page


def test_reading_page_has_no_dictionary_tabs(client, spanish):
    book = make_book("Gatos", "Hola gato.", spanish)
    db.session.add(book)
    db.session.commit()
    page = client.get(f"/read/{book.id}").data
    assert b"wordframeid" in page
    assert b"dicttabs" not in page
    assert b"dictcontainer" not in page
