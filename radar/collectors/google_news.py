"""Google News RSS search. Free, no key, covers most funding / partnership press."""

from __future__ import annotations

import html
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
from dateutil import parser as dateparser

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE = "https://news.google.com/rss/search"


def build_url(query: str, cfg: dict[str, Any]) -> str:
    params = {
        "q": query,
        "hl": cfg.get("hl", "en-US"),
        "gl": cfg.get("gl", "US"),
        "ceid": cfg.get("ceid", "US:en"),
    }
    return f"{BASE}?{urllib.parse.urlencode(params)}"


def _to_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = dateparser.parse(value)
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip() or None


def parse_feed(xml: str, query: str, max_items: int) -> list[dict[str, Any]]:
    parsed = feedparser.parse(xml)
    items: list[dict[str, Any]] = []
    for e in parsed.entries[:max_items]:
        title = (e.get("title") or "").strip()
        link = e.get("link")
        if not title or not link:
            continue
        source = None
        src = e.get("source")
        if isinstance(src, dict):
            source = src.get("title")
        if not source and " - " in title:
            source = title.rsplit(" - ", 1)[1].strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        items.append({
            "url": link,
            "title": title,
            "source": source,
            "published_at": _to_iso(e.get("published")),
            "raw_summary": _strip_html(e.get("summary")),
            "query": query,
        })
    return items


def search(name: str | None, template: str, cfg: dict[str, Any], max_items: int,
           client: httpx.Client | None = None) -> list[dict[str, Any]]:
    query = template.format(name=name) if name is not None else template
    url = build_url(query, cfg)
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA})
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return parse_feed(resp.text, query, max_items)
    finally:
        if own:
            client.close()
