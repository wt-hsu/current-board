"""The public dashboard must never carry analyst notes or other private fields; the private report must."""
import json
import re

import pytest

from radar import db
from radar.dashboard import PrivateFieldLeak, build_payload, check_public, render_html
from radar.queries import review_queue, snapshot
from radar.report import render_markdown
from radar.resolve import AliasIndex, apply_extraction
from tests.conftest import make_item, nuclear_deal

WEEK = "2026-W41"


@pytest.fixture
def loaded(conn):
    sid = db.insert_signal(conn, make_item())
    signal = conn.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
    data = nuclear_deal()
    db.save_extraction(conn, sid, data)
    apply_extraction(conn, signal, data, AliasIndex(conn), WEEK)
    db.upsert_analyst_note(conn, sid, importance_override=4, note_zh="SECRET_NOTE_ZH 首例州級", note_en="SECRET_NOTE_EN",
                           deal_logic="SECRET_LOGIC who pays")
    db.log_decision(conn, "score", f"signal:{sid}", 5, 4, "SECRET_REASON", WEEK)
    db.save_weekly_view(conn, WEEK, "SECRET_VIEW_ZH 本週觀點", "SECRET_VIEW_EN", public=False)
    conn.commit()
    return conn, sid


def test_public_payload_has_no_private_fields(loaded):
    conn, sid = loaded
    snap = snapshot(conn, WEEK, private=False)
    payload = build_payload(snap)
    text = json.dumps(payload, ensure_ascii=False)
    for secret in ("SECRET_", "PRIVATE NOTE", "PRIVATE THESIS", "importance_override", "why_relevant", "\"score\""):
        assert secret not in text, secret
    assert payload["weekly_view"] is None  # not marked public
    assert payload["signals"][0]["importance"] == 5  # machine score, not the analyst's override
    assert payload["relations"][0]["subject_name"] == "Microsoft"
    html = render_html(snap)
    assert "SECRET_" not in html and "Current Board" in html and "電流看板" in html


def test_leak_check_catches_private_keys():
    with pytest.raises(PrivateFieldLeak):
        check_public({"companies": [{"name": "x", "notes": "n"}]})
    check_public({"companies": [{"name": "x"}]})  # fine


def test_public_view_appears_only_when_flagged(loaded):
    conn, _ = loaded
    db.save_weekly_view(conn, WEEK, None, None, public=True)
    conn.commit()
    payload = build_payload(snapshot(conn, WEEK, private=False))
    assert payload["weekly_view"]["zh"].startswith("SECRET_VIEW_ZH")


def test_private_report_carries_notes_public_report_does_not(loaded):
    conn, _ = loaded
    private = render_markdown(snapshot(conn, WEEK, private=True))
    public = render_markdown(snapshot(conn, WEEK, private=False))
    assert "SECRET_NOTE_ZH" in private and "SECRET_LOGIC" in private and "machine said 5" in private
    assert "radar accept" in private and "SECRET_VIEW_ZH" in private
    assert "SECRET_" not in public and "Public edition" in public
    assert "Microsoft" in public and "buys power from" in public and "微軟" in public


def test_review_queue_flags_reasons_and_reviewed(loaded):
    conn, sid = loaded
    q = review_queue(conn, WEEK, {"min_importance": 4, "money_importance": 3, "max_items": 12})
    assert len(q) == 1 and q[0]["id"] == sid and q[0]["reviewed"] is True
    assert {"importance 5", "money or MW stated", "new relation"} <= set(q[0]["reasons"])


def test_workbench_is_private_and_renders(loaded):
    from radar.queries import decision_log
    from radar.workbench import render_workbench
    conn, sid = loaded
    html = render_workbench(snapshot(conn, WEEK, private=True), decision_log(conn))
    assert "SECRET_NOTE_ZH" in html and "SECRET_REASON" in html and "SECRET_VIEW_ZH" in html
    assert f"radar note {sid}" in html and "僅你可見" in html
