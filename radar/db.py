"""SQLite storage. One file, committed to the (private) data repo, so the history is versioned.

Tables fall into three groups (see docs/SPEC-v3.md §2.3):
  machine facts      companies, investors, signals, entity_mentions, relations, funding_rounds, candidates, runs
  analyst judgment   analyst_notes, decision_log, weekly_views   (private: never leave the data repo)
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH, Company, Investor, slugify

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  slug TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT,
  entity_type TEXT NOT NULL DEFAULT 'private_startup',
  value_chain TEXT NOT NULL DEFAULT 'other',
  hq_country TEXT,
  region TEXT,
  ticker TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  notes TEXT,
  added_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_aliases (
  company_slug TEXT NOT NULL REFERENCES companies(slug) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  PRIMARY KEY (company_slug, alias)
);
CREATE TABLE IF NOT EXISTS investors (
  slug TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT,
  fund_type TEXT NOT NULL DEFAULT 'unknown',
  stage_focus TEXT,
  energy_thesis TEXT,
  conflict_risk TEXT,
  status TEXT NOT NULL DEFAULT 'manual',
  notes TEXT,
  added_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investor_aliases (
  investor_slug TEXT NOT NULL REFERENCES investors(slug) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  PRIMARY KEY (investor_slug, alias)
);
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  resolved_url TEXT,
  title TEXT NOT NULL,
  title_norm TEXT NOT NULL,
  source TEXT,
  published_at TEXT,
  fetched_at TEXT NOT NULL,
  raw_summary TEXT,
  body TEXT,
  scope TEXT NOT NULL,
  query TEXT,
  seed_company_slug TEXT,
  seed_investor_slug TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  relevant INTEGER,
  signal_type TEXT,
  value_chain TEXT,
  importance INTEGER,
  summary TEXT,
  summary_zh TEXT,
  deal_value_usd REAL,
  capacity_mw REAL,
  extracted_json TEXT,
  extracted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_title ON signals(title_norm, source);
CREATE INDEX IF NOT EXISTS idx_signals_published ON signals(published_at);
CREATE TABLE IF NOT EXISTS signal_companies (
  signal_id INTEGER NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  company_slug TEXT NOT NULL REFERENCES companies(slug) ON DELETE CASCADE,
  PRIMARY KEY (signal_id, company_slug)
);
CREATE TABLE IF NOT EXISTS signal_investors (
  signal_id INTEGER NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  investor_slug TEXT NOT NULL REFERENCES investors(slug) ON DELETE CASCADE,
  PRIMARY KEY (signal_id, investor_slug)
);
CREATE TABLE IF NOT EXISTS entity_mentions (
  id INTEGER PRIMARY KEY,
  signal_id INTEGER NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  name_raw TEXT NOT NULL,
  name_norm TEXT NOT NULL,
  domain TEXT,
  entity_type TEXT,
  role TEXT,
  company_slug TEXT REFERENCES companies(slug) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_mentions_norm ON entity_mentions(name_norm);
CREATE TABLE IF NOT EXISTS relations (
  id INTEGER PRIMARY KEY,
  subject_slug TEXT REFERENCES companies(slug) ON DELETE SET NULL,
  subject_name TEXT NOT NULL,
  object_slug TEXT REFERENCES companies(slug) ON DELETE SET NULL,
  object_name TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  value_usd REAL,
  capacity_mw REAL,
  term_years REAL,
  signal_id INTEGER REFERENCES signals(id) ON DELETE SET NULL,
  confidence REAL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  mentions INTEGER NOT NULL DEFAULT 1,
  UNIQUE (subject_name, object_name, relation_type)
);
CREATE TABLE IF NOT EXISTS funding_rounds (
  id INTEGER PRIMARY KEY,
  company_slug TEXT REFERENCES companies(slug) ON DELETE SET NULL,
  company_name_raw TEXT NOT NULL,
  announced_on TEXT,
  round_type TEXT NOT NULL DEFAULT 'undisclosed',
  amount_raw TEXT,
  currency TEXT,
  amount_usd REAL,
  signal_id INTEGER REFERENCES signals(id) ON DELETE SET NULL,
  confidence TEXT,
  source_url TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS round_investors (
  round_id INTEGER NOT NULL REFERENCES funding_rounds(id) ON DELETE CASCADE,
  investor_slug TEXT NOT NULL REFERENCES investors(slug) ON DELETE CASCADE,
  role TEXT NOT NULL,
  PRIMARY KEY (round_id, investor_slug)
);
CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  name_norm TEXT NOT NULL UNIQUE,
  domain TEXT,
  entity_type TEXT,
  value_chain TEXT,
  why_relevant TEXT,
  source TEXT NOT NULL DEFAULT 'llm',
  score REAL NOT NULL DEFAULT 0,
  mentions INTEGER NOT NULL DEFAULT 1,
  first_signal_id INTEGER REFERENCES signals(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'proposed',
  proposed_week TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyst_notes (
  signal_id INTEGER PRIMARY KEY REFERENCES signals(id) ON DELETE CASCADE,
  importance_override INTEGER,
  relevant_override INTEGER,
  note_zh TEXT,
  note_en TEXT,
  deal_logic TEXT,
  decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_log (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  target TEXT NOT NULL,
  machine_value TEXT,
  human_value TEXT,
  reason TEXT,
  week TEXT,
  decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_views (
  week TEXT PRIMARY KEY,
  draft_zh TEXT,
  draft_en TEXT,
  public INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  published_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  stage TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  stats_json TEXT
);
"""

# Columns added after a table first shipped. migrate() adds any that are missing, so an old radar.db keeps working.
_MIGRATIONS: dict[str, dict[str, str]] = {
    "companies": {"entity_type": "TEXT NOT NULL DEFAULT 'private_startup'", "value_chain": "TEXT NOT NULL DEFAULT 'other'",
                  "region": "TEXT", "ticker": "TEXT"},
    "signals": {"value_chain": "TEXT", "summary_zh": "TEXT", "deal_value_usd": "REAL", "capacity_mw": "REAL",
                "capacity_kind": "TEXT", "project_stage": "TEXT", "location_name": "TEXT", "location_country": "TEXT",
                "grid_region": "TEXT", "lat": "REAL", "lng": "REAL", "location_precision": "TEXT", "event_scope": "TEXT"},
    "relations": {"value_source": "TEXT"},
    "candidates": {"entity_type": "TEXT", "value_chain": "TEXT", "source": "TEXT NOT NULL DEFAULT 'llm'"},
}
_RENAMES: dict[str, dict[str, str]] = {  # v2 name -> v3 name
    "companies": {"sub_vertical": "value_chain"},
    "candidates": {"sub_vertical": "value_chain"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def norm_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"\s+-\s+[^-]{2,40}$", "", t)  # strip trailing " - Source"
    t = re.sub(r"[^a-z0-9一-鿿]+", " ", t)
    return t.strip()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Bring a v2 database up to the v3 schema in place. Idempotent. Returns the changes applied."""
    applied: list[str] = []
    for table, renames in _RENAMES.items():
        cols = _columns(conn, table)
        for old, new in renames.items():
            if old in cols and new not in cols:
                conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
                applied.append(f"{table}.{old}->{new}")
    for table, cols in _MIGRATIONS.items():
        have = _columns(conn, table)
        for col, decl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                applied.append(f"{table}.{col}")
    if applied:
        # v2 companies were all energy-software startups
        conn.execute("UPDATE companies SET value_chain='energy_software' WHERE value_chain IN ("
                     "'vpp_asset_optimization','grid_capacity_siting','forecasting','bess_optimization',"
                     "'ev_grid_integration','data_center_energy','energy_trading')")
        conn.commit()
    return applied


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


# ---------- watchlist sync ----------

def sync_watchlist(conn: sqlite3.Connection, companies: Iterable[Company], investors: Iterable[Investor]) -> dict[str, int]:
    ts = now_iso()
    n_c = n_i = 0
    for c in companies:
        conn.execute(
            """INSERT INTO companies (slug, name, domain, entity_type, value_chain, hq_country, region, ticker, status,
                 notes, added_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(slug) DO UPDATE SET name=excluded.name, domain=excluded.domain,
                 entity_type=excluded.entity_type, value_chain=excluded.value_chain, hq_country=excluded.hq_country,
                 region=excluded.region, ticker=excluded.ticker, status=excluded.status,
                 notes=COALESCE(excluded.notes, companies.notes), updated_at=excluded.updated_at""",
            (c.slug, c.name, c.domain, c.entity_type, c.value_chain, c.hq_country, c.region, c.ticker, c.status,
             c.notes, ts, ts),
        )
        conn.execute("DELETE FROM company_aliases WHERE company_slug=?", (c.slug,))
        for alias in {c.name, *c.aliases}:
            conn.execute("INSERT OR IGNORE INTO company_aliases VALUES (?,?)", (c.slug, alias))
        n_c += 1
    for inv in investors:
        conn.execute(
            """INSERT INTO investors (slug, name, domain, fund_type, stage_focus, energy_thesis, conflict_risk,
                 status, notes, added_at, updated_at)
               VALUES (?,?,?,?,?,?,?,'manual',?,?,?)
               ON CONFLICT(slug) DO UPDATE SET name=excluded.name, domain=excluded.domain,
                 fund_type=excluded.fund_type, stage_focus=excluded.stage_focus,
                 energy_thesis=excluded.energy_thesis, conflict_risk=excluded.conflict_risk,
                 status='manual', notes=excluded.notes, updated_at=excluded.updated_at""",
            (inv.slug, inv.name, inv.domain, inv.fund_type, json.dumps(inv.stage_focus), inv.energy_thesis,
             inv.conflict_risk, inv.notes, ts, ts),
        )
        conn.execute("DELETE FROM investor_aliases WHERE investor_slug=?", (inv.slug,))
        for alias in {inv.name, *inv.aliases}:
            conn.execute("INSERT OR IGNORE INTO investor_aliases VALUES (?,?)", (inv.slug, alias))
        n_i += 1
    conn.commit()
    return {"companies": n_c, "investors": n_i}


def ensure_investor(conn: sqlite3.Connection, name: str) -> str:
    """Return slug for an investor, auto-creating a row (status='auto') if unknown."""
    slug = slugify(name)
    row = conn.execute("SELECT slug FROM investors WHERE slug=?", (slug,)).fetchone()
    if row:
        return slug
    ts = now_iso()
    conn.execute("INSERT INTO investors (slug, name, status, added_at, updated_at) VALUES (?,?,'auto',?,?)",
                 (slug, name, ts, ts))
    conn.execute("INSERT OR IGNORE INTO investor_aliases VALUES (?,?)", (slug, name))
    return slug


# ---------- signals ----------

def insert_signal(conn: sqlite3.Connection, item: dict[str, Any]) -> int | None:
    """Insert a collected item. Returns new id, or None if it is a duplicate."""
    title_norm = norm_title(item["title"])
    dup = conn.execute("SELECT id FROM signals WHERE url=? OR (title_norm=? AND title_norm != '')",
                       (item["url"], title_norm)).fetchone()
    if dup:
        return None
    cur = conn.execute(
        """INSERT INTO signals (url, title, title_norm, source, published_at, fetched_at, raw_summary, body,
             scope, query, seed_company_slug, seed_investor_slug)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (item["url"], item["title"], title_norm, item.get("source"), item.get("published_at"), now_iso(),
         item.get("raw_summary"), item.get("body"), item["scope"], item.get("query"),
         item.get("seed_company_slug"), item.get("seed_investor_slug")),
    )
    return cur.lastrowid


def update_signal_body(conn: sqlite3.Connection, signal_id: int, resolved_url: str | None, body: str | None) -> None:
    conn.execute("UPDATE signals SET resolved_url=?, body=? WHERE id=?", (resolved_url, body, signal_id))


def new_signals(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM signals WHERE status='new' ORDER BY published_at DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def save_extraction(conn: sqlite3.Connection, signal_id: int, data: dict[str, Any]) -> None:
    loc = data.get("location") or {}
    conn.execute(
        """UPDATE signals SET status='extracted', relevant=?, signal_type=?, value_chain=?, importance=?,
             summary=?, summary_zh=?, deal_value_usd=?, capacity_mw=?, capacity_kind=?, project_stage=?,
             location_name=?, location_country=?, grid_region=?, lat=?, lng=?, location_precision=?, event_scope=?,
             extracted_json=?, extracted_at=? WHERE id=?""",
        (1 if data.get("relevant") else 0, data.get("signal_type"), data.get("value_chain"), data.get("importance"),
         data.get("summary_en") or data.get("summary"), data.get("summary_zh"),
         data.get("deal_value_usd"), data.get("capacity_mw"), data.get("capacity_kind"), data.get("project_stage"),
         loc.get("name"), loc.get("country"), loc.get("grid_region"), loc.get("lat"), loc.get("lng"), loc.get("precision"), data.get("event_scope"),
         json.dumps(data, ensure_ascii=False), now_iso(), signal_id),
    )


def link_signal_company(conn: sqlite3.Connection, signal_id: int, slug: str) -> None:
    conn.execute("INSERT OR IGNORE INTO signal_companies VALUES (?,?)", (signal_id, slug))


def link_signal_investor(conn: sqlite3.Connection, signal_id: int, slug: str) -> None:
    conn.execute("INSERT OR IGNORE INTO signal_investors VALUES (?,?)", (signal_id, slug))


def insert_mention(conn: sqlite3.Connection, signal_id: int, name_raw: str, name_norm: str, domain: str | None,
                   entity_type: str | None, role: str | None, company_slug: str | None) -> None:
    conn.execute(
        "INSERT INTO entity_mentions (signal_id, name_raw, name_norm, domain, entity_type, role, company_slug) VALUES (?,?,?,?,?,?,?)",
        (signal_id, name_raw, name_norm, domain, entity_type, role, company_slug))


# ---------- relations ----------

def upsert_relation(conn: sqlite3.Connection, *, subject_slug: str | None, subject_name: str, object_slug: str | None,
                    object_name: str, relation_type: str, value_usd: float | None, capacity_mw: float | None,
                    term_years: float | None, signal_id: int, confidence: float | None, seen: str,
                    value_source: str | None = None) -> bool:
    """Insert or refresh a relation. Returns True when it is new."""
    row = conn.execute("SELECT id FROM relations WHERE subject_name=? AND object_name=? AND relation_type=?",
                       (subject_name, object_name, relation_type)).fetchone()
    if row:
        conn.execute(
            """UPDATE relations SET last_seen=MAX(last_seen, ?), mentions=mentions+1,
                 value_usd=COALESCE(?, value_usd), capacity_mw=COALESCE(?, capacity_mw), term_years=COALESCE(?, term_years),
                 subject_slug=COALESCE(subject_slug, ?), object_slug=COALESCE(object_slug, ?),
                 confidence=MAX(COALESCE(confidence,0), COALESCE(?,0)),
                 value_source=CASE WHEN ?='disclosed' OR value_source IS NULL THEN ? ELSE value_source END WHERE id=?""",
            (seen, value_usd, capacity_mw, term_years, subject_slug, object_slug, confidence, value_source, value_source, row["id"]))
        return False
    conn.execute(
        """INSERT INTO relations (subject_slug, subject_name, object_slug, object_name, relation_type, value_usd,
             capacity_mw, term_years, signal_id, confidence, first_seen, last_seen, value_source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (subject_slug, subject_name, object_slug, object_name, relation_type, value_usd, capacity_mw, term_years,
         signal_id, confidence, seen, seen, value_source))
    return True


# ---------- funding ----------

def find_similar_round(conn: sqlite3.Connection, company_slug: str | None, company_name_raw: str,
                       round_type: str, amount_usd: float | None, announced_on: str | None) -> sqlite3.Row | None:
    """Same company + same round type within 45 days, with amounts within 15%, is the same round."""
    rows = conn.execute(
        """SELECT * FROM funding_rounds
           WHERE (company_slug IS NOT NULL AND company_slug=?) OR lower(company_name_raw)=lower(?)""",
        (company_slug, company_name_raw)).fetchall()
    for r in rows:
        if r["round_type"] != round_type and round_type != "undisclosed" and r["round_type"] != "undisclosed":
            continue
        if amount_usd and r["amount_usd"]:
            if abs(amount_usd - r["amount_usd"]) / max(amount_usd, r["amount_usd"]) > 0.15:
                continue
        if announced_on and r["announced_on"]:
            try:
                d1 = datetime.fromisoformat(announced_on)
                d2 = datetime.fromisoformat(r["announced_on"])
                if abs((d1 - d2).days) > 45:
                    continue
            except ValueError:
                pass
        return r
    return None


def insert_round(conn: sqlite3.Connection, **kw: Any) -> int:
    cur = conn.execute(
        """INSERT INTO funding_rounds (company_slug, company_name_raw, announced_on, round_type, amount_raw,
             currency, amount_usd, signal_id, confidence, source_url, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (kw.get("company_slug"), kw["company_name_raw"], kw.get("announced_on"), kw.get("round_type") or "undisclosed",
         kw.get("amount_raw"), kw.get("currency"), kw.get("amount_usd"), kw.get("signal_id"),
         kw.get("confidence"), kw.get("source_url"), now_iso()))
    return cur.lastrowid


def link_round_investor(conn: sqlite3.Connection, round_id: int, investor_slug: str, role: str) -> None:
    conn.execute("INSERT OR IGNORE INTO round_investors VALUES (?,?,?)", (round_id, investor_slug, role))


# ---------- candidates ----------

def upsert_candidate(conn: sqlite3.Connection, name: str, score: float, week: str, signal_id: int | None,
                     domain: str | None, value_chain: str | None, why: str | None,
                     entity_type: str | None = None, source: str = "llm") -> None:
    name_norm = slugify(name)
    ts = now_iso()
    conn.execute(
        """INSERT INTO candidates (name, name_norm, domain, entity_type, value_chain, why_relevant, source, score, mentions,
             first_signal_id, status, proposed_week, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,1,?,'proposed',?,?,?)
           ON CONFLICT(name_norm) DO UPDATE SET
             score = CASE WHEN candidates.status='proposed' THEN MAX(candidates.score, excluded.score) + 0.5
                          ELSE candidates.score END,
             mentions = candidates.mentions + 1,
             domain = COALESCE(candidates.domain, excluded.domain),
             entity_type = COALESCE(candidates.entity_type, excluded.entity_type),
             value_chain = COALESCE(candidates.value_chain, excluded.value_chain),
             why_relevant = COALESCE(excluded.why_relevant, candidates.why_relevant),
             updated_at = excluded.updated_at""",
        (name, name_norm, domain, entity_type, value_chain, why, source, score, signal_id, week, ts, ts))


def set_candidate_status(conn: sqlite3.Connection, name: str, status: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM candidates WHERE name_norm=?", (slugify(name),)).fetchone()
    if not row:
        return None
    conn.execute("UPDATE candidates SET status=?, updated_at=? WHERE id=?", (status, now_iso(), row["id"]))
    conn.commit()
    return row


# ---------- analyst judgment (private) ----------

def upsert_analyst_note(conn: sqlite3.Connection, signal_id: int, *, importance_override: int | None = None,
                        relevant_override: bool | None = None, note_zh: str | None = None, note_en: str | None = None,
                        deal_logic: str | None = None) -> None:
    conn.execute(
        """INSERT INTO analyst_notes (signal_id, importance_override, relevant_override, note_zh, note_en, deal_logic, decided_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(signal_id) DO UPDATE SET
             importance_override=COALESCE(excluded.importance_override, analyst_notes.importance_override),
             relevant_override=COALESCE(excluded.relevant_override, analyst_notes.relevant_override),
             note_zh=COALESCE(excluded.note_zh, analyst_notes.note_zh),
             note_en=COALESCE(excluded.note_en, analyst_notes.note_en),
             deal_logic=COALESCE(excluded.deal_logic, analyst_notes.deal_logic),
             decided_at=excluded.decided_at""",
        (signal_id, importance_override, None if relevant_override is None else int(relevant_override),
         note_zh, note_en, deal_logic, now_iso()))


def log_decision(conn: sqlite3.Connection, kind: str, target: str, machine_value: Any, human_value: Any,
                 reason: str | None, week: str | None) -> None:
    conn.execute(
        "INSERT INTO decision_log (kind, target, machine_value, human_value, reason, week, decided_at) VALUES (?,?,?,?,?,?,?)",
        (kind, target, None if machine_value is None else str(machine_value),
         None if human_value is None else str(human_value), reason, week, now_iso()))


def save_weekly_view(conn: sqlite3.Connection, week: str, draft_zh: str | None, draft_en: str | None,
                     public: bool | None = None) -> None:
    conn.execute(
        """INSERT INTO weekly_views (week, draft_zh, draft_en, public, updated_at) VALUES (?,?,?,?,?)
           ON CONFLICT(week) DO UPDATE SET draft_zh=COALESCE(excluded.draft_zh, weekly_views.draft_zh),
             draft_en=COALESCE(excluded.draft_en, weekly_views.draft_en),
             public=COALESCE(?, weekly_views.public), updated_at=excluded.updated_at""",
        (week, draft_zh, draft_en, int(bool(public)), now_iso(), None if public is None else int(public)))


# ---------- runs ----------

def start_run(conn: sqlite3.Connection, stage: str) -> int:
    cur = conn.execute("INSERT INTO runs (stage, started_at) VALUES (?,?)", (stage, now_iso()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, stats: dict[str, Any]) -> None:
    conn.execute("UPDATE runs SET finished_at=?, stats_json=? WHERE id=?", (now_iso(), json.dumps(stats), run_id))
    conn.commit()


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]
