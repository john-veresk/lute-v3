"""Extract a Yle Selkouutiset broadcast into UTF-8 text and a Lute import CSV."""

import argparse
import csv
from datetime import date
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

ARCHIVE_URL = "https://yle.fi/selkouutiset/kaikki-lahetykset"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "text"


def article_url(value):
    """Accept only public Yle article URLs."""
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "yle.fi"
        or not re.fullmatch(r"/a/\d+-\d+", parsed.path)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Expected an article URL like https://yle.fi/a/74-12345678")
    return value


def fetch_html(session, url):
    """Fetch HTML with a timeout and explicit HTTP error handling."""
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.content


def find_broadcast_url(html, broadcast_date):
    """Find a dated story card without confusing it with adjacent broadcasts."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = set()
    for timestamp in soup.select("time[datetime]"):
        if timestamp["datetime"][:10] != broadcast_date.isoformat():
            continue
        for parent in timestamp.parents:
            links = set()
            for anchor in parent.select("a[href]"):
                value = urljoin(ARCHIVE_URL, anchor["href"])
                try:
                    links.add(article_url(value))
                except ValueError:
                    continue
            if links:
                if len(links) == 1:
                    candidates.update(links)
                break
    if len(candidates) != 1:
        raise ValueError(
            f"Cannot identify one broadcast for {broadcast_date.isoformat()} "
            "on the archive page. For older broadcasts, supply --url instead."
        )
    return candidates.pop()


def extract_broadcast(html, expected_date=None):
    """Extract only the article body, preserving Finnish and paragraph order."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.yle__article")
    heading = article.select_one("h1") if article else None
    body = article.select_one(".yle__article__content") if article else None
    if heading is None or body is None:
        raise ValueError(
            "Yle article heading or body missing; page layout may have changed"
        )
    title = " ".join(heading.get_text(" ", strip=True).split())
    match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", title)
    if "selkouutiset" not in title.casefold() or not match:
        raise ValueError("This is not a dated Selkouutiset broadcast")
    day, month, year = map(int, match.groups())
    broadcast_date = date(year, month, day)
    if expected_date is not None and broadcast_date != expected_date:
        raise ValueError(
            f"Requested {expected_date}, but article is dated {broadcast_date}"
        )

    for element in body.select(
        "figure, aside, nav, footer, button, form, script, style, noscript"
    ):
        element.decompose()
    paragraphs = []
    has_prose = False
    for element in body.select("h2, h3, p"):
        paragraph = " ".join(element.get_text(" ", strip=True).split())
        if paragraph:
            paragraphs.append(paragraph)
            has_prose = has_prose or element.name == "p"
    if not has_prose:
        raise ValueError("Broadcast body contains no text paragraphs")
    return title, broadcast_date, "\n\n".join(paragraphs) + "\n"


def save_broadcast(output_dir, title, broadcast_date, text, source_url):
    """Write a reading file and a CSV accepted by Lute's existing import CLI."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"selkouutiset-{broadcast_date.isoformat()}-fi"
    text_path = output_dir / f"{stem}.txt"
    csv_path = output_dir / f"{stem}.csv"
    # Do not replace a previously extracted or manually corrected text silently.
    if text_path.exists() or csv_path.exists():
        raise ValueError(
            f"Output already exists for {broadcast_date}; choose another --output-dir"
        )
    text_path.write_text(text, encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["title", "text", "language", "tags", "url"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "title": title,
                "text": text,
                "language": "Finnish",
                "tags": "selkouutiset",
                "url": source_url,
            }
        )
    return text_path, csv_path


def main(argv=None):
    """Command-line entry point; extraction does not modify the Lute database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", type=date.fromisoformat, help="Broadcast date: YYYY-MM-DD"
    )
    parser.add_argument(
        "--url", help="Direct Yle article URL (also works for older broadcasts)"
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    if args.date is None and args.url is None:
        parser.error("supply --date or --url")
    try:
        with requests.Session() as session:
            session.headers["User-Agent"] = "Lute-Selkouutiset-Extractor/1.0"
            if args.url:
                url = article_url(args.url)
            else:
                url = find_broadcast_url(fetch_html(session, ARCHIVE_URL), args.date)
            title, broadcast_date, text = extract_broadcast(
                fetch_html(session, url), args.date
            )
        paths = save_broadcast(args.output_dir, title, broadcast_date, text, url)
    except (requests.RequestException, ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(title)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
