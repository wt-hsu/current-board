"""Render the public static dashboard (docs/index.html) for GitHub Pages.

Everything that reaches the page passes through an explicit field whitelist, and the rendered payload is
scanned for private field names before it is written. If the scan fails nothing is written.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .config import BRAND, DOCS_DIR, REPORTS_DIR
from .queries import recent_signals, snapshot

TEMPLATES = Path(__file__).parent / "templates"
WORLD = TEMPLATES / "world-110m.json"  # Natural Earth 1:110m countries via world-atlas (ISC), inlined into the page

# Field names that must never appear anywhere in the public payload (SPEC-v3 §2.3 "private").
PRIVATE_KEYS = {
    "notes", "note_zh", "note_en", "deal_logic", "importance_override", "relevant_override", "reason",
    "why_relevant", "score", "source_rule", "energy_thesis", "conflict_risk", "draft_zh", "draft_en", "body",
    "extracted_json", "machine_value", "human_value", "review_queue", "decision_log", "raw_summary",
}

PUBLIC_FIELDS = {
    "signal": ("id", "title", "link", "source", "date", "signal_type", "value_chain", "importance", "summary",
               "deal_value_usd", "capacity_mw", "capacity_kind", "project_stage", "location_name", "location_country",
               "grid_region", "lat", "lng", "location_precision", "event_scope", "company_slugs", "investor_slugs", "scope"),
    "relation": ("id", "subject_slug", "subject_name", "object_slug", "object_name", "relation_type", "value_usd",
                 "capacity_mw", "term_years", "value_source", "confidence", "first_seen", "last_seen", "mentions", "source_url", "source"),
    "funding": ("id", "company_slug", "company_name", "value_chain", "date", "round_type", "amount_raw", "amount_usd",
                "leads", "participants", "confidence", "source_url"),
    "company": ("slug", "name", "domain", "entity_type", "value_chain", "hq_country", "region", "ticker", "status",
                "signal_count", "last_signal_at", "total_raised_usd", "relation_count"),
    "investor": ("slug", "name", "fund_type", "stage_focus", "status", "round_count", "signal_count", "portfolio"),
    "candidate": ("name", "domain", "entity_type", "value_chain", "first_title", "first_url", "proposed_week", "mentions"),
}


def _pick(kind: str, row: dict) -> dict:
    return {k: row.get(k) for k in PUBLIC_FIELDS[kind]}


class PrivateFieldLeak(RuntimeError):
    pass


def check_public(obj, path: str = "$") -> None:
    """Raise if any private key appears anywhere in the payload."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in PRIVATE_KEYS:
                raise PrivateFieldLeak(f"private field {k!r} at {path}")
            check_public(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            check_public(v, f"{path}[{i}]")


def build_payload(snap: dict) -> dict:
    tax = snap["taxonomy"]
    labels = {kind: {code: {"en": v.get("label_en", code)}
                     for code, v in (tax.get(kind) or {}).items() if isinstance(v, dict)}
              for kind in ("value_chain", "signal_types", "entity_types", "relation_types")}
    view = snap.get("weekly_view") or {}
    payload = {
        "brand": {k: v for k, v in BRAND.items() if not k.endswith("_zh")},  # the public board is English-only
        "week": snap["week"],
        "generated_at": snap["generated_at"],
        "labels": labels,
        "signals": [_pick("signal", s) for s in snap["signals_recent"]],
        "week_signal_ids": [s["id"] for s in snap["signals_week"]],
        "relations": [_pick("relation", r) for r in snap["relations_all"]],
        "week_relation_ids": [r["id"] for r in snap["relations_week"]],
        "funding": [_pick("funding", r) for r in snap["funding_all"]],
        "week_funding_ids": [r["id"] for r in snap["funding_week"]],
        "companies": [_pick("company", c) for c in snap["companies"]],
        "investors": [_pick("investor", i) for i in snap["investors"]],
        "candidates": [_pick("candidate", c) for c in snap["candidates"]],
        "weekly_view": {"en": view.get("draft_en")} if view.get("public") else None,
        "stats": {k: v for k, v in snap["stats"].items() if k != "last_run"},
    }
    check_public(payload)
    return payload


def render_html(snap: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=False)
    payload = json.dumps(build_payload(snap), ensure_ascii=False).replace("</", "<\\/")
    world = WORLD.read_text(encoding="utf-8") if WORLD.exists() else '{"type":"Topology","objects":{"countries":{"type":"GeometryCollection","geometries":[]}},"arcs":[]}'
    vendor_d3 = (TEMPLATES / "vendor-d3.min.js").read_text(encoding="utf-8")          # D3 7, ISC — inlined so the page works offline and without a CDN
    vendor_topojson = (TEMPLATES / "vendor-topojson.min.js").read_text(encoding="utf-8")  # topojson-client 3, ISC
    return env.get_template("dashboard.html.j2").render(data_json=payload, world_json=world, vendor_d3=vendor_d3,
                                                        vendor_topojson=vendor_topojson, week=snap["week"], brand=BRAND)


def write_dashboard(conn: sqlite3.Connection, week: str, out_dir: Path = DOCS_DIR) -> Path:
    snap = snapshot(conn, week, private=False)   # the dashboard never sees the private snapshot
    # the board reads 8 weeks of activity and 90 days of feed; lift the default 600-row cap but drop the marginal (1/5)
    snap["signals_recent"] = [s for s in recent_signals(conn, days=90, limit=4000, private=False) if (s.get("importance") or 1) >= 2]
    html = render_html(snap)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    public_report = REPORTS_DIR / "latest.public.md"
    if public_report.exists():  # Pages only serves docs/, so carry the public report along
        (out_dir / "latest-report.md").write_text(public_report.read_text(encoding="utf-8"), encoding="utf-8")
    return path
