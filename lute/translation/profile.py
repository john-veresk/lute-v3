"""Personal output vocabulary and the identity of a translation's audience."""

from lute.translation.vocabulary import Vocabulary


def known_words(session, language):
    """Represent learned forms by their root parents, without changing statuses."""
    vocabulary = Vocabulary(session, language)
    return tuple(sorted(vocabulary.terms[item][0] for item in vocabulary.known_roots))


def vocabulary_for(session, language, mode=None):
    """Only a compact local revision enters job keys; never send the word list."""
    return (
        Vocabulary(session, language).revision
        if (mode or language.translation_mode) == "personal"
        else ""
    )


def cache_profile(source, target, mode="translation"):
    """Dictionary identity is independent of a sentence and the learner's progress."""
    if mode != "personal":
        return f"translation:{len(source)}:{source}{target}"
    return f"personal:{len(source)}:{source}"


def profile_for(_session, language):
    """Current dictionary output identity; fallback languages have their own rows."""
    return cache_profile(
        language.name,
        language.translation_target_name,
        language.translation_mode,
    )


def profile_from_key(key):
    """Use the submitted profile even if settings change during CLI work."""
    return cache_profile(
        key[0],
        key[1],
        key[11] if len(key) > 11 else "translation",
    )
