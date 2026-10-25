import sqlite3

import pytest

from radar import db
from radar.config import Company, Investor


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "t.db")
    db.sync_watchlist(c, [
        Company(name="Microsoft", domain="microsoft.com", entity_type="hyperscaler", value_chain="compute_demand",
                ticker="MSFT", aliases=["Microsoft Azure", "Azure"]),
        Company(name="Constellation Energy", domain="constellationenergy.com", entity_type="utility",
                value_chain="generation_nuclear", ticker="CEG", aliases=["Constellation"]),
        Company(name="Lunar Energy", domain="lunarenergy.com", entity_type="private_startup", value_chain="energy_software",
                aliases=["Lunar Energy Inc", "Gridshare"], notes="PRIVATE NOTE lunar"),
        Company(name="Ogre AI", domain="ogre.ai", entity_type="private_startup", value_chain="energy_software", aliases=["Ogre"]),
    ], [Investor(name="Lowercarbon Capital", fund_type="climate_vc", energy_thesis="PRIVATE THESIS")])
    yield c
    c.close()


def make_item(**kw):
    base = {"url": "https://example.com/a", "title": "Microsoft signs 20-year deal to restart Three Mile Island",
            "source": "Reuters", "published_at": "2026-10-05T08:00:00+00:00", "raw_summary": None, "scope": "company",
            "query": "q", "seed_company_slug": "microsoft"}
    base.update(kw)
    return base


def nuclear_deal(**kw):
    """A realistic v3 extraction record: an offtake relation between two tracked entities plus an unknown counterparty."""
    data = {
        "relevant": True, "signal_type": "offtake", "value_chain": "generation_nuclear", "importance": 5,
        "summary_en": "Microsoft signed a 20-year PPA with Constellation to restart Three Mile Island Unit 1 (835 MW).",
        "summary_zh": "微軟與 Constellation 簽署 20 年購電合約，重啟三哩島一號機（835 MW）。",
        "summary": "Microsoft signed a 20-year PPA with Constellation to restart Three Mile Island Unit 1 (835 MW).",
        "deal_value_usd": 16_000_000_000, "capacity_mw": 835,
        "entities": [{"name": "Microsoft", "entity_type": "hyperscaler", "role": "buyer"},
                     {"name": "Constellation Energy", "entity_type": "utility", "role": "seller"},
                     {"name": "PJM Interconnection", "entity_type": "government", "role": "regulator"}],
        "investors": [],
        "funding": None,
        "relations": [{"subject": "Microsoft", "object": "Constellation", "relation_type": "buys_power_from",
                       "value_usd": 16_000_000_000, "capacity_mw": 835, "term_years": 20, "confidence": 0.95},
                      {"subject": "Constellation", "object": "Holtec International", "relation_type": "supplies_to",
                       "value_usd": None, "capacity_mw": None, "term_years": None, "confidence": 0.6}],
        "new_entity_candidate": None,
    }
    data.update(kw)
    return data
