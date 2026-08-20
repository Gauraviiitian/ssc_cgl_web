from __future__ import annotations

import re
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.mahendras.org/blogs/current-affairs-{dd}-{mon}-{yyyy}"
USER_AGENT = "Mozilla/5.0 (compatible; ssc-cgl-prep-bot/1.0)"
MAX_SOURCE_CHARS = 12000

# When today's article isn't published yet, combine whichever of the
# previous FALLBACK_LOOKBACK_DAYS days have one, so Groq has enough fresh
# material to write a new, different set of questions rather than just
# reusing a single old day's (thinner) article.
#
# Kept small enough that source text + the (fairly verbose) system prompt +
# the completion's max_tokens together stay under Groq's tokens-per-minute
# cap for this model/tier (hit a 413 "rate_limit_exceeded" in production
# once a multi-day fallback pushed a request to ~10.6k tokens against an
# 8000 TPM limit) — see app/llm.py's generate_ca_questions max_tokens.
FALLBACK_LOOKBACK_DAYS = 7
MAX_CHARS_PER_FALLBACK_DAY = 900
MAX_COMBINED_SOURCE_CHARS = 6000

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

    return "\n".join(paragraphs)


def _fetch_day(client: httpx.Client, d: date) -> str | None:
    """Return cleaned article text for date d, or None if it isn't published."""
    resp = client.get(_url_for(d))
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    if _title_marker(d) not in title:
        return None  # soft-404: site redirected to the homepage

    text = _extract_article_text(resp.text)
    if len(text) < 200:
        return None
    return text


def fetch_source_for_date(target_date: date) -> tuple[str, list[str], date]:
    """Fetch CA source material for target_date.

    If target_date's article is up, returns just that day's text. Otherwise
    combines whichever of the FALLBACK_LOOKBACK_DAYS days before it have an
    article, so there's still enough fresh material for Groq to generate a
    new set of questions from.

    Returns (source_text, source_urls, source_date) where source_date is
    target_date itself, or the most recent fallback day used.
    """
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
        today_text = _fetch_day(client, target_date)
        if today_text is not None:
            return today_text[:MAX_SOURCE_CHARS], [_url_for(target_date)], target_date

        chunks: list[str] = []
        urls: list[str] = []
        newest_available: date | None = None
        for offset in range(1, FALLBACK_LOOKBACK_DAYS + 1):
            d = target_date - timedelta(days=offset)
            text = _fetch_day(client, d)
            if text is None:
                continue
            if newest_available is None:
                newest_available = d
            chunks.append(f"--- Current affairs {d.isoformat()} ---\n{text[:MAX_CHARS_PER_FALLBACK_DAY]}")
            urls.append(_url_for(d))

        if not chunks:
            raise SourceNotFoundError(
                f"No current affairs article found for {target_date} or the "
                f"{FALLBACK_LOOKBACK_DAYS} days before it"
            )

        combined = "\n\n".join(chunks)[:MAX_COMBINED_SOURCE_CHARS]
        return combined, urls, newest_available
