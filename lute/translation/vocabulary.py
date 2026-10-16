"""Read-only vocabulary lookup and local word-form checks, shared by CLI and jobs."""

import hashlib
import json
import threading
from functools import lru_cache
import simplemma
from lute.models.term import Term, wordparents

LEARNED = (5, 99)
LANGUAGES = {
    "finnish": "fi",
    "suomi": "fi",
    "english": "en",
    "spanish": "es",
    "swedish": "sv",
    "german": "de",
    "french": "fr",
    "russian": "ru",
    "italian": "it",
    "portuguese": "pt",
    "estonian": "et",
    "dutch": "nl",
}
# Conservative corrections for common irregular forms and a lexicalized adverb.
# Explicit vocabulary parents always take precedence over dictionary analysis.
FINNISH_FORMS = {
    "ollut": "olla",
    "olleet": "olla",
    "tehnyt": "tehdä",
    "tehneet": "tehdä",
    "nähnyt": "nähdä",
    "nähneet": "nähdä",
    "voinut": "voida",
    "voineet": "voida",
    "huusin": "huutaa",
    "huusi": "huutaa",
    "huusivat": "huutaa",
    "tarpeeksi": "tarpeeksi",
}
_MORPHOLOGY_LOCK = threading.RLock()


@lru_cache(maxsize=32768)
def lemma_for(text, code):
    """Offline dictionary analysis; never guess by stripping arbitrary suffixes."""
    if not code:
        return text
    if code == "fi" and text in FINNISH_FORMS:
        return FINNISH_FORMS[text]
    with _MORPHOLOGY_LOCK:
        return simplemma.lemmatize(text, lang=code).lower()


class Vocabulary:
    """One language's local index, including explicit parents and learning statuses."""

    def __init__(self, session, language):
        self.language = language
        self.code = LANGUAGES.get(language.name.casefold(), "")
        self.terms = {
            term_id: (self.normalize(text), status)
            for term_id, text, status in session.query(
                Term.id, Term.text_lc, Term.status
            ).filter(Term.language_id == language.id)
        }
        self.by_text = {text: term_id for term_id, (text, _) in self.terms.items()}
        self.parents = {}
        for child, parent in (
            session.query(wordparents)
            .join(Term, Term.id == wordparents.c.WpWoID)
            .filter(Term.language_id == language.id)
        ):
            if parent in self.terms:
                self.parents.setdefault(child, set()).add(parent)
        self._roots = {}
        self.known_roots = set()
        for term_id, (_, status) in self.terms.items():
            if status in LEARNED:
                self.known_roots.update(self.roots(term_id))
        self._known_lemmas = None

    def normalize(self, text):
        return self.language.get_lowercase(text.replace("\u200b", "").strip())

    def roots(self, term_id):
        """Follow all local parents, tolerating bad cycles and cross-language links."""
        if term_id in self._roots:
            return self._roots[term_id]
        pending, visited, roots = [term_id], set(), set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            if current in self.parents:
                pending.extend(self.parents[current])
            else:
                roots.add(current)
        if not roots:
            roots.add(min(visited, key=lambda item: self.terms[item][0]))
        self._roots[term_id] = roots
        return roots

    @property
    def revision(self):
        """A compact local fingerprint; no vocabulary contents belong in prompts."""
        data = [
            sorted(self.terms.items()),
            sorted((child, sorted(parents)) for child, parents in self.parents.items()),
        ]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()

    @property
    def known_lemmas(self):
        if self._known_lemmas is None:
            roots = [self.terms[item][0] for item in self.known_roots]
            self._known_lemmas = set(roots)
            self._known_lemmas.update(
                lemma_for(text, self.code) for text in roots if " " not in text
            )
        return self._known_lemmas

    def words(self, text):
        """Use the language's configured tokenizer and normalization."""
        return list(
            dict.fromkeys(
                self.normalize(token.token)
                for token in self.language.get_parsed_tokens(text)
                if token.is_word
            )
        )

    def lookup(self, texts):
        """Batch exact, parent-family and lemma lookup with an explanation of each match."""
        result = []
        for text in texts:
            normalized = self.normalize(text)
            term_id = self.by_text.get(normalized)
            status = self.terms[term_id][1] if term_id is not None else None
            roots = self.roots(term_id) if term_id is not None else set()
            root_texts = sorted(self.terms[item][0] for item in roots)
            lemma = (
                root_texts[0]
                if term_id in self.parents
                else lemma_for(normalized, self.code)
            )
            if status in LEARNED:
                known, via = True, "exact"
            elif roots & self.known_roots:
                known, via = True, "parent"
            elif status not in (None, 0):
                # Respect an explicitly unfamiliar, unlinked vocabulary entry.
                known, via = False, "status"
            elif normalized in self.known_lemmas or lemma in self.known_lemmas:
                known, via = True, "lemma"
            else:
                known, via = False, "missing"
            result.append(
                {
                    "text": normalized,
                    "lemma": lemma,
                    "known": known,
                    "status": status,
                    "via": via,
                    "parents": root_texts if term_id in self.parents else [],
                    "ignored": status == 98,
                }
            )
        return result

    def check(self, text, exclude=()):
        """Classify every distinct word; excluded learning targets are not new obstacles."""
        excluded = {self.normalize(word) for word in exclude}
        excluded.update(lemma_for(word, self.code) for word in list(excluded))
        report = {"known": [], "unknown": [], "ignored": []}
        for entry in self.lookup(self.words(text)):
            if (
                entry["ignored"]
                or entry["text"] in excluded
                or entry["lemma"] in excluded
            ):
                bucket = "ignored"
            else:
                bucket = "known" if entry["known"] else "unknown"
            report[bucket].append(entry)
        return report

    def search(self, query, limit=20):
        """Literal substring search; returns statuses, parents and knowledge matches."""
        query = self.normalize(query)
        matches = sorted(text for text in self.by_text if query in text)
        return self.lookup(matches[: max(1, min(limit, 100))])
