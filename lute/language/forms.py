"""
Flask-wtf forms.
"""

from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    BooleanField,
    SelectField,
    ValidationError,
)
from wtforms.validators import DataRequired, Length, Optional, Regexp
from lute.translation.service import (
    REASONING_EFFORTS,
    available_cursor_models,
    available_model_efforts,
    cursor_model_efforts,
)


class TranslationCliField(SelectField):
    """Missing values stay on Codex CLI; an unknown CLI is still rejected."""

    def process_formdata(self, valuelist):
        if not valuelist or valuelist[0] in ("", None):
            self.data = "codex"
            return
        super().process_formdata(valuelist)


class LanguageForm(FlaskForm):
    """
    Language.
    """

    name = StringField("Name", validators=[DataRequired()])
    translation_target = StringField(
        "Translate into", default="Russian", validators=[Length(max=80)]
    )
    translation_cli = TranslationCliField(
        "Translation CLI",
        choices=[("codex", "Codex CLI"), ("cursor", "Cursor Agent")],
        default="codex",
    )
    codex_model = StringField(
        "Model",
        default="",
        validators=[
            Optional(),
            Length(max=100),
            Regexp(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$", message="Enter a valid model ID"),
        ],
    )
    codex_reasoning_effort = SelectField(
        "Reasoning effort",
        choices=[("", "Default from the selected CLI")]
        + [(effort, effort) for effort in REASONING_EFFORTS],
        default="",
    )
    codex_fast_mode = BooleanField("Fast mode", default=False)
    codex_show_timer = BooleanField("Show translation timer", default=True)
    show_romanization = BooleanField("Show Pronunciation field")
    right_to_left = BooleanField("Right-to-left")

    # Note!  The choices have to be set in the routes!
    # I originally had "choices=lute.parse.registry.supported_parsers()",
    # but it never worked: the Japanese mecab parser was excluded.
    # Possible coder error, not sure, but setting the choices at
    # form creation time works.
    parser_type = SelectField("Parse as", choices=[("tbd", "tbd")])

    character_substitutions = StringField("Character substitutions")

    regexp_split_sentences = StringField(
        "Split sentences at (default: all Unicode sentence terminators)"
    )
    exceptions_split_sentences = StringField("Split sentence exceptions")
    word_characters = StringField(
        "Word characters (default: all Unicode letters and marks)"
    )

    def validate_translation_target(self, field):
        "Codex needs a target language."
        if not (field.data or "").strip():
            raise ValidationError("Please enter a translation language")

    def validate_codex_reasoning_effort(self, field):
        "Reject explicit levels the selected model does not offer."
        if not field.data:
            return
        if self.translation_cli.data == "cursor":
            info = cursor_model_efforts(available_cursor_models()).get(
                self.codex_model.data
            )
            supported = info["efforts"] if info else None
        else:
            supported = available_model_efforts().get(self.codex_model.data)
        if supported and field.data not in supported:
            raise ValidationError(
                "This model does not support the selected reasoning effort"
            )
