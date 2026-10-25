import sqlite3

from radar import db
from tests.conftest import make_item


def test_insert_dedupes_by_url_and_title(conn):
    assert db.insert_signal(conn, make_item()) is not None
    assert db.insert_signal(conn, make_item()) is None  # same url
    assert db.insert_signal(conn, make_item(url="https://other.com/b", title="Microsoft signs 20-year deal to restart Three Mile Island - ESG Today")) is None
    assert db.insert_signal(conn, make_item(url="https://other.com/c", title="Microsoft launches Texas plan")) is not None


def test_similar_round_merges_within_tolerance(conn):
    rid = db.insert_round(conn, company_slug="lunar-energy", company_name_raw="Lunar Energy", announced_on="2026-02-04",
                          round_type="series_c_plus", amount_usd=232e6)
    same = db.find_similar_round(conn, "lunar-energy", "Lunar Energy Inc", "series_c_plus", 230e6, "2026-02-06")
    assert same and same["id"] == rid
    assert db.find_similar_round(conn, "lunar-energy", "Lunar Energy", "series_c_plus", 50e6, "2026-02-06") is None
    assert db.find_similar_round(conn, "lunar-energy", "Lunar Energy", "series_c_plus", 232e6, "2026-06-01") is None
    assert db.find_similar_round(conn, "lunar-energy", "Lunar Energy", "undisclosed", None, None)["id"] == rid


def test_candidate_upsert_accumulates(conn):
    db.upsert_candidate(conn, "Amperon", 3.0, "2026-W41", None, None, "energy_software", "why", "private_startup")
    db.upsert_candidate(conn, "amperon", 4.0, "2026-W41", None, "amperon.co", None, None, source="counterparty")
    row = conn.execute("SELECT * FROM candidates WHERE name_norm='amperon'").fetchone()
    assert row["mentions"] == 2 and row["score"] == 4.5 and row["domain"] == "amperon.co"
    assert row["entity_type"] == "private_startup" and row["source"] == "llm"  # first writer wins for identity fields
    assert db.set_candidate_status(conn, "Amperon", "accepted")["name"] == "Amperon"


def test_relation_upsert_merges_and_counts(conn):
    new = db.upsert_relation(conn, subject_slug="microsoft", subject_name="Microsoft", object_slug="constellation-energy",
                             object_name="Constellation Energy", relation_type="buys_power_from", value_usd=None,
                             capacity_mw=835, term_years=20, signal_id=None, confidence=0.9, seen="2026-10-05")
    again = db.upsert_relation(conn, subject_slug="microsoft", subject_name="Microsoft", object_slug=None,
                               object_name="Constellation Energy", relation_type="buys_power_from", value_usd=16e9,
                               capacity_mw=None, term_years=None, signal_id=None, confidence=0.7, seen="2026-10-09")
    assert new is True and again is False
    r = conn.execute("SELECT * FROM relations").fetchone()
    assert r["mentions"] == 2 and r["value_usd"] == 16e9 and r["capacity_mw"] == 835 and r["last_seen"] == "2026-10-09"
    assert r["confidence"] == 0.9


def test_analyst_note_and_decision_log(conn):
    sid = db.insert_signal(conn, make_item())
    db.upsert_analyst_note(conn, sid, importance_override=5, note_zh="首例")
    db.upsert_analyst_note(conn, sid, note_en="first of its kind")  # merges, keeps the override
    n = conn.execute("SELECT * FROM analyst_notes WHERE signal_id=?", (sid,)).fetchone()
    assert n["importance_override"] == 5 and n["note_zh"] == "首例" and n["note_en"] == "first of its kind"
    db.log_decision(conn, "score", f"signal:{sid}", 3, 5, "state-level first", "2026-W41")
    assert conn.execute("SELECT human_value FROM decision_log").fetchone()[0] == "5"


def test_migrate_v2_database(tmp_path):
    """A v2 radar.db (sub_vertical columns, no relations table) opens and is upgraded in place."""
    path = tmp_path / "v2.db"
    raw = sqlite3.connect(path)
    raw.executescript("""
        CREATE TABLE companies (slug TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT, sub_vertical TEXT NOT NULL DEFAULT 'other',
          hq_country TEXT, status TEXT NOT NULL DEFAULT 'tracked', core_value_prop TEXT, tech_stack TEXT, traction_notes TEXT,
          notes TEXT, added_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO companies VALUES ('lunar-energy','Lunar Energy','lunarenergy.com','vpp_asset_optimization','US','tracked',NULL,NULL,NULL,'n','t','t');
        CREATE TABLE candidates (id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_norm TEXT NOT NULL UNIQUE, domain TEXT, sub_vertical TEXT,
          why_relevant TEXT, score REAL NOT NULL DEFAULT 0, mentions INTEGER NOT NULL DEFAULT 1, first_signal_id INTEGER,
          status TEXT NOT NULL DEFAULT 'proposed', proposed_week TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE signals (id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, resolved_url TEXT, title TEXT NOT NULL, title_norm TEXT NOT NULL,
          source TEXT, published_at TEXT, fetched_at TEXT NOT NULL, raw_summary TEXT, body TEXT, scope TEXT NOT NULL, query TEXT,
          seed_company_slug TEXT, seed_investor_slug TEXT, status TEXT NOT NULL DEFAULT 'new', relevant INTEGER, signal_type TEXT,
          importance INTEGER, summary TEXT, extracted_json TEXT, extracted_at TEXT);
    """)
    raw.commit(); raw.close()
    conn = db.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
    assert "value_chain" in cols and "sub_vertical" not in cols and "entity_type" in cols
    assert conn.execute("SELECT value_chain FROM companies").fetchone()[0] == "energy_software"
    assert {r[1] for r in conn.execute("PRAGMA table_info(signals)")} >= {"summary_zh", "deal_value_usd", "capacity_mw", "value_chain"}
    assert conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0
    assert db.migrate(conn) == []  # idempotent
    conn.close()
