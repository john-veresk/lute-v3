"""One local vocabulary check and at most one additional generation."""

from lute.db import db
from lute.models.language import Language
from lute.translation.vocabulary import Vocabulary


def explanation_text(result):
    """Check generated explanations and examples, not copied source labels."""
    parts = [result.get("lemma_translation", "")]
    for option in result.get("options", []) + result.get("lemma_options", []):
        parts.extend((option.get("translation", ""), option.get("explanation", "")))
    for card in result.get("words", []) + result.get("phrases", []):
        parts.extend((card.get("translation", ""), card.get("lemma_translation", "")))
    return "\n".join(parts)


def check_result(app, language_id, key, result):
    """Close the database context before any CLI request or wait."""
    with app.app_context():
        language = db.session.get(Language, language_id)
        if language is None:
            return None
        vocabulary = Vocabulary(db.session, language)
        excluded = []
        if key[5] == "term":
            excluded = vocabulary.words(key[3]) + [result.get("lemma", "")]
            for word in result.get("words", []):
                excluded.extend((word["text"], word.get("lemma", "")))
        return vocabulary.check(explanation_text(result), excluded)


def check_and_revise(app, language_id, key, result, generate):
    """Accept the second valid answer even if unfamiliar words remain; never loop."""
    report = check_result(app, language_id, key, result)
    revised = False
    if report and report["unknown"]:
        feedback = {
            "previous_result": result,
            "unfamiliar_words": [
                {"text": entry["text"], "lemma": entry["lemma"]}
                for entry in report["unknown"]
            ],
            "familiar_words": sorted({entry["lemma"] for entry in report["known"]}),
        }
        result = generate(*(key + (feedback,)))
        revised = True
        report = check_result(app, language_id, key, result)
    if report is not None:
        result = {**result, "vocabulary": {**report, "revised": revised}}
    return result
