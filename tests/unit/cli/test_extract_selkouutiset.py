"""Standalone extraction tests, independent of Lute's database fixtures."""

import csv
from datetime import date

import pytest

from scripts.extract_selkouutiset import (
    article_url,
    extract_broadcast,
    find_broadcast_url,
    latest_broadcast_date,
    main,
    save_broadcast,
)

DAY = date(2026, 10, 15)
URL = "https://yle.fi/a/74-12345678"
# Synthetic content: do not store a copyrighted broadcast as a test fixture.
HTML = """
<nav><h1>Yle</h1><p>Menu</p></nav>
<article class="yle__article">
  <header><h1>Selkouutiset | torstai 15.10.2026</h1><p>Summary</p></header>
  <section class="yle__article__content">
    <h2>Sää</h2><p>Tänään on <strong>lämmin</strong> sää.</p>
    <figure><figcaption><p>Photo credit</p></figcaption></figure>
    <aside><p>Related story</p></aside>
    <p>Yöllä on kylmä.</p>
  </section>
  <footer><p>Contact details</p></footer>
</article>
"""


def test_extracts_body_in_order_without_navigation_or_captions():
    title, day, text = extract_broadcast(HTML, DAY)
    assert title == "Selkouutiset | torstai 15.10.2026"
    assert day == DAY
    assert text == "Sää\n\nTänään on lämmin sää.\n\nYöllä on kylmä.\n"


@pytest.mark.parametrize(
    "html,day",
    [
        (HTML, date(2026, 10, 14)),
        ("<html/>", DAY),
        (HTML.replace("<p>", "<div>").replace("</p>", "</div>"), DAY),
    ],
)
def test_rejects_wrong_date_or_missing_body(html, day):
    with pytest.raises(ValueError):
        extract_broadcast(html, day)


def test_archive_matches_date_within_one_card():
    html = f"""<main>
      <div><a href="/a/74-99999999">Other</a><time datetime="2026-10-14T17:00:00+0300"/></div>
      <div><a href="{URL}">Story</a><div><time datetime="2026-10-15T17:00:00+0300"/></div></div>
    </main>"""
    assert find_broadcast_url(html, DAY) == URL
    with pytest.raises(ValueError):
        find_broadcast_url(html, date(2026, 1, 1))


def test_archive_rejects_ambiguous_cards():
    html = """<div><a href="/a/74-11111111">One</a><a href="/a/74-22222222">Two</a>
        <time datetime="2026-10-15T17:00:00+0300"/></div>"""
    with pytest.raises(ValueError):
        find_broadcast_url(html, DAY)


def test_latest_uses_newest_date_not_card_order():
    html = """<time datetime="2026-10-11T12:00:00+0300"/>
        <time datetime="2026-10-15T17:00:00+0300"/>
        <time datetime="2026-10-14T17:00:00+0300"/>
        <time datetime="invalid"/>"""
    assert latest_broadcast_date(html) == DAY
    with pytest.raises(ValueError):
        latest_broadcast_date("<html/>")


@pytest.mark.parametrize(
    "url",
    [
        "http://yle.fi/a/74-123",
        "https://other.test/a/74-123",
        "https://yle.fi/selkouutiset",
        "https://yle.fi/a/74-123?x=1",
    ],
)
def test_rejects_non_article_urls(url):
    with pytest.raises(ValueError):
        article_url(url)


def test_csv_preserves_text_and_import_metadata(tmp_path):
    title, day, text = extract_broadcast(HTML, DAY)
    txt, csv_path = save_broadcast(tmp_path, title, day, text, URL)
    assert txt.read_text(encoding="utf-8") == text
    with csv_path.open(encoding="utf-8", newline="") as stream:
        assert list(csv.DictReader(stream)) == [
            {
                "title": title,
                "text": text,
                "language": "Finnish",
                "tags": "selkouutiset",
                "url": URL,
            }
        ]
    with pytest.raises(ValueError):
        save_broadcast(tmp_path, title, day, "Changed", URL)
    assert txt.read_text(encoding="utf-8") == text
    previous_mtime = (txt.stat().st_mtime_ns, csv_path.stat().st_mtime_ns)
    assert save_broadcast(tmp_path, title, day, text, URL) == (txt, csv_path)
    assert (txt.stat().st_mtime_ns, csv_path.stat().st_mtime_ns) == previous_mtime


def test_refuses_incomplete_existing_output(tmp_path):
    title, day, text = extract_broadcast(HTML, DAY)
    txt, csv_path = save_broadcast(tmp_path, title, day, text, URL)
    csv_path.unlink()
    with pytest.raises(ValueError):
        save_broadcast(tmp_path, title, day, text, URL)
    assert txt.read_text(encoding="utf-8") == text


def test_latest_cli_resolves_date_and_saves_csv(tmp_path, monkeypatch):
    import requests

    archive = f'<div><a href="{URL}">Story</a><time datetime="2026-10-15T17:00:00+0300"/></div>'
    calls = []

    def get(_session, url, **_kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 200
        response._content = (HTML if url == URL else archive).encode("utf-8")
        return response

    monkeypatch.setattr(requests.Session, "get", get)
    assert main(["--latest", "--output-dir", str(tmp_path)]) == 0
    assert calls == ["https://yle.fi/selkouutiset/kaikki-lahetykset", URL]
    csv_path = tmp_path / "selkouutiset-2026-10-15-fi.csv"
    with csv_path.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["title"] == "Selkouutiset | torstai 15.10.2026"
    assert row["tags"] == "selkouutiset"


def test_cli_reports_network_failure_without_writing_files(tmp_path, monkeypatch):
    import requests

    def fail(*args, **kwargs):
        raise requests.ConnectionError("Offline")

    monkeypatch.setattr(requests.Session, "get", fail)
    assert main(["--url", URL, "--output-dir", str(tmp_path)]) == 1
    assert not list(tmp_path.iterdir())
