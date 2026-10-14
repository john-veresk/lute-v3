"""Overlapping phrases listed under Words in the term card."""

from urllib.parse import quote

from lute.db import db
from lute.models.term import Term as DBTerm
from lute.term.overlapping import overlapping_phrases


def _phrase(term_id, text_lc, text=None, translation=""):
    return {
        "id": term_id,
        "text": text or text_lc,
        "text_lc": text_lc,
        "translation": translation,
    }


def _tokens(text):
    return "\u200b \u200b".join(text.split(" "))


CURRENT = _tokens("some data here")


def test_inner_and_edge_phrases_follow_the_open_phrase():
    "A phrase inside this one, and one that runs past it, are both listed."
    phrases = [
        _phrase(2, _tokens("data here"), translation="данные здесь"),
        _phrase(3, _tokens("data here now"), "data here now", "данные здесь сейчас"),
        _phrase(4, _tokens("some data"), translation="некоторые данные"),
        _phrase(5, _tokens("good night"), translation="спокойной ночи"),
        _phrase(6, CURRENT, "some data here"),
    ]
    listed = overlapping_phrases(CURRENT, phrases, embedded=True)
    assert [phrase.text for phrase in listed] == ["some data", "data here now", "data here"]
    assert [phrase.url for phrase in listed] == [
        "/read/edit_term/4",
        "/read/edit_term/3",
        "/read/edit_term/2",
    ]
    assert listed[2].translation == "данные здесь"


def test_single_word_and_standalone_form_have_no_inner_list():
    "The section belongs to a phrase, and the term page edits by id."
    assert overlapping_phrases(_tokens("data"), [_phrase(1, _tokens("data here"))], True) == []
    listed = overlapping_phrases(CURRENT, [_phrase(2, _tokens("data here"))], embedded=False)
    assert listed[0].url == "/term/edit/2"


def test_term_card_renders_overlapping_phrases(client, empty_db, english):
    "The open phrase card lists the saved phrases that overlap it."
    outer = DBTerm(english, "some data here")
    outer.status = 2
    inner = DBTerm(english, "data here")
    inner.status = 3
    inner.translation = "данные здесь"
    ahead = DBTerm(english, "data here now")
    ahead.status = 1
    elsewhere = DBTerm(english, "good night")
    elsewhere.status = 1
    unknown = DBTerm(english, "some data")
    unknown.status = 0
    db.session.add_all([outer, inner, ahead, elsewhere, unknown])
    db.session.commit()

    response = client.get(f"/read/termform/{english.id}/{quote('some data here')}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Overlapping phrases" in html
    assert html.index(f"/read/edit_term/{ahead.id}") < html.index(f"/read/edit_term/{inner.id}")
    assert "данные здесь" in html
    assert "good night" not in html
    assert f"/read/edit_term/{unknown.id}" not in html
    assert f"/read/edit_term/{outer.id}" not in html
