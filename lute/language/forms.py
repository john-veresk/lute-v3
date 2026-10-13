"""
Flask-wtf forms.
"""

from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    IntegerField,
    BooleanField,
    SelectField,
    FormField,
    FieldList,
    Form,
    ValidationError,
)
from wtforms.validators import DataRequired, Length, Optional, Regexp
from lute.models.language import LanguageDictionary


class LanguageDictionaryForm(Form):
    """
    Language dictionary form, nested in Language form.
    """

    usefor = SelectField(
        choices=[("terms", "Terms"), ("sentences", "Sentences")],
        render_kw={"title": "Use dictionary for"},
    )
    dicttype = SelectField(
        choices=[
            ("embeddedhtml", "Embedded"),
            ("popuphtml", "Pop-up window"),
        ],
        render_kw={"title": "Show as"},
    )
    dicturi = StringField("URL", validators=[DataRequired()])
    is_active = BooleanField("Is active", render_kw={"title": "Is active?"})
    sort_order = IntegerField("Sort", render_kw={"style": "display: none"})


class LanguageForm(FlaskForm):
    """
    Language.
    """

    name = StringField("Name", validators=[DataRequired()])
    translation_provider = SelectField(
        "Translation source",
        choices=[
            ("dictionaries", "Dictionary websites"),
            ("codex", "Codex CLI translation"),
        ],
        default="dictionaries",
    )
    translation_target = StringField(
        "Translate into", default="Russian", validators=[Length(max=80)]
    )
    codex_model = StringField(
        "Codex model",
        default="",
        validators=[
            Optional(),
            Length(max=100),
            Regexp(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$", message="Enter a valid model ID"),
        ],
    )
    dictionaries = FieldList(
        FormField(LanguageDictionaryForm, default=LanguageDictionary)
    )
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

    def validate_dictionaries(self, field):  # pylint: disable=unused-argument
        "Dictionaries must be valid."
        if self.translation_provider.data == "codex":
            return

        # raise ValueError(self.dictionaries.data) # debugging
        def _get_actives(usefor):
            "Return dictionaries."
            return [
                d
                for d in self.dictionaries.data
                if d.get("usefor", "") == usefor and d.get("is_active")
            ]

        term_dicts = _get_actives("terms")
        sentence_dicts = _get_actives("sentences")
        if len(term_dicts) == 0:
            raise ValidationError("Please add an active Terms dictionary")
        if len(sentence_dicts) == 0:
            raise ValidationError("Please add an active Sentences dictionary")

    def validate_translation_target(self, field):
        "Codex needs a target language."
        if self.translation_provider.data == "codex" and not (field.data or "").strip():
            raise ValidationError("Please enter a translation language")
