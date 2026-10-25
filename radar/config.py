"""Load YAML config (watchlist, taxonomy, sources) and resolve project paths.

Two roots:
  ROOT       the code checkout (templates, docs/ for the public dashboard)
  DATA_ROOT  where config/, data/, reports/ live. Defaults to ROOT; set RADAR_DATA_DIR to point at the
             private data repository once code and data are split.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("RADAR_ROOT", Path(__file__).resolve().parent.parent))
DATA_ROOT = Path(os.environ.get("RADAR_DATA_DIR", ROOT))
CONFIG_DIR = DATA_ROOT / "config"
DATA_DIR = DATA_ROOT / "data"
REPORTS_DIR = DATA_ROOT / "reports"
DOCS_DIR = ROOT / "docs"
DB_PATH = Path(os.environ.get("RADAR_DB", DATA_DIR / "radar.db"))

WATCHLIST_FILES = [CONFIG_DIR / "watchlist.yaml", CONFIG_DIR / "watchlist.accepted.yaml"]
TAXONOMY_FILE = CONFIG_DIR / "taxonomy.yaml"
SOURCES_FILE = CONFIG_DIR / "sources.yaml"

BRAND = {
    "name": "Current Board",
    "name_zh": "電流看板",
    "tagline_en": "The power behind AI, on one board.",
    "tagline_zh": "AI 背後的電，一板看盡。",
    "weekly_en": "On the Board",
    "weekly_zh": "本週上板",
    "sparks": "Sparks",
    "footer_en": "Every line on the board has a source.",
    "footer_zh": "板上每一條都有來源。",
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "unnamed"


@dataclass
class Company:
    """A tracked entity: hyperscaler, utility, equipment maker, startup ... 'Company' kept for continuity."""
    name: str
    domain: str | None = None
    entity_type: str = "private_startup"
    value_chain: str = "other"
    hq_country: str | None = None
    region: str | None = None
    ticker: str | None = None
    aliases: list[str] = field(default_factory=list)
    notes: str | None = None          # maintainer-owned, private, never overwritten by the pipeline
    status: str = "active"

    @property
    def slug(self) -> str:
        return slugify(self.name)


@dataclass
class Investor:
    name: str
    domain: str | None = None
    fund_type: str = "unknown"
    stage_focus: list[str] = field(default_factory=list)
    energy_thesis: str | None = None
    conflict_risk: str | None = None
    aliases: list[str] = field(default_factory=list)
    notes: str | None = None

    @property
    def slug(self) -> str:
        return slugify(self.name)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_taxonomy() -> dict[str, Any]:
    return _load_yaml(TAXONOMY_FILE)


def load_sources() -> dict[str, Any]:
    return _load_yaml(SOURCES_FILE)


def label(taxonomy: dict[str, Any], kind: str, code: str | None, lang: str = "en") -> str:
    """Human label for a taxonomy code. kind in value_chain | signal_types | entity_types | relation_types."""
    code = code or "other"
    entry = (taxonomy.get(kind) or {}).get(code)
    if isinstance(entry, dict):
        return entry.get(f"label_{lang}") or entry.get("label_en") or code
    return {"m_and_a": "M&A"}.get(code) or code.replace("_", " ").title()


def importance_scale_text(taxonomy: dict[str, Any], lang: str = "en") -> str:
    scale = taxonomy.get("importance_scale") or {}
    lines = []
    for level in sorted(scale, reverse=True):
        entry = scale[level]
        text = entry.get(lang) if isinstance(entry, dict) else entry
        lines.append(f"{level}: {text}")
    return "\n".join(lines)


def load_watchlist() -> tuple[list[Company], list[Investor]]:
    taxonomy = load_taxonomy()
    valid_vc = set((taxonomy.get("value_chain") or {}).keys()) or {"other"}
    valid_et = set((taxonomy.get("entity_types") or {}).keys()) or {"private_startup"}
    companies: dict[str, Company] = {}
    investors: dict[str, Investor] = {}
    files = list(WATCHLIST_FILES)
    if not files[0].exists():  # a fresh public clone: fall back to the sample panel so the pipeline still runs
        files[0] = CONFIG_DIR / "examples" / "watchlist.yaml"
    for path in files:
        data = _load_yaml(path)
        for raw in data.get("companies") or []:
            # v2 files used sub_vertical; accept it as a fallback so old accepted-lists still load.
            vc = raw.get("value_chain") or ("energy_software" if raw.get("sub_vertical") else "other")
            if vc not in valid_vc:
                raise ValueError(f"{path.name}: '{raw.get('name')}' has unknown value_chain '{vc}'. Valid: {sorted(valid_vc)}")
            et = raw.get("entity_type") or "private_startup"
            if et not in valid_et:
                raise ValueError(f"{path.name}: '{raw.get('name')}' has unknown entity_type '{et}'. Valid: {sorted(valid_et)}")
            c = Company(
                name=raw["name"], domain=raw.get("domain"), entity_type=et, value_chain=vc,
                hq_country=raw.get("hq_country"), region=raw.get("region"), ticker=raw.get("ticker"),
                aliases=[str(a) for a in (raw.get("aliases") or [])], notes=raw.get("notes"),
                status=raw.get("status") or "active",
            )
            companies[c.slug] = c
        for raw in data.get("investors") or []:
            inv = Investor(
                name=raw["name"], domain=raw.get("domain"), fund_type=raw.get("fund_type") or "unknown",
                stage_focus=list(raw.get("stage_focus") or []), energy_thesis=raw.get("energy_thesis"),
                conflict_risk=raw.get("conflict_risk"), aliases=[str(a) for a in (raw.get("aliases") or [])],
                notes=raw.get("notes"),
            )
            investors[inv.slug] = inv
    return list(companies.values()), list(investors.values())


def append_accepted_company(company: dict[str, Any]) -> None:
    path = CONFIG_DIR / "watchlist.accepted.yaml"
    data = _load_yaml(path)
    data.setdefault("companies", [])
    data["companies"].append(company)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("# 由 `radar accept <候選名稱>` 自動維護。不要手動編輯；要改請搬到 watchlist.yaml。\n")
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
