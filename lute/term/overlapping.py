"""Saved phrases that overlap the phrase open in the term card."""

from lute.models.term import Status, Term as DBTerm

ZWS = "\u200b"


def word_tokens(text_lc):
    "Lowercase term text stores every token, including spaces, between zero-width spaces."
    return [part for part in (text_lc or "").split(ZWS) if part.strip()]


def _contains(haystack, needle):
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(
        haystack[index : index + width] == needle
        for index in range(len(haystack) - width + 1)
    )


def sequences_overlap(current, other):
    "One phrase sits inside the other, or they continue across each other's edge."
    if _contains(current, other) or _contains(other, current):
        return True
    limit = min(len(current), len(other))
    return any(
        current[-length:] == other[:length] or other[-length:] == current[:length]
        for length in range(1, limit + 1)
    )


def _overlap_index(current, other):
    "Where the other phrase first meets this one, for reading order."
    if _contains(current, other):
        width = len(other)
        for index in range(len(current) - width + 1):
            if current[index : index + width] == other:
                return index
    if _contains(other, current):
        return 0
    for length in range(min(len(current), len(other)), 0, -1):
        if current[:length] == other[-length:]:
            return 0
        if current[-length:] == other[:length]:
            return len(current) - length
    return 0


def _edit_url(term_id, embedded):
    if embedded:
        return f"/read/edit_term/{term_id}"
    return f"/term/edit/{term_id}"


class OverlappingPhrase:
    "A saved phrase the open card can jump to."

    def __init__(self, text, translation, url, position, length):
        self.text = text
        self.translation = translation
        self.url = url
        self.position = position
        self.length = length


def overlapping_phrases(current_text_lc, phrases, embedded):
    "Phrases whose words overlap this one. A single word has no inner phrases."
    current = word_tokens(current_text_lc)
    if len(current) < 2:
        return []
    matches = []
    for phrase in phrases:
        words = word_tokens(phrase["text_lc"])
        if len(words) < 2 or words == current or not sequences_overlap(current, words):
            continue
        matches.append(
            OverlappingPhrase(
                phrase["text"].replace(ZWS, ""),
                phrase.get("translation") or "",
                _edit_url(phrase["id"], embedded),
                _overlap_index(current, words),
                len(words),
            )
        )
    matches.sort(key=lambda phrase: (phrase.position, -phrase.length, phrase.text))
    return matches


def load_overlapping_phrases(session, language, text_lc, embedded):
    "Saved multiword terms in this language that overlap the open phrase."
    if language is None or len(word_tokens(text_lc)) < 2:
        return []
    rows = (
        session.query(DBTerm)
        .filter(
            DBTerm.language_id == language.id,
            DBTerm.token_count > 1,
            DBTerm.status != Status.UNKNOWN,
        )
        .all()
    )
    phrases = [
        {
            "id": row.id,
            "text": row.text,
            "text_lc": row.text_lc,
            "translation": row.translation,
        }
        for row in rows
    ]
    return overlapping_phrases(text_lc, phrases, embedded)
