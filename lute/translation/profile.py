"""Cache identity for ordinary translations into a target language."""


def cache_profile(source, target):
    """Keep translations into different target languages separate."""
    return f"translation:{len(source)}:{source}{target}"


def profile_for(_session, language):
    """Current source and target language identity."""
    return cache_profile(language.name, language.translation_target)


def profile_from_key(key):
    """Use submitted settings even if they change during translation."""
    return cache_profile(key[0], key[1])
