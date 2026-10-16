"""
Book tag routes used by the book listing.
"""

from lute.db import db
from lute.book.model import Repository
from tests.utils import make_book


def _saved_book(language):
    b = make_book("Tagged", "Hello.", language)
    db.session.add(b)
    db.session.commit()
    return b


def test_set_tags_replaces_book_tags(client, english):
    b = _saved_book(english)
    response = client.post(f"/book/{b.id}/tags", json={"tags": ["news", " easy ", ""]})
    assert response.status_code == 200
    assert response.get_json() == {"tags": ["easy", "news"]}
    assert Repository(db.session).load(b.id).book_tags == ["easy", "news"]

    client.post(f"/book/{b.id}/tags", json={"tags": ["easy", "easy"]})
    assert Repository(db.session).load(b.id).book_tags == ["easy"]


def test_set_tags_for_missing_book_is_404(client, english):
    assert client.post("/book/999999/tags", json={"tags": []}).status_code == 404


def test_tag_counts(client, english):
    b = _saved_book(english)
    client.post(f"/book/{b.id}/tags", json={"tags": ["news"]})
    response = client.get(f"/book/tag_counts?archived=0&language_id={english.id}")
    news = [t for t in response.get_json() if t["text"] == "news"]
    assert [(t["text"], t["count"]) for t in news] == [("news", 1)]
