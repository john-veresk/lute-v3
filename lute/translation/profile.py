"""Personal output vocabulary and the identity of a translation's audience."""

import hashlib
import json
from lute.models.term import Term, wordparents


def known_words(session, language):
    """Represent learned forms by their root parents, without changing statuses."""
    terms = {
        term_id: (text.replace("\u200b", ""), status)
        for term_id, text, status in session.query(
            Term.id, Term.text_lc, Term.status
        ).filter(Term.language_id == language.id)
    }
    parents = {}
    for child, parent in (
        session.query(wordparents)
        .join(Term, Term.id == wordparents.c.WpWoID)
        .filter(Term.language_id == language.id)
    ):
        if parent in terms:
            parents.setdefault(child, set()).add(parent)
    vocabulary = set()
    for term_id, (_, status) in terms.items():
        if status not in (5, 99):
            continue
        pending = [term_id]
        visited = set()
        roots = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            if current in parents:
                pending.extend(parents[current])
            else:
                roots.add(current)
        # Bad cyclic links must not hang requests or lose the entire family.
        if not roots:
            roots.add(min(visited, key=lambda item: terms[item][0]))
        vocabulary.update(terms[root][0] for root in roots)
    return tuple(sorted(vocabulary))


def vocabulary_for(session, language):
    """Only personal output needs the reader's vocabulary in its prompt."""
    return (
        known_words(session, language)
        if language.translation_mode == "personal"
        else ()
    )


def cache_profile(source, target, mode="translation", vocabulary=()):
    """Separate ordinary translations from explanations for a particular reader."""
    if mode != "personal":
        return f"translation:{len(source)}:{source}{target}"
    payload = json.dumps([source, target, vocabulary], ensure_ascii=False)
    return "personal:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def profile_for(session, language):
    """Current output identity, including vocabulary changes in personal mode."""
    return cache_profile(
        language.name,
        language.translation_target_name,
        language.translation_mode,
        vocabulary_for(session, language),
    )


def profile_from_key(key):
    """Use the submitted profile even if settings change during CLI work."""
    return cache_profile(
        key[0],
        key[1],
        key[11] if len(key) > 11 else "translation",
        key[12] if len(key) > 12 else (),
    )
