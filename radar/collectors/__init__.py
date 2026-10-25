"""Collectors: pull candidate news items from free sources into the signals table.

Three passes: one Google News query per tracked entity (phrased by entity type), one per manual investor,
then discovery (topic queries per value-chain layer + industry RSS feeds)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .. import db
from ..config import Company, Investor
from . import feeds, google_news
from .fetch import fetch_article

log = logging.getLogger(__name__)


def _cutoff(lookback_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=lookback_days)


def _is_recent(item: dict[str, Any], cutoff: datetime) -> bool:
    ts = item.get("published_at")
    if not ts:
        return True  # unknown date: keep, dedupe will catch repeats
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return dt >= cutoff


def date_windows(since: str, until: str, days: int = 14) -> list[tuple[str, str]]:
    """Split [since, until] into consecutive windows of `days`, as ISO date strings.
    Google News RSS returns at most ~100 items per query, so a 10-week backfill must be asked for in slices."""
    start = datetime.fromisoformat(since).date()
    end = datetime.fromisoformat(until).date()
    out: list[tuple[str, str]] = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        out.append((cur.isoformat(), nxt.isoformat()))
        cur = nxt
    return out


def collect_all(conn: sqlite3.Connection, sources: dict[str, Any], companies: Iterable[Company],
                investors: Iterable[Investor], fetch_bodies: bool | None = None,
                windows: list[tuple[str, str]] | None = None) -> dict[str, int]:
    """`windows`: optional list of (after, before) ISO dates. When given, every Google News query is run once per
    window with Google's after:/before: operators appended, and the recency cutoff is the first window's start."""
    limits = sources.get("limits") or {}
    lookback = int(limits.get("lookback_days", 10))
    max_items = int(limits.get("max_items_per_query", 20))
    if windows:
        max_items = max(max_items, int(limits.get("backfill_items_per_query", 100)))
    if fetch_bodies is None:
        fetch_bodies = bool(limits.get("fetch_article_body", True))
    body_max = int(limits.get("body_max_chars", 6000))
    cutoff = _cutoff(lookback)
    backfill_cutoff = _cutoff(int(limits.get("backfill_days", 180)))
    if windows:
        first = datetime.fromisoformat(windows[0][0]).replace(tzinfo=timezone.utc)
        cutoff = backfill_cutoff = min(cutoff, first)

    def gn_search(name: str | None, template: str) -> list[dict[str, Any]]:
        """One Google News search, or one per date window when backfilling."""
        if not windows:
            return google_news.search(name, template, gn_cfg, max_items)
        out: list[dict[str, Any]] = []
        for after, before in windows:
            stats["queries"] += 1
            out.extend(google_news.search(name, f"{template} after:{after} before:{before}", gn_cfg, max_items))
        return out
    gn_cfg = sources.get("google_news") or {}
    disc_cfg = sources.get("discovery") or {}

    stats = {"queries": 0, "items_seen": 0, "items_new": 0, "bodies_fetched": 0, "errors": 0}

    def ingest(items: list[dict[str, Any]], since: datetime = cutoff) -> None:
        for item in items:
            stats["items_seen"] += 1
            if not _is_recent(item, since):
                continue
            try:
                sid = db.insert_signal(conn, item)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("insert failed for %s: %s", item.get("url"), exc)
                stats["errors"] += 1
                continue
            if sid is None:
                continue
            stats["items_new"] += 1
            if fetch_bodies:
                resolved, body = fetch_article(item["url"], body_max)
                if body or resolved:
                    db.update_signal_body(conn, sid, resolved, body)
                if body:
                    stats["bodies_fetched"] += 1
        conn.commit()

    # 1. Tracked companies. A company we have never collected for gets a long backfill window
    #    so the dashboard has history from day one.
    templates = gn_cfg.get("company_queries") or {}
    for c in companies:
        if getattr(c, "status", "active") != "active":
            continue
        seen_before = conn.execute("SELECT 1 FROM signals WHERE seed_company_slug=? LIMIT 1", (c.slug,)).fetchone()
        since = cutoff if seen_before else backfill_cutoff
        # the search phrasing depends on what kind of entity this is (a hyperscaler is not asked about "raises")
        template = templates.get(getattr(c, "entity_type", None)) or templates.get("default") or gn_cfg.get("company_query", '"{name}"')
        for name in _query_names(c.name, c.aliases):
            stats["queries"] += 0 if windows else 1
            try:
                items = gn_search(name, template)
            except Exception as exc:
                log.warning("google news failed for %s: %s", name, exc)
                stats["errors"] += 1
                continue
            for it in items:
                it.update(scope="company", seed_company_slug=c.slug)
            ingest(items, since)

    # 2. Tracked investors (manual ones only; auto-created ones would blow up the query count)
    for inv in investors:
        stats["queries"] += 0 if windows else 1
        try:
            items = gn_search(inv.name, gn_cfg.get("investor_query", '"{name}"'))
        except Exception as exc:
            log.warning("google news failed for investor %s: %s", inv.name, exc)
            stats["errors"] += 1
            continue
        for it in items:
            it.update(scope="investor", seed_investor_slug=inv.slug)
        ingest(items)

    # 3. Discovery: topic queries + newsletter feeds
    for q in disc_cfg.get("queries") or []:
        stats["queries"] += 0 if windows else 1
        try:
            items = gn_search(None, q)
        except Exception as exc:
            log.warning("google news discovery failed for %r: %s", q, exc)
            stats["errors"] += 1
            continue
        for it in items:
            it.update(scope="discovery")
        ingest(items)

    for feed in disc_cfg.get("feeds") or []:
        stats["queries"] += 1
        try:
            items = feeds.fetch_feed(feed["name"], feed["url"], max_items * 3)
        except Exception as exc:
            log.warning("feed %s failed: %s", feed.get("name"), exc)
            stats["errors"] += 1
            continue
        for it in items:
            it.update(scope="discovery")
        ingest(items)

    return stats


def _query_names(name: str, aliases: list[str]) -> list[str]:
    """Only query the canonical name. Aliases are used for matching, not searching,
    to keep the query count (and Google's patience) bounded."""
    return [name]
