from radar import db
from radar.resolve import AliasIndex, apply_extraction, candidate_score, normalize_name, propose_from_cooccurrence
from tests.conftest import make_item, nuclear_deal


def test_normalize_strips_suffixes_but_not_energy():
    assert normalize_name("Lunar Energy, Inc.") == normalize_name("lunar energy")
    assert normalize_name("Ogre AI") != normalize_name("Ogre")  # aliases handle short forms
    assert normalize_name("Siemens Energy") != normalize_name("Siemens")
    assert normalize_name("Constellation Energy Corp") == normalize_name("Constellation Energy")


def test_alias_and_domain_matching(conn):
    idx = AliasIndex(conn)
    assert idx.match_company("Gridshare") == "lunar-energy"
    assert idx.match_company("AZURE") == "microsoft"
    assert idx.match_company("Constellation") == "constellation-energy"
    assert idx.match_company("Unknown Co", "www.ogre.ai") == "ogre-ai"
    assert idx.match_company("Amperon") is None
    assert idx.match_investor("Lowercarbon Capital LLC") == "lowercarbon-capital"


def test_candidate_score_rewards_money_and_megawatts():
    assert candidate_score({"importance": 3}) == 3
    assert candidate_score({"importance": 3, "funding": {"amount_usd": 20e6}}) == 6
    assert candidate_score({"importance": 4, "deal_value_usd": 2e9, "capacity_mw": 500}) == 7


def test_apply_extraction_links_relations_and_counterparty(conn):
    sid = db.insert_signal(conn, make_item(scope="discovery", seed_company_slug=None))
    signal = conn.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
    idx = AliasIndex(conn)
    stats = apply_extraction(conn, signal, nuclear_deal(), idx, "2026-W41")
    assert stats["companies_linked"] == 2 and stats["unmatched"] == 1  # PJM is not on the panel
    assert stats["relations"] == 2 and stats["candidates"] == 1
    rels = {(r["subject_name"], r["relation_type"], r["object_name"]): r for r in conn.execute("SELECT * FROM relations")}
    msft = rels[("Microsoft", "buys_power_from", "Constellation Energy")]
    assert msft["subject_slug"] == "microsoft" and msft["object_slug"] == "constellation-energy" and msft["capacity_mw"] == 835
    # the unknown counterparty of a supplies_to relation became a candidate
    cand = conn.execute("SELECT * FROM candidates WHERE name='Holtec International'").fetchone()
    assert cand and cand["source"] == "counterparty" and cand["value_chain"] == "generation_nuclear"
    # mentions were kept, including the unmatched one
    assert conn.execute("SELECT COUNT(*) FROM entity_mentions WHERE company_slug IS NULL").fetchone()[0] == 1
    # a second article about the same deal does not duplicate the relation
    sid2 = db.insert_signal(conn, make_item(url="https://x.com/2", title="Constellation to restart Three Mile Island for Microsoft", scope="discovery", seed_company_slug=None))
    signal2 = conn.execute("SELECT * FROM signals WHERE id=?", (sid2,)).fetchone()
    stats2 = apply_extraction(conn, signal2, nuclear_deal(), idx, "2026-W41")
    assert stats2["relations"] == 0 and conn.execute("SELECT mentions FROM relations WHERE subject_name='Microsoft'").fetchone()[0] == 2


def test_funding_and_llm_candidate_still_work(conn):
    sid = db.insert_signal(conn, make_item(url="https://x.com/f", title="Lunar Energy raises $232M", scope="discovery", seed_company_slug=None))
    signal = conn.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
    data = nuclear_deal(
        signal_type="funding", value_chain="energy_software", importance=4, deal_value_usd=232e6, capacity_mw=None, relations=[],
        entities=[{"name": "Lunar Energy Inc", "entity_type": "private_startup", "role": "subject"},
                  {"name": "Amperon", "entity_type": "private_startup", "role": "other"}],
        investors=[{"name": "Lowercarbon Capital", "role": "lead"}, {"name": "Energy Impact Partners", "role": "participant"}],
        funding={"company_name": "Lunar Energy", "round_type": "series_c_plus", "amount_raw": "$232M", "currency": "USD",
                 "amount_usd": 232e6, "announced_on": "2026-02-04", "confidence": "high"},
        new_entity_candidate={"name": "Amperon", "domain": "amperon.co", "entity_type": "private_startup",
                              "value_chain": "energy_software", "why_relevant": "forecasting peer"})
    stats = apply_extraction(conn, signal, data, AliasIndex(conn), "2026-W41")
    assert stats["rounds"] == 1 and stats["candidates"] == 1 and stats["investors_linked"] == 2
    roles = dict(conn.execute("SELECT investor_slug, role FROM round_investors").fetchall())
    assert roles == {"lowercarbon-capital": "lead", "energy-impact-partners": "participant"}
    assert conn.execute("SELECT entity_type, source FROM candidates WHERE name_norm='amperon'").fetchone()[:] == ("private_startup", "llm")


def test_cooccurrence_rule_proposes_frequent_unknown(conn):
    idx = AliasIndex(conn)
    # "Holtec" shows up next to three different tracked entities within the window -> candidate
    for i, (seed, other) in enumerate([("microsoft", "Microsoft"), ("constellation-energy", "Constellation"), ("lunar-energy", "Lunar Energy")]):
        sid = db.insert_signal(conn, make_item(url=f"https://x.com/c{i}", title=f"Holtec news {i}", seed_company_slug=seed,
                                               published_at=db.now_iso()))
        signal = conn.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
        data = nuclear_deal(relations=[], entities=[{"name": other, "entity_type": "utility", "role": "subject"},
                                                    {"name": "Holtec International", "entity_type": "public_company", "role": "supplier"}])
        db.save_extraction(conn, sid, data)
        apply_extraction(conn, signal, data, idx, "2026-W41")
    n = propose_from_cooccurrence(conn, "2026-W41")
    assert n == 1
    cand = conn.execute("SELECT * FROM candidates WHERE name_norm='holtec-international'").fetchone()
    assert cand["source"] == "cooccurrence" and cand["entity_type"] == "public_company"


def test_irrelevant_signal_writes_nothing(conn):
    sid = db.insert_signal(conn, make_item())
    signal = conn.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
    stats = apply_extraction(conn, signal, {"relevant": False, "entities": [{"name": "Microsoft"}]}, AliasIndex(conn), "2026-W41")
    assert stats["companies_linked"] == 0
