"""The book a reader returns to from the library."""

from datetime import datetime, timedelta
from lute.db import db
from lute.book.recent import last_read_book
from tests.utils import make_book


def _opened(book, pagenum, minutes_ago):
    text = book.texts[pagenum - 1]
    text.start_date = datetime.now() - timedelta(minutes=minutes_ago)
    book.current_tx_id = text.id


def test_no_opened_book(app_context, spanish):
    db.session.add(make_book("Unread", "Hola.", spanish))
    db.session.commit()
    assert last_read_book(db.session) is None


def test_most_recently_opened_active_book_and_its_current_page(app_context, spanish):
    older = make_book("Older", ["Uno.", "Dos."], spanish)
    newer = make_book("Newer", ["Uno.", "Dos.", "Tres."], spanish)
    archived = make_book("Archived", "Uno.", spanish)
    archived.archived = True
    db.session.add_all([older, newer, archived])
    db.session.commit()
    _opened(older, 1, 30)
    _opened(newer, 2, 10)
    _opened(archived, 1, 1)
    db.session.commit()

    assert last_read_book(db.session) == {
        "id": newer.id,
        "title": "Newer",
        "language": spanish.name,
        "page_num": 2,
        "page_count": 3,
    }
