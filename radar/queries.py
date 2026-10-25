"""Read-side queries shared by the weekly report, the dashboard and the review queue.

snapshot(conn, week, private=False) is the single entry point. With private=True it also carries the
analyst's notes, overrides, the decision log and the weekly view; the dashboard never asks for that.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .config import BRAND, load_sources, load_taxonomy


def week_bounds(week: str) -> tuple[str, str]:
    """ISO week 'YYYY-Www' -> (monday_iso, next_monday_iso) as dates."""
    year, w = week.split("-W")
    monday = date.fromisocalendar(int(year), int(w), 1)
    return monday.isoformat(), (monday + timedelta(days=7)).isoformat()


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _split(value: str | None) -> list[str]:
    return [x for x in (value or "").split(",") if x]


_SIGNAL_SELECT = """
    SELECT s.*, GROUP_CONCAT(DISTINCT sc.company_slug) AS company_slugs,
           GROUP_CONCAT(DISTINCT si.investor_slug) AS investor_slugs,
           n.importance_override, n.relevant_override, n.note_zh, n.note_en, n.deal_logic
    FROM signals s
    LEFT JOIN signal_companies sc ON sc.signal_id = s.id
    LEFT JOIN signal_investors si ON si.signal_id = s.id
    LEFT JOIN analyst_notes n ON n.signal_id = s.id
"""


def _decorate(s: dict[str, Any], private: bool) -> dict[str, Any]:
    s["link"] = s.get("resolved_url") or s["url"]
    s["date"] = (s.get("published_at") or s.get("fetched_at") or "")[:10]
    s["company_slugs"] = _split(s.pop("company_slugs", None))
    s["investor_slugs"] = _split(s.pop("investor_slugs", None))
    s["importance_machine"] = s.get("importance") or 1
    s["importance_final"] = s["importance_override"] if private and s.get("importance_override") else s["importance_machine"]
    s.pop("body", None)
    s.pop("extracted_json", None)
    if not private:
        for k in ("importance_override", "relevant_override", "note_zh", "note_en", "deal_logic"):
            s.pop(k, None)
    return s


def signals_for_week(conn: sqlite3.Connection, week: str, private: bool = False) -> list[dict[str, Any]]:
    start, end = week_bounds(week)
    rows = _rows(conn, _SIGNAL_SELECT + """
        WHERE s.status = 'extracted' AND s.relevant = 1
          AND ((s.published_at >= ? AND s.published_at < ?)
               OR (s.published_at IS NULL AND s.extracted_at >= ? AND s.extracted_at < ?))
        GROUP BY s.id ORDER BY s.importance DESC, s.published_at DESC""", (start, end, start, end))
    out = [_decorate(s, private) for s in rows]
    if private:  # the analyst can also mark a signal irrelevant
        out = [s for s in out if s.get("relevant_override") != 0]
    return sorted(out, key=lambda s: (-s["importance_final"], s["date"]), reverse=False)


def recent_signals(conn: sqlite3.Connection, days: int = 90, limit: int = 600, private: bool = False) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rows = _rows(conn, _SIGNAL_SELECT + """
        WHERE s.status='extracted' AND s.relevant=1 AND COALESCE(s.published_at, s.fetched_at) >= ?
        GROUP BY s.id ORDER BY COALESCE(s.published_at, s.fetched_at) DESC LIMIT ?""", (since, limit))
    return [_decorate(s, private) for s in rows]


def relations(conn: sqlite3.Connection, week: str | None = None, limit: int = 400) -> list[dict[str, Any]]:
    where, params = "", ()
    if week:
        start, end = week_bounds(week)
        where, params = "WHERE r.first_seen >= ? AND r.first_seen < ?", (start, end)
    rows = _rows(conn, f"""
        SELECT r.*, cs.value_chain AS subject_layer, co.value_chain AS object_layer, cs.entity_type AS subject_type,
               co.entity_type AS object_type, COALESCE(s.resolved_url, s.url) AS source_url, s.source, s.value_chain
        FROM relations r
        LEFT JOIN companies cs ON cs.slug = r.subject_slug
        LEFT JOIN companies co ON co.slug = r.object_slug
        LEFT JOIN signals s ON s.id = r.signal_id
        {where} ORDER BY r.first_seen DESC, COALESCE(r.value_usd, 0) DESC LIMIT {int(limit)}""", params)
    return rows


def funding_rounds(conn: sqlite3.Connection, week: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    where, params = "", ()
    if week:
        start, end = week_bounds(week)
        where = "WHERE (fr.announced_on >= ? AND fr.announced_on < ?) OR (fr.announced_on IS NULL AND fr.created_at >= ? AND fr.created_at < ?)"
        params = (start, end, start, end)
    rows = _rows(conn, f"""
        SELECT fr.*, c.name AS company_name, c.value_chain,
               GROUP_CONCAT(CASE WHEN ri.role='lead' THEN i.name END) AS leads,
               GROUP_CONCAT(CASE WHEN ri.role='participant' THEN i.name END) AS participants
        FROM funding_rounds fr
        LEFT JOIN companies c ON c.slug = fr.company_slug
        LEFT JOIN round_investors ri ON ri.round_id = fr.id
        LEFT JOIN investors i ON i.slug = ri.investor_slug
        {where}
        GROUP BY fr.id ORDER BY COALESCE(fr.announced_on, fr.created_at) DESC LIMIT {int(limit)}""", params)
    for r in rows:
        r["company_name"] = r["company_name"] or r["company_name_raw"]
        r["leads"] = sorted(set(_split(r["leads"])))
        r["participants"] = sorted(set(_split(r["participants"])))
        r["date"] = (r.get("announced_on") or r["created_at"])[:10]
    return rows


def companies(conn: sqlite3.Connection, private: bool = False) -> list[dict[str, Any]]:
    rows = _rows(conn, """
        SELECT c.*, COUNT(DISTINCT sc.signal_id) AS signal_count, MAX(s.published_at) AS last_signal_at,
               (SELECT SUM(amount_usd) FROM funding_rounds fr WHERE fr.company_slug=c.slug) AS total_raised_usd,
               (SELECT COUNT(*) FROM relations r WHERE r.subject_slug=c.slug OR r.object_slug=c.slug) AS relation_count
        FROM companies c
        LEFT JOIN signal_companies sc ON sc.company_slug=c.slug
        LEFT JOIN signals s ON s.id=sc.signal_id AND s.relevant=1
        GROUP BY c.slug ORDER BY c.value_chain, c.name""")
    if not private:
        for r in rows:
            r.pop("notes", None)
    return rows


def investors(conn: sqlite3.Connection, private: bool = False) -> list[dict[str, Any]]:
    rows = _rows(conn, """
        SELECT i.*, COUNT(DISTINCT ri.round_id) AS round_count, COUNT(DISTINCT si.signal_id) AS signal_count,
               GROUP_CONCAT(DISTINCT c.name) AS portfolio
        FROM investors i
        LEFT JOIN round_investors ri ON ri.investor_slug=i.slug
        LEFT JOIN funding_rounds fr ON fr.id=ri.round_id
        LEFT JOIN companies c ON c.slug=fr.company_slug
        LEFT JOIN signal_investors si ON si.investor_slug=i.slug
        GROUP BY i.slug ORDER BY round_count DESC, signal_count DESC, i.name""")
    for r in rows:
        r["portfolio"] = sorted(set(_split(r["portfolio"])))
        try:
            r["stage_focus"] = json.loads(r["stage_focus"]) if r["stage_focus"] else []
        except json.JSONDecodeError:
            r["stage_focus"] = []
        if not private:
            for k in ("notes", "energy_thesis", "conflict_risk"):
                r.pop(k, None)
    return rows


def candidates(conn: sqlite3.Connection, status: str = "proposed", limit: int = 20, private: bool = False) -> list[dict[str, Any]]:
    rows = _rows(conn, """
        SELECT cd.*, s.title AS first_title, COALESCE(s.resolved_url, s.url) AS first_url
        FROM candidates cd LEFT JOIN signals s ON s.id = cd.first_signal_id
        WHERE cd.status=? ORDER BY cd.score DESC, cd.mentions DESC LIMIT ?""", (status, limit))
    if not private:
        for r in rows:
            for k in ("score", "why_relevant", "source"):
                r.pop(k, None)
    return rows


def review_queue(conn: sqlite3.Connection, week: str, rules: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The 8–12 signals worth the analyst's hour: high importance, money/MW at importance 3, new relations."""
    rules = rules or (load_sources().get("review") or {})
    min_imp = int(rules.get("min_importance", 4))
    money_imp = int(rules.get("money_importance", 3))
    max_items = int(rules.get("max_items", 12))
    start, end = week_bounds(week)
    new_rel_sids = {r["signal_id"] for r in relations(conn, week) if r.get("signal_id")}
    out = []
    for s in signals_for_week(conn, week, private=True):
        reasons = []
        if s["importance_machine"] >= min_imp:
            reasons.append(f"importance {s['importance_machine']}")
        if s["importance_machine"] >= money_imp and (s.get("deal_value_usd") or s.get("capacity_mw")):
            reasons.append("money or MW stated")
        if s["id"] in new_rel_sids:
            reasons.append("new relation")
        if reasons:
            s["reasons"] = reasons
            s["reviewed"] = bool(s.get("importance_override") or s.get("note_zh") or s.get("note_en"))
            out.append(s)
    out.sort(key=lambda s: (s["reviewed"], -s["importance_final"], -(s.get("deal_value_usd") or 0)))
    return out[:max_items]


def weekly_view(conn: sqlite3.Connection, week: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM weekly_views WHERE week=?", (week,)).fetchone()
    return dict(row) if row else None


def decision_log(conn: sqlite3.Connection, since_days: int = 35, limit: int = 200) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    return _rows(conn, "SELECT * FROM decision_log WHERE decided_at >= ? ORDER BY decided_at DESC LIMIT ?", (since, limit))


def run_stats(conn: sqlite3.Connection, week: str) -> dict[str, Any]:
    start, end = week_bounds(week)
    out: dict[str, Any] = {}
    out["collected"] = conn.execute("SELECT COUNT(*) FROM signals WHERE fetched_at >= ? AND fetched_at < ?", (start, end)).fetchone()[0]
    out["extracted"] = conn.execute("SELECT COUNT(*) FROM signals WHERE extracted_at >= ? AND extracted_at < ?", (start, end)).fetchone()[0]
    out["failed"] = conn.execute("SELECT COUNT(*) FROM signals WHERE status='failed'").fetchone()[0]
    out["pending"] = conn.execute("SELECT COUNT(*) FROM signals WHERE status='new'").fetchone()[0]
    out["no_body"] = conn.execute("SELECT COUNT(*) FROM signals WHERE body IS NULL AND fetched_at >= ? AND fetched_at < ?", (start, end)).fetchone()[0]
    out["relations_total"] = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
    last = conn.execute("SELECT stage, started_at, finished_at, stats_json FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    out["last_run"] = dict(last) if last else None
    return out


def snapshot(conn: sqlite3.Connection, week: str, private: bool = False) -> dict[str, Any]:
    tax = load_taxonomy()
    week_signals = signals_for_week(conn, week, private)
    comps = companies(conn, private)
    by_slug = {c["slug"]: c for c in comps}
    for s in week_signals:
        s["company_names"] = [by_slug[x]["name"] for x in s["company_slugs"] if x in by_slug]
    rels_week = relations(conn, week)
    view = weekly_view(conn, week)
    if view and not private and not view.get("public"):
        view = None
    return {
        "brand": BRAND,
        "week": week,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "taxonomy": tax,
        "private": private,
        "signals_week": week_signals,
        "top_signals": [s for s in week_signals if s["importance_final"] >= 4],
        "relations_week": rels_week,
        "relations_all": relations(conn),
        "funding_week": funding_rounds(conn, week),
        "funding_all": funding_rounds(conn),
        "companies": comps,
        "investors": investors(conn, private),
        "candidates": candidates(conn, private=private),
        "signals_recent": recent_signals(conn, private=private),
        "review_queue": review_queue(conn, week) if private else [],
        "weekly_view": view,
        "stats": run_stats(conn, week),
    }
