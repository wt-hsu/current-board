"""LLM extraction: turn a raw news item into a structured Signal using Claude structured outputs.

The schema enums and the importance scale are built from config/taxonomy.yaml, so editing the YAML
(for example after reviewing the decision log) changes what the model is asked to do. No code edit needed.
"""

from __future__ import annotations

import logging
import json
import os
import sys
import sqlite3
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from . import db
from .config import ROOT, importance_scale_text, load_taxonomy
from .resolve import AliasIndex, apply_extraction, propose_from_cooccurrence

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("RADAR_MODEL", "claude-sonnet-5-5")


class MissingApiKey(RuntimeError):
    pass


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Tiny .env loader so we don't need python-dotenv. Does not override existing env."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_client():
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise MissingApiKey(
            "ANTHROPIC_API_KEY is not set. Put it in .env at the repo root (ANTHROPIC_API_KEY=sk-ant-...) "
            "for local runs, and as a repository secret named ANTHROPIC_API_KEY for GitHub Actions."
        )
    import anthropic

    return anthropic.Anthropic()


# ---------- schema (enums come from the taxonomy so the vocabulary lives in one place) ----------

_tax = load_taxonomy()


def _enum(name: str, kind: str, fallback: str) -> type[Enum]:
    codes = _tax.get(kind) or {}
    keys = list(codes.keys()) if isinstance(codes, dict) else list(codes)
    return Enum(name, {k: k for k in (keys or [fallback])})


SignalType = _enum("SignalType", "signal_types", "other")
ValueChain = _enum("ValueChain", "value_chain", "other")
EntityType = _enum("EntityType", "entity_types", "private_startup")
RelationType = _enum("RelationType", "relation_types", "partners_with")
RoundType = _enum("RoundType", "round_types", "undisclosed")


class EntityMention(BaseModel):
    name: str = Field(description="Organisation name as written in the article")
    domain: Optional[str] = Field(default=None, description="Website domain if stated, e.g. constellationenergy.com")
    entity_type: EntityType = Field(description="What kind of organisation this is")
    role: str = Field(description="One of: subject, buyer, seller, supplier, customer, partner, acquirer, acquired, investor, regulator, other")


class InvestorMention(BaseModel):
    name: str
    role: str = Field(description="One of: lead, participant, mentioned")


class FundingRound(BaseModel):
    company_name: str = Field(description="The company that raised the money")
    round_type: RoundType
    amount_raw: Optional[str] = Field(default=None, description="Amount exactly as written, e.g. '$232 million', '€11M'")
    currency: Optional[str] = Field(default=None, description="ISO code: USD, EUR, GBP ...")
    amount_usd: Optional[float] = Field(default=None, description="Approximate amount converted to USD, plain number")
    announced_on: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD if stated, else null")
    confidence: str = Field(description="high if the article is primarily about this round, medium if mentioned in passing, low if inferred")


class Relation(BaseModel):
    subject: str = Field(description="Who acts, e.g. 'Microsoft'")
    object: str = Field(description="Who it acts on, e.g. 'Constellation Energy'")
    relation_type: RelationType
    value_usd: Optional[float] = Field(default=None, description="Deal value in USD if stated or clearly derivable, else null")
    capacity_mw: Optional[float] = Field(default=None, description="Power capacity in MW if stated (1 GW = 1000), else null")
    term_years: Optional[float] = Field(default=None, description="Contract length in years if stated, else null")
    value_source: str = Field(default="estimated", description="Where the money/MW figure comes from: 'disclosed' (company filing, press release, or the parties on record), 'reported' (media citing unnamed sources or 'according to'), 'estimated' (your own derivation, or no figure)")
    confidence: float = Field(description="0.0–1.0: how explicitly the article states this relation")


class NewEntityCandidate(BaseModel):
    name: str
    domain: Optional[str] = None
    entity_type: EntityType
    value_chain: ValueChain
    why_relevant: str = Field(description="One sentence: why this organisation belongs on a radar of the power & infrastructure behind AI")


class Location(BaseModel):
    name: Optional[str] = Field(default=None, description="Place of the project or contract as written, e.g. 'New Albany, Ohio' or 'Johor'")
    country: Optional[str] = Field(default=None, description="ISO 3166-1 alpha-2, e.g. US, MY, JP")
    grid_region: Optional[str] = Field(default=None, description="Grid or market region if known: PJM, ERCOT, MISO, CAISO, SPP, NYISO, ISO-NE, SERC, WECC, or a country/state grid name outside the US; else null")
    lat: Optional[float] = Field(default=None, description="Approximate latitude of the named place if you know it, else null")
    lng: Optional[float] = Field(default=None, description="Approximate longitude, else null")
    precision: str = Field(default="unknown", description="One of: exact, city, region, country, unknown")


class SignalExtraction(BaseModel):
    relevant: bool = Field(description="True if the article is about the power, grid, generation, data-center infrastructure or energy-software layer that serves AI compute, or about tracked entities acting in that layer")
    signal_type: SignalType
    value_chain: ValueChain = Field(description="The single value-chain layer this article mainly concerns")
    importance: int = Field(description="1–5 per the importance scale in the system prompt")
    summary_en: str = Field(description="Two sentences, English, factual, no hype. Name the parties, amounts, MW and dates.")
    summary_zh: str = Field(description="同樣內容的繁體中文摘要，兩句，事實陳述，保留金額與數字")
    deal_value_usd: Optional[float] = Field(default=None, description="Headline money figure of the article in USD (deal, contract, capex, raise), else null")
    capacity_mw: Optional[float] = Field(default=None, description="Headline power figure in MW (1 GW = 1000 MW), else null")
    capacity_kind: Optional[str] = Field(default=None, description="What kind of MW capacity_mw is: 'nameplate' for generation/storage capacity, 'it_load' for data-center IT or critical load, 'grid' for transmission/interconnection capacity, else null")
    project_stage: Optional[str] = Field(default=None, description="Stage of the project or deal the article is mainly about: 'announced', 'contracted' (PPA/contract signed, financing closed), 'under_construction', 'operational', else null")
    location: Optional[Location] = Field(default=None, description="Where the project, plant, campus or contract is physically located. Null if the article names no place.")
    entities: list[EntityMention] = Field(default_factory=list, description="Every organisation that acts in the article")
    investors: list[InvestorMention] = Field(default_factory=list)
    funding: Optional[FundingRound] = Field(default=None, description="Only for a startup funding round")
    relations: list[Relation] = Field(default_factory=list, description="Who did what to whom. Only relations the article states.")
    new_entity_candidate: Optional[NewEntityCandidate] = Field(
        default=None,
        description="Only if the article's main subject is an organisation NOT in the watchlist that clearly belongs in this value chain. Otherwise null.",
    )


def build_system_prompt(taxonomy: dict[str, Any] | None = None) -> str:
    tax = taxonomy or _tax
    layers = "\n".join(
        f"- {code}: {v.get('label_en', code)} — {v.get('scope', '')}" for code, v in (tax.get("value_chain") or {}).items()
    )
    return f"""You are an analyst maintaining Current Board, a weekly radar of the power and infrastructure behind AI:
who supplies the electricity for AI compute, who pays for it, and why now. You classify news into a fixed vocabulary.

VALUE CHAIN LAYERS (pick the one the article mainly concerns):
{layers}

IMPORTANCE SCALE (1–5):
{importance_scale_text(tax, 'en')}

RULES
- Extract facts only from the provided text. Never invent amounts, dates, capacities or names.
- Convert GW to MW (1 GW = 1000 MW). Convert currencies to approximate USD when the article gives a figure.
- A relation needs an explicit subject, object and action in the text. Do not infer relations from context.
- If the text is a newsletter or roundup covering many items, pick the single most relevant item as the subject.
- Mark irrelevant: consumer gadgets, generic AI model news with no power/infrastructure angle, oil & gas upstream,
  unrelated finance, crypto mining unless it is converting to AI compute.
- A tracked entity acting outside this layer (e.g. a hyperscaler launching a chatbot) is irrelevant.
- summary_zh must be Traditional Chinese (繁體中文), same facts as summary_en.
- capacity_kind: a power plant, PPA, battery or SMR figure is 'nameplate'; a data-center campus or AI factory figure
  is 'it_load'; transformer, line or interconnection figures are 'grid'. Never add the two kinds together.
- project_stage: 'announced' for plans and intentions; 'contracted' once a PPA, offtake, financing or definitive
  agreement is signed; 'under_construction' when ground has broken; 'operational' when energised or serving load.
- value_source on each relation: 'disclosed' only when the parties themselves state the figure (filing, release,
  on-record executive); 'reported' when the article attributes it to sources or another outlet; 'estimated' otherwise.
- location: the place of the asset or campus, not the company's headquarters."""


SYSTEM_PROMPT = build_system_prompt()


def build_user_prompt(signal: sqlite3.Row, watchlist_names: list[str]) -> str:
    parts = [
        f"Watchlist entities (match these names when present): {', '.join(watchlist_names)}",
        f"Collected for: {signal['scope']} / query: {signal['query']}",
        f"Title: {signal['title']}",
        f"Source: {signal['source'] or 'unknown'}",
        f"Published: {signal['published_at'] or 'unknown'}",
        f"URL: {signal['resolved_url'] or signal['url']}",
    ]
    if signal["raw_summary"]:
        parts.append(f"RSS summary: {signal['raw_summary']}")
    if signal["body"]:
        parts.append(f"Article text:\n{signal['body']}")
    else:
        parts.append("Article text: (not available; rely on title and summary, lower your confidence accordingly)")
    return "\n".join(parts)


# Output mode. "json" (default) puts the JSON Schema in the system prompt and validates the model's JSON with
# pydantic — the schema is too large for the API's strict structured-output grammar ("compiled grammar is too
# large"), so strict mode is opt-in via RADAR_STRICT=1 for a smaller schema in the future.
STRICT = os.environ.get("RADAR_STRICT", "") == "1"
_SCHEMA_JSON = json.dumps(SignalExtraction.model_json_schema(), ensure_ascii=False)
JSON_SYSTEM_PROMPT = (
    SYSTEM_PROMPT
    + "\n\nOUTPUT FORMAT\nRespond with ONE JSON object and nothing else: no prose, no markdown fences. It must validate "
    + "against this JSON Schema (use null for unknown optional fields, use the exact enum codes):\n"
    + _SCHEMA_JSON
)


def _json_from_text(text: str) -> str:
    """Tolerate a stray fence or sentence around the object."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in model output")
    return text[start:end + 1]


def extract_one(client, signal: sqlite3.Row, watchlist_names: list[str], model: str = DEFAULT_MODEL) -> dict[str, Any]:
    user = build_user_prompt(signal, watchlist_names)
    if STRICT:
        msg = client.messages.parse(model=model, max_tokens=1500, system=SYSTEM_PROMPT,
                                    messages=[{"role": "user", "content": user}], output_format=SignalExtraction)
        parsed: SignalExtraction = msg.parsed_output
        if parsed is None:
            raise ValueError(f"no structured output (stop_reason={msg.stop_reason})")
        return to_record(parsed)
    msg = client.messages.create(model=model, max_tokens=2000, system=JSON_SYSTEM_PROMPT,
                                 messages=[{"role": "user", "content": user}])
    text = "".join(getattr(b, "text", "") for b in msg.content)
    parsed = SignalExtraction.model_validate_json(_json_from_text(text))
    return to_record(parsed)


def to_record(parsed: SignalExtraction) -> dict[str, Any]:
    data = parsed.model_dump(mode="json")
    data["importance"] = max(1, min(5, int(data.get("importance") or 1)))
    data["summary"] = data.get("summary_en")  # legacy column name
    return data


def iso_week(d: date | None = None) -> str:
    d = d or date.today()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def run_extraction(conn: sqlite3.Connection, client=None, limit: int | None = None,
                   model: str = DEFAULT_MODEL, week: str | None = None) -> dict[str, int]:
    client = client or get_client()
    week = week or iso_week()
    index = AliasIndex(conn)
    names = [r["name"] for r in conn.execute("SELECT name FROM companies WHERE status='active' ORDER BY name")]
    stats = {"processed": 0, "relevant": 0, "failed": 0, "rounds": 0, "relations": 0, "candidates": 0, "unmatched": 0}
    # API calls run in parallel (RADAR_WORKERS, default 6); every database write stays on this thread, in order.
    from concurrent.futures import ThreadPoolExecutor
    workers = max(1, int(os.environ.get("RADAR_WORKERS", "6")))
    signals = db.new_signals(conn, limit)
    total = len(signals)

    def call(signal):
        try:
            return signal, extract_one(client, signal, names, model), None
        except Exception as exc:  # noqa: BLE001 - keep going, mark the row
            return signal, None, exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (signal, data, exc) in enumerate(pool.map(call, signals), 1):
            if exc is not None:
                log.warning("extraction failed for signal %s (%s): %s", signal["id"], signal["title"][:60], exc)
                conn.execute("UPDATE signals SET status='failed' WHERE id=?", (signal["id"],))
                conn.commit()
                stats["failed"] += 1
                continue
            db.save_extraction(conn, signal["id"], data)
            s = apply_extraction(conn, signal, data, index, week)
            conn.commit()
            stats["processed"] += 1
            stats["relevant"] += int(bool(data.get("relevant")))
            for k in ("rounds", "relations", "candidates", "unmatched"):
                stats[k] += s[k]
            if i % 50 == 0:
                print(f"extract: {i}/{total} · relevant {stats['relevant']} · failed {stats['failed']}", file=sys.stderr)
    if stats["processed"]:
        stats["candidates_cooccurrence"] = propose_from_cooccurrence(conn, week)
        conn.commit()
    return stats
