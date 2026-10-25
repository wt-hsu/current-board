"""Entity resolution: map names the LLM extracted onto watchlist entities, record relations and
funding rounds, and propose new entities as candidates (three detection rules, see SPEC-v3 §2.2)."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db

_SUFFIXES = {"inc", "inc.", "ltd", "ltd.", "llc", "gmbh", "plc", "corp", "corp.", "corporation", "co", "co.",
             "company", "limited", "sas", "bv", "b.v.", "ab", "oy", "se", "ag", "nv", "holdings", "group",
             "technologies", "technology", "labs"}

# Relations substantive enough that an unknown counterparty becomes a candidate on its own.
_STRONG_RELATIONS = {"buys_power_from", "supplies_to", "invests_in", "acquires", "builds_for"}


def normalize_name(name: str) -> str:
    text = name.lower().strip()
    text = re.sub(r"[^\w\s&.-]", " ", text)
    tokens = [t for t in re.split(r"\s+", text) if t]
    # strip legal suffixes but never reduce a name to nothing. "Energy" is deliberately NOT a suffix:
    # Siemens Energy and Siemens are different companies; use aliases for short forms instead.
    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return re.sub(r"[^a-z0-9]+", "", "".join(tokens))


class AliasIndex:
    """In-memory lookup of normalized alias -> slug, rebuilt per extraction run."""

    def __init__(self, conn: sqlite3.Connection):
        self.companies: dict[str, str] = {}
        self.company_domains: dict[str, str] = {}
        self.investors: dict[str, str] = {}
        self.names: dict[str, str] = {}
        for row in conn.execute("SELECT company_slug, alias FROM company_aliases"):
            self.companies[normalize_name(row["alias"])] = row["company_slug"]
        for row in conn.execute("SELECT slug, name, domain FROM companies"):
            self.names[row["slug"]] = row["name"]
            if row["domain"]:
                self.company_domains[row["domain"].lower().removeprefix("www.")] = row["slug"]
        for row in conn.execute("SELECT investor_slug, alias FROM investor_aliases"):
            self.investors[normalize_name(row["alias"])] = row["investor_slug"]

    def match_company(self, name: str | None, domain: str | None = None) -> str | None:
        if domain:
            slug = self.company_domains.get(domain.lower().removeprefix("www.").split("/")[0])
            if slug:
                return slug
        if not name:
            return None
        return self.companies.get(normalize_name(name))

    def match_investor(self, name: str) -> str | None:
        return self.investors.get(normalize_name(name))


def candidate_score(data: dict[str, Any]) -> float:
    """Importance plus bonuses for money and megawatts. Big-company deals score like big rounds."""
    score = float(data.get("importance") or 1)
    funding = data.get("funding") or {}
    if funding:
        score += 2
        if (funding.get("amount_usd") or 0) >= 10_000_000:
            score += 1
    value = data.get("deal_value_usd") or 0
    if value >= 1_000_000_000:
        score += 2
    elif value >= 100_000_000:
        score += 1
    if (data.get("capacity_mw") or 0) >= 100:
        score += 1
    return score


def apply_extraction(conn: sqlite3.Connection, signal: sqlite3.Row, data: dict[str, Any],
                     index: AliasIndex, week: str) -> dict[str, int]:
    """Write links, mentions, relations, rounds and candidates derived from one extraction."""
    stats = {"companies_linked": 0, "investors_linked": 0, "rounds": 0, "relations": 0, "candidates": 0, "unmatched": 0}
    sid = signal["id"]
    if not data.get("relevant"):
        return stats
    seen = (signal["published_at"] or db.now_iso())[:10]

    # entities -> links + mentions (mentions keep the unmatched names for the co-occurrence rule)
    matched: list[str] = []
    entity_types: dict[str, str] = {}
    for ent in data.get("entities") or data.get("companies") or []:
        name = (ent.get("name") or "").strip()
        if not name:
            continue
        slug = index.match_company(name, ent.get("domain"))
        db.insert_mention(conn, sid, name, normalize_name(name), ent.get("domain"), ent.get("entity_type"), ent.get("role"), slug)
        if slug:
            matched.append(slug)
        else:
            stats["unmatched"] += 1
            entity_types[normalize_name(name)] = ent.get("entity_type")
    if signal["seed_company_slug"] and signal["seed_company_slug"] not in matched:
        matched.append(signal["seed_company_slug"])
    for slug in dict.fromkeys(matched):
        db.link_signal_company(conn, sid, slug)
        stats["companies_linked"] += 1

    # investors
    investor_slugs: dict[str, str] = {}
    for inv in data.get("investors") or []:
        name = (inv.get("name") or "").strip()
        if not name:
            continue
        slug = index.match_investor(name) or db.ensure_investor(conn, name)
        index.investors[normalize_name(name)] = slug
        investor_slugs[slug] = inv.get("role") or "mentioned"
        db.link_signal_investor(conn, sid, slug)
        stats["investors_linked"] += 1
    if signal["seed_investor_slug"]:
        db.link_signal_investor(conn, sid, signal["seed_investor_slug"])

    # relations: who did what to whom; unknown counterparties of strong relations become candidates
    for rel in data.get("relations") or []:
        subj, obj = (rel.get("subject") or "").strip(), (rel.get("object") or "").strip()
        rtype = rel.get("relation_type")
        if not subj or not obj or not rtype or normalize_name(subj) == normalize_name(obj):
            continue
        s_slug, o_slug = index.match_company(subj), index.match_company(obj)
        is_new = db.upsert_relation(
            conn, subject_slug=s_slug, subject_name=index.names.get(s_slug, subj), object_slug=o_slug,
            object_name=index.names.get(o_slug, obj), relation_type=rtype, value_usd=rel.get("value_usd"), value_source=rel.get("value_source"),
            capacity_mw=rel.get("capacity_mw"), term_years=rel.get("term_years"), signal_id=sid,
            confidence=rel.get("confidence"), seen=seen)
        stats["relations"] += int(is_new)
        if rtype in _STRONG_RELATIONS and (s_slug or o_slug) and not (s_slug and o_slug):
            unknown = obj if s_slug else subj
            known = index.names.get(s_slug or o_slug, "")
            db.upsert_candidate(
                conn, unknown, candidate_score(data), week, sid, None, data.get("value_chain"),
                f"Counterparty of {known}: {rtype.replace('_', ' ')}", entity_types.get(normalize_name(unknown)),
                source="counterparty")
            stats["candidates"] += 1

    # funding (Sparks)
    funding = data.get("funding")
    if funding and (funding.get("company_name") or matched):
        raw_name = funding.get("company_name") or ""
        company_slug = index.match_company(raw_name) or (matched[0] if matched else None)
        if company_slug and not raw_name:
            raw_name = index.names.get(company_slug, raw_name)
        round_type = funding.get("round_type") or "undisclosed"
        existing = db.find_similar_round(conn, company_slug, raw_name, round_type, funding.get("amount_usd"), funding.get("announced_on"))
        if existing:
            round_id = existing["id"]
        else:
            round_id = db.insert_round(
                conn, company_slug=company_slug, company_name_raw=raw_name, announced_on=funding.get("announced_on"),
                round_type=round_type, amount_raw=funding.get("amount_raw"), currency=funding.get("currency"),
                amount_usd=funding.get("amount_usd"), signal_id=sid, confidence=funding.get("confidence"),
                source_url=signal["resolved_url"] or signal["url"])
            stats["rounds"] += 1
        for slug, role in investor_slugs.items():
            if role in ("lead", "participant"):
                db.link_round_investor(conn, round_id, slug, role)

    # explicit LLM proposal
    cand = data.get("new_entity_candidate") or data.get("new_company_candidate")
    if cand and cand.get("name") and not index.match_company(cand["name"], cand.get("domain")):
        db.upsert_candidate(conn, cand["name"], candidate_score(data), week, sid, cand.get("domain"),
                            cand.get("value_chain") or cand.get("sub_vertical"), cand.get("why_relevant"),
                            cand.get("entity_type"), source="llm")
        stats["candidates"] += 1
    return stats


def propose_from_cooccurrence(conn: sqlite3.Connection, week: str, days: int = 28, min_companies: int = 3,
                              accel_factor: float = 3.0) -> int:
    """Rules 1 and 3 from the spec: an unmatched name that co-occurs with >= N tracked entities in the window,
    or whose mention count accelerated >= 3x versus the previous window, becomes a candidate."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).date().isoformat()
    before = (now - timedelta(days=2 * days)).date().isoformat()
    n = 0
    rows = conn.execute("""
        SELECT m.name_norm, MIN(m.name_raw) AS name, MAX(m.domain) AS domain, MAX(m.entity_type) AS entity_type,
               COUNT(DISTINCT sc.company_slug) AS tracked, COUNT(DISTINCT m.signal_id) AS mentions,
               MIN(m.signal_id) AS first_sid, MAX(s.value_chain) AS value_chain
        FROM entity_mentions m
        JOIN signals s ON s.id = m.signal_id AND s.relevant = 1 AND COALESCE(s.published_at, s.fetched_at) >= ?
        LEFT JOIN signal_companies sc ON sc.signal_id = m.signal_id
        WHERE m.company_slug IS NULL
        GROUP BY m.name_norm""", (since,)).fetchall()
    for r in rows:
        if r["tracked"] >= min_companies:
            db.upsert_candidate(conn, r["name"], 3 + r["tracked"], week, r["first_sid"], r["domain"], r["value_chain"],
                                f"Co-occurs with {r['tracked']} tracked entities in the last {days} days",
                                r["entity_type"], source="cooccurrence")
            n += 1
            continue
        prev = conn.execute("""
            SELECT COUNT(DISTINCT m.signal_id) FROM entity_mentions m
            JOIN signals s ON s.id = m.signal_id AND s.relevant = 1
            WHERE m.name_norm = ? AND COALESCE(s.published_at, s.fetched_at) >= ? AND COALESCE(s.published_at, s.fetched_at) < ?""",
            (r["name_norm"], before, since)).fetchone()[0]
        if r["mentions"] >= 3 and r["mentions"] >= accel_factor * max(prev, 1):
            db.upsert_candidate(conn, r["name"], 3 + r["mentions"] / 2, week, r["first_sid"], r["domain"], r["value_chain"],
                                f"Mentions accelerated: {r['mentions']} in the last {days} days vs {prev} before",
                                r["entity_type"], source="acceleration")
            n += 1
    return n
