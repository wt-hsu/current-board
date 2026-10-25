"""Render the weekly Markdown report ("On the Board / 本週上板") from a snapshot.

Private version (default): machine facts on top, the analyst's notes and weekly view underneath.
Public version: facts only, plus the weekly view when it has been marked public.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import REPORTS_DIR, label
from .queries import snapshot

TEMPLATES = Path(__file__).parent / "templates"


def _env(autoescape: bool = False) -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]) if autoescape else False,
                      trim_blocks=True, lstrip_blocks=True)
    env.tests["contains"] = lambda seq, item: item in (seq or [])
    return env


def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1e9:
        return f"${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v / 1e3:.0f}K"


def _fmt_mw(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v / 1000:.1f} GW" if v >= 1000 else f"{v:.0f} MW"


def render_markdown(snap: dict) -> str:
    env = _env()
    tax = snap["taxonomy"]
    env.globals.update({
        "vc": lambda code, lang="en": label(tax, "value_chain", code, lang),
        "sig": lambda code, lang="en": label(tax, "signal_types", code, lang),
        "et": lambda code, lang="en": label(tax, "entity_types", code, lang),
        "rel": lambda code, lang="en": label(tax, "relation_types", code, lang),
        "usd": _fmt_usd, "mw": _fmt_mw,
    })
    return env.get_template("weekly.md.j2").render(**snap)


def write_report(conn: sqlite3.Connection, week: str, out_dir: Path = REPORTS_DIR, private: bool = True) -> Path:
    snap = snapshot(conn, week, private=private)
    md = render_markdown(snap)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if private else ".public"
    path = out_dir / f"{week}{suffix}.md"
    path.write_text(md, encoding="utf-8")
    (out_dir / f"latest{suffix}.md").write_text(md, encoding="utf-8")
    return path
