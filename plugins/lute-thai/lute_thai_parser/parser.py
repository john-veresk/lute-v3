"""
Parsing using pythainlp

Includes classes:

- ThaiParser

"""

import re
import pythainlp

from typing import List

from lute.parse.base import ParsedToken, AbstractParser


class ThaiParser(AbstractParser):
    """
    A parser for Thai that uses the pythainlp library for text segmentation.

    The user can add some exceptions to the "parsing_exceptions.txt"
    data file.
    """

    @classmethod
    def name(cls):
        return "Lute Thai"

    def get_parsed_tokens(self, text: str, language) -> List[ParsedToken]:
        """
        Returns ParsedToken array for given language.
        """
        text = text.replace("\r\n", "\n")

        words = pythainlp.word_tokenize(text)
        tokens = []
        pattern = f"[{language.word_characters}]"
        whitespace_regex = r"[ \t]+"
        for word in words:
            is_word_char = re.match(pattern, word) is not None
            is_whitespace = re.match(whitespace_regex, word) is not None
            is_split_sentence = word in language.regexp_split_sentences
            is_end_of_sentence = is_split_sentence or is_whitespace
            if is_end_of_sentence:
                is_word_char = False
            if word == "\n":
                word = "¶"
            if word == "¶":
                is_word_char = False
                is_end_of_sentence = True
            t = ParsedToken(word, is_word_char, is_end_of_sentence)
            tokens.append(t)
        return tokens
