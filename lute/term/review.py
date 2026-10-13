"""Build transient review queues from saved terms or an entire book."""

from sqlalchemy.orm import selectinload
from lute.models.term import Term, Status
from lute.read.render.service import Service as RenderService
from lute.term.datatables import get_data_tables_list


def parse_ids(value):
    """Accept only comma-separated positive term IDs."""
    if not value or not value.strip():
        return []
    ids = [int(part.strip()) for part in value.split(",")]
    if any(term_id <= 0 for term_id in ids):
        raise ValueError("Term IDs must be positive integers")
    return list(dict.fromkeys(ids))


def card_data(term):
    """Use the term's meaning, falling back to labelled parent meanings."""
    translation = (term.translation or "").strip()
    meanings = []
    if translation:
        meanings.append({"parent": None, "translation": translation})
    else:
        for parent in sorted(term.parents, key=lambda item: item.text):
            translation = (parent.translation or "").strip()
            if translation:
                meanings.append({"parent": parent.text, "translation": translation})
    return {
        "id": term.id,
        "text": term.text,
        "language": term.language.name,
        "direction": "rtl" if term.language.right_to_left else "ltr",
        "status": term.status,
        "meanings": meanings,
    }


class Service:
    """Select queues without creating terms or modifying reading progress."""

    def __init__(self, session):
        self.session = session

    def _terms(self, ids):
        return (
            self.session.query(Term)
            .filter(Term.id.in_(ids))
            .options(selectinload(Term.parents), selectinload(Term.language))
            .all()
        )

    @staticmethod
    def _queue(terms):
        ids = []
        untranslated = 0
        for term in terms:
            if term.status == Status.UNKNOWN or not term.language.is_supported:
                continue
            if not card_data(term)["meanings"]:
                untranslated += 1
                continue
            ids.append(term.id)
        return {"term_ids": ids, "untranslated": untranslated}

    def from_terms(self, parameters, selected_ids):
        """Review exact selections, or every matching row irrespective of paging."""
        if selected_ids:
            return self._queue(self._terms(selected_ids))

        parameters = dict(parameters, start=0, length=-1)
        # Use the same searchable columns as Terms, with trusted SQL names.
        fields = [
            "WoText",
            "ParentText",
            "WoTranslation",
            "TagList",
            "StID",
            "LgName",
            "WoCreated",
            "WoID",
            "LgID",
        ]
        parameters["columns"] = [
            {"name": name, "searchable": True, "orderable": True} for name in fields
        ]
        parameters["order"] = []
        # The reading pane filter includes direct parents. Normalize its IDs
        # before handing it to the existing SQL selection logic.
        parameters["filtTermIDs"] = ",".join(
            str(term_id) for term_id in parse_ids(parameters.get("filtTermIDs", ""))
        )
        rows = get_data_tables_list(parameters, self.session)["data"]
        ids = {row["WoID"] for row in rows}
        return self._queue(self._terms(ids))

    def from_book(self, book):
        """Find forms and their direct parents across all pages, including unread."""
        renderer = RenderService(self.session)
        indexer = renderer.get_multiword_indexer(book.language)
        ids = set()
        for page in book.texts:
            terms = renderer.find_all_Terms_in_string(page.text, book.language, indexer)
            ids.update(term.id for term in terms)
        # Load parent relationships together rather than querying each word.
        found = self._terms(ids)
        ids.update(parent.id for term in found for parent in term.parents)
        terms = [
            term
            for term in self._terms(ids)
            if term.language_id == book.language_id and 1 <= term.status <= 5
        ]
        return self._queue(terms)
