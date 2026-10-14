"""The book to continue reading."""

from lute.models.book import Book, Text


def last_read_book(session):
    "The active book with the most recently opened page, or None."
    text = (
        session.query(Text)
        .join(Book)
        .filter(Book.archived.is_(False), Text.start_date.isnot(None))
        .order_by(Text.start_date.desc())
        .first()
    )
    if text is None or not text.book.is_supported:
        return None
    book = text.book
    current = session.get(Text, book.current_tx_id) if book.current_tx_id else None
    return {
        "id": book.id,
        "title": book.title,
        "language": book.language.name,
        "page_num": current.order if current else text.order,
        "page_count": book.page_count,
    }
