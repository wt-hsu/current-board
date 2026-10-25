"""Best-effort article body fetching.

Google News RSS links are redirect wrappers; we decode them through Google's
batchexecute endpoint (same trick the googlenewsdecoder package uses). If that
breaks, we fall back to title + RSS summary, which is usually enough for the LLM
to classify the item and pull a headline funding amount.
"""

from __future__ import annotations

import html
import json
import logging
import re

import httpx

from .google_news import UA

log = logging.getLogger(__name__)

_GN_RE = re.compile(r"https://news\.google\.com/rss/articles/([^?/]+)")
_BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


def resolve_google_news(url: str, client: httpx.Client) -> str | None:
    m = _GN_RE.match(url)
    if not m:
        return url
    art_id = m.group(1)
    try:
        page = client.get(url)
        sg = re.search(r'data-n-a-sg="([^"]+)"', page.text)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page.text)
        if not (sg and ts):
            return None
        req = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                              None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
               art_id, ts.group(1), sg.group(1)]
        payload = json.dumps([[["Fbv4je", json.dumps(req), None, "generic"]]])
        resp = client.post(_BATCH_URL, data={"f.req": payload},
                           headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        chunk = resp.text.split("\n\n")[1]
        outer = json.loads(chunk)
        inner = json.loads(outer[0][2])
        resolved = inner[1]
        return resolved if isinstance(resolved, str) and resolved.startswith("http") else None
    except Exception as exc:  # noqa: BLE001 - any failure just means "unresolved"
        log.debug("could not resolve %s: %s", url, exc)
        return None


_DROP_TAGS = re.compile(r"<(script|style|noscript|svg|nav|header|footer|aside|form)[^>]*>.*?</\1>", re.S | re.I)
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(raw: str, max_chars: int) -> str | None:
    raw = _DROP_TAGS.sub(" ", raw)
    paragraphs = [_TAG_RE.sub(" ", p) for p in _P_RE.findall(raw)]
    paragraphs = [re.sub(r"\s+", " ", html.unescape(p)).strip() for p in paragraphs]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    text = "\n".join(paragraphs)
    if len(text) < 300:  # page without <p>, fall back to whole document text
        text = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", raw))).strip()
    text = text[:max_chars].strip()
    return text or None


def fetch_article(url: str, max_chars: int = 6000, client: httpx.Client | None = None) -> tuple[str | None, str | None]:
    """Return (resolved_url, body_text). Either may be None."""
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA})
    try:
        resolved = resolve_google_news(url, client)
        target = resolved or (url if not _GN_RE.match(url) else None)
        if not target:
            return None, None
        try:
            resp = client.get(target)
            if resp.status_code >= 400 or "text/html" not in resp.headers.get("content-type", "text/html"):
                return resolved, None
            return resolved, html_to_text(resp.text, max_chars)
        except Exception as exc:  # noqa: BLE001
            log.debug("fetch failed %s: %s", target, exc)
            return resolved, None
    finally:
        if own:
            client.close()
