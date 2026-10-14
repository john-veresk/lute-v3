"""
Reading rendering helpers.
"""

import itertools
import re
from sqlalchemy import text as sqltext
from sqlalchemy.orm import joinedload

from lute.models.term import Term
from lute.parse.base import ParsedToken
from lute.read.render.calculate_textitems import get_textitems as calc_get_textitems
from lute.read.render.multiword_indexer import MultiwordTermIndexer


class Service:
    "Service."

    def __init__(self, session):
        self.session = session

    def find_all_Terms_in_string(self, s, language, multiword_term_indexer=None):
        """
        Find all terms contained in the string s.

        For example
        - given s = "Here is a cat"
        - given terms in the db: [ "cat", "a cat", "dog" ]

        This would return the terms "cat" and "a cat".
        """
        cleaned = re.sub(r" +", " ", s)
        tokens = language.get_parsed_tokens(cleaned)
        return self._find_all_terms_in_tokens(tokens, language, multiword_term_indexer)

    def _get_multiword_terms(self, language):
        "Get all multiword terms."
        sql = sqltext("""
            SELECT WoID, WoTextLC FROM words
            WHERE WoLgID=:language_id and WoTokenCount>1
            """)
        sql = sql.bindparams(language_id=language.id)
        return self.session.execute(sql).all()

    def _find_all_multi_word_term_text_lcs_in_content(self, text_lcs, language):
        "Find multiword terms, return list of text_lcs."

        # Loading each multiword text_lc and testing containment was as fast
        # as a model query or a LIKE, and the code is the clearest of the three.
        zws = "\u200b"  # zero-width space
        content = zws + zws.join(text_lcs) + zws
        reclist = self._get_multiword_terms(language)
        return [p[1] for p in reclist if f"{zws}{p[1]}{zws}" in content]

    def _find_all_terms_in_tokens(self, tokens, language, kwtree=None):
        """
        Find all terms contained in the (ordered) parsed tokens tokens.

        For example
        - given tokens = "Here", " ", "is", " ", "a", " ", "cat"
        - given terms in the db: [ "cat", "a/ /cat", "dog" ]

        This would return the terms "cat" and "a/ /cat".

        Method:
        - build list of lowercase text in the tokens
        - append all multword term strings that exist in the content
        - query for Terms that exist in the list

        Note: this method only uses indexes for multiword terms, as any
        content analyzed is first parsed into tokens before being passed
        to this routine.  There's no need to search for single-word Terms
        in the tokenized strings, they can be found by a simple query.
        """

        parser = language.parser
        text_lcs = [parser.get_lowercase(t.token) for t in tokens]

        # A single token cannot contain a term whose text has an internal
        # zero-width space, so the multiword scan only runs for longer strings.
        mword_terms = []
        if len(tokens) >= 2:
            if kwtree is None:
                mword_terms = self._find_all_multi_word_term_text_lcs_in_content(
                    text_lcs, language
                )
            else:
                mword_terms = [r[0] for r in kwtree.search_all(text_lcs)]

        text_lcs.extend(mword_terms)
        tok_strings = list(set(text_lcs))
        terms_matching_tokens_qry = (
            self.session.query(Term)
            .options(joinedload(Term.language))
            .filter(Term.text_lc.in_(tok_strings), Term.language == language)
        )
        return terms_matching_tokens_qry.all()

    def get_textitems(self, s, language, multiword_term_indexer=None):
        """
        Get array of TextItems for the string s.

        The multiword_term_indexer is a big performance boost, but takes
        time to initialize.
        """
        # Hacky reset of state of ParsedToken state.
        # _Shouldn't_ be needed but doesn't hurt, even if it's lame.
        ParsedToken.reset_counters()

        cleaned = re.sub(r" +", " ", s)
        tokens = language.get_parsed_tokens(cleaned)
        terms = self._find_all_terms_in_tokens(tokens, language, multiword_term_indexer)
        textitems = calc_get_textitems(tokens, terms, language, multiword_term_indexer)
        return textitems

    def get_multiword_indexer(self, language):
        "Return indexer loaded with all multiword terms."
        mw = MultiwordTermIndexer()
        for r in self._get_multiword_terms(language):
            mw.add(r[1])
        return mw

    def get_paragraphs(self, s, language):
        """
        Get array of arrays of TextItems for the given string s.

        This doesn't use an indexer, as it should only be used
        for a single page of text!
        """
        textitems = self.get_textitems(s, language)

        def _split_textitems_by_paragraph(textitems):
            "Split by ¶"
            ret = []
            curr_para = []
            for t in textitems:
                if t.text == "¶":
                    ret.append(curr_para)
                    curr_para = []
                else:
                    curr_para.append(t)
            if len(curr_para) > 0:
                ret.append(curr_para)
            return ret

        def _split_by_sentence_number(p):
            sentences = [
                list(sentence)
                for _, sentence in itertools.groupby(p, key=lambda t: t.sentence_number)
            ]
            for s in sentences:
                s[0].add_html_class("sentencestart")
            return sentences

        paras = [
            _split_by_sentence_number(list(sentences))
            for sentences in _split_textitems_by_paragraph(textitems)
        ]

        return paras
