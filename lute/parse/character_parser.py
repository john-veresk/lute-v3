"""
Parsing for single-character languages.

The parser uses some Language settings (e.g., word characters) to
perform the actual parsing.

Includes classes:

- ClassicalChineseParser

"""

import re
from typing import List
from lute.parse.base import ParsedToken, AbstractParser, apply_character_substitutions


class ClassicalChineseParser(AbstractParser):
    """
    One character at a time, for Classical Chinese.
    """

    @classmethod
    def name(cls):
        return "Classical Chinese"

    def get_parsed_tokens(self, text: str, language) -> List[ParsedToken]:
        """
        Returns ParsedToken array for given language.
        """
        text = re.sub(r"[ \t]+", "", text)
        text = apply_character_substitutions(text, language.character_substitutions)
        text = text.replace("\n", "¶")
        text = text.strip()

        tokens = []
        pattern = f"[{language.word_characters}]"
        for char in text:
            is_word_char = re.match(pattern, char) is not None
            is_end_of_sentence = char in language.regexp_split_sentences
            if char == "¶":
                is_end_of_sentence = True
            p = ParsedToken(char, is_word_char, is_end_of_sentence)
            tokens.append(p)

        return tokens
