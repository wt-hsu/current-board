"""Plain RSS/Atom feeds (climate-tech deal newsletters)."""

from __future__ import annotations

from typing import Any

import httpx

from .google_news import UA, _strip_html, _to_iso

import feedparser


def fetch_feed(name: str, url: str, max_items: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        xml = resp.text
    parsed = feedparser.parse(xml)
    items: list[dict[str, Any]] = []
    for e in parsed.entries[:max_items]:
        title = (e.get("title") or "").strip()
        link = e.get("link")
        if not title or not link:
            continue
        summary = e.get("summary") or ""
        content = e.get("content")
        if isinstance(content, list) and content:
            summary = content[0].get("value") or summary
        items.append({
            "url": link,
            "title": title,
            "source": name,
            "published_at": _to_iso(e.get("published") or e.get("updated")),
            "raw_summary": (_strip_html(summary) or "")[:2000] or None,
            "query": f"feed:{name}",
        })
    return items
