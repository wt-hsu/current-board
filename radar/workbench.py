"""Render the analyst's private workbench (reports/workbench.html).

Local file only: it carries notes, overrides, candidate scores and the decision log, and is listed in
.gitignore. Nothing here is ever published. The page is server-rendered; the only JavaScript copies commands.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import BRAND, REPORTS_DIR, label
from .queries import decision_log, snapshot
from .report import _fmt_mw, _fmt_usd

TEMPLATES = Path(__file__).parent / "templates"


def render_workbench(snap: dict, log: list[dict]) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    tax = snap["taxonomy"]
    env.globals.update({
        "vc": lambda code, lang="en": label(tax, "value_chain", code, lang),
        "sig": lambda code, lang="en": label(tax, "signal_types", code, lang),
        "et": lambda code, lang="en": label(tax, "entity_types", code, lang),
        "rel": lambda code, lang="en": label(tax, "relation_types", code, lang),
        "usd": _fmt_usd, "mw": _fmt_mw,
    })
    reviewed_ids = {s["id"] for s in snap["review_queue"]}
    others = [s for s in snap["signals_week"] if s["id"] not in reviewed_ids]
    return env.get_template("workbench.html.j2").render(log=log, others=others, **snap)


def write_workbench(conn: sqlite3.Connection, week: str, out_dir: Path = REPORTS_DIR) -> Path:
    snap = snapshot(conn, week, private=True)
    html = render_workbench(snap, decision_log(conn))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "workbench.html"
    path.write_text(html, encoding="utf-8")
    return path
