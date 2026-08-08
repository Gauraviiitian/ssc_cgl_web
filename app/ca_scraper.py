from __future__ import annotations

import re
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.mahendras.org/blogs/current-affairs-{dd}-{mon}-{yyyy}"
USER_AGENT = "Mozilla/5.0 (compatible; ssc-cgl-prep-bot/1.0)"
MAX_SOURCE_CHARS = 15000

# Devanagari block; paragraphs mostly in this script are the Hindi
# translation of the preceding English paragraph and add nothing for
# Groq beyond extra tokens, so they're dropped.
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


class SourceNotFoundError(Exception):
    pass


def _url_for(d: date) -> str:
    return BASE_URL.format(dd=f"{d.day:02d}", mon=d.strftime("%b").lower(), yyyy=d.year)


def _title_marker(d: date) -> str:
    # e.g. "08 Aug 2026" — matches how the site renders the date in <title>.
    return f"{d.day:02d} {d.strftime('%b')} {d.year}"


def _is_mostly_devanagari(text: str, threshold: float = 0.3) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    devanagari = sum(1 for c in letters if _DEVANAGARI_RE.match(c))
    return (devanagari / len(letters)) > threshold


def _extract_article_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    content = soup.find(class_="blog-content")
    if content is None:
        raise SourceNotFoundError("blog-content container not found on page")

    for tag in content.find_all(["script", "style"]):
        tag.decompose()

    paragraphs = []
    for el in content.find_all(["h1", "h2", "h3", "p", "li", "td"]):
        text = el.get_text(" ", strip=True)
        if not text or _is_mostly_devanagari(text):
            continue
        paragraphs.append(text)

    joined = "\n".join(paragraphs)
    return joined[:MAX_SOURCE_CHARS]


def fetch_source_for_date(target_date: date, max_lookback_days: int = 10) -> tuple[str, str, date]:
    """Fetch the CA article for target_date, falling back to earlier days if
    that day's article isn't published yet. Returns (clean_text, source_url, source_date).
    """
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
        for offset in range(max_lookback_days + 1):
            d = target_date - timedelta(days=offset)
            url = _url_for(d)
            resp = client.get(url)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            title = soup.title.get_text(strip=True) if soup.title else ""
            if _title_marker(d) not in title:
                continue  # soft-404: site redirected to the homepage

            text = _extract_article_text(resp.text)
            if len(text) < 200:
                continue

            return text, url, d

    raise SourceNotFoundError(
        f"No current affairs article found for {target_date} or the {max_lookback_days} days before it"
    )
