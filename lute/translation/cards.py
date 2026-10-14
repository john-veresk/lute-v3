"""Word and phrase cards suggested by Codex, saved into the vocabulary."""

from lute.models.term import Status


def _is_inflected_word(language, card, card_type):
    return (
        card_type == "words"
        and card["is_inflected"]
        and language.get_lowercase(card["lemma"])
        != language.get_lowercase(card["text"])
    )


def save_card(repo, language, card, card_type):
    """Add a card, preserving existing translations, parents and statuses.

    The caller commits the repository.
    """
    term = repo.find_or_new(language.id, card["text"])
    already_saved = term.id is not None and term.status != Status.UNKNOWN
    if not (term.translation or "").strip():
        term.translation = card["translation"]
    if term.status == Status.UNKNOWN:
        term.status = 1
    is_inflected = _is_inflected_word(language, card, card_type)
    if is_inflected and not term.parents:
        parent_term = repo.find(language.id, card["lemma"])
        term.parents = [card["lemma"]]
        if not already_saved:
            term.sync_status = True
            if parent_term is not None and parent_term.status != Status.UNKNOWN:
                term.status = parent_term.status
    if is_inflected:
        term.suggested_parent_text = card["lemma"]
        term.suggested_parent_translation = card["lemma_translation"]
    repo.add(term)
    return {
        "text": card["text"],
        "translation": term.translation,
        "already_saved": already_saved,
    }
