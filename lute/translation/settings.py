"""Validate partial CLI/model updates shared by language and book job APIs."""

import re
from lute.translation.service import REASONING_EFFORTS, available_model_efforts


def updated_settings(current, data):
    """Return validated settings without changing unrelated snapshot fields."""
    if not isinstance(data, dict) or not data:
        raise ValueError("Expected a non-empty JSON object")
    if data.keys() - {"cli", "model", "effort"}:
        raise ValueError("Allowed fields: cli, model, effort")
    result = {**current, **data}
    if result["cli"] not in ("codex", "cursor"):
        raise ValueError("CLI must be codex or cursor")
    model = result["model"]
    if (
        not isinstance(model, str)
        or len(model) > 100
        or (model and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]*", model))
    ):
        raise ValueError("Enter a valid model ID (up to 100 characters)")
    effort = result["effort"]
    if not isinstance(effort, str) or effort not in ("", *REASONING_EFFORTS):
        raise ValueError("Invalid reasoning effort")
    if result["cli"] == "cursor":
        if data.get("effort"):
            raise ValueError("For Cursor, choose reasoning effort in the model ID")
        result["effort"] = ""
    elif effort:
        supported = available_model_efforts().get(model)
        if supported and effort not in supported:
            raise ValueError(
                "This model does not support the selected reasoning effort"
            )
    return result


def language_cli_settings(language):
    """Effective translation options; Cursor encodes effort in its model ID."""
    return {
        "cli": language.translation_cli or "codex",
        "model": language.codex_model or "",
        "effort": language.translation_reasoning_effort or "",
    }
