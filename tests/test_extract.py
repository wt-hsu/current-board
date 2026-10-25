import os

import pytest

from radar import db, extract
from radar.extract import SignalExtraction, MissingApiKey, build_system_prompt, run_extraction, to_record
from tests.conftest import make_item, nuclear_deal


class FakeMessages:
    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = []

    def parse(self, **kw):
        self.calls.append(kw)
        class R:
            parsed_output = self.parsed
            stop_reason = "end_turn"
        return R()

    def create(self, **kw):  # json mode: the model answers with the object as text
        self.calls.append(kw)
        class Block:
            type = "text"
            text = "```json\n" + self.parsed.model_dump_json() + "\n```"
        class R:
            content = [Block()]
            stop_reason = "end_turn"
        return R()


class FakeClient:
    def __init__(self, parsed):
        self.messages = FakeMessages(parsed)


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(extract, "ROOT", tmp_path)
    monkeypatch.setattr(extract, "load_dotenv", lambda *a, **k: None)  # the real .env may exist on this machine
    with pytest.raises(MissingApiKey):
        extract.get_client()


def test_dotenv_loader(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text('ANTHROPIC_API_KEY="sk-test"\n# c\nX=1\n')
    extract.load_dotenv(tmp_path / ".env")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"


def test_schema_has_v3_fields_and_taxonomy_enums():
    schema = SignalExtraction.model_json_schema()
    assert set(schema["properties"]) >= {"relevant", "signal_type", "value_chain", "importance", "summary_en", "summary_zh",
                                         "deal_value_usd", "capacity_mw", "entities", "relations", "funding", "new_entity_candidate"}
    assert "compute_demand" in schema["$defs"]["ValueChain"]["enum"]
    assert "offtake" in schema["$defs"]["SignalType"]["enum"]
    assert "buys_power_from" in schema["$defs"]["RelationType"]["enum"]
    rec = to_record(SignalExtraction(relevant=True, signal_type="offtake", value_chain="generation_nuclear", importance=9,
                                     summary_en="s", summary_zh="摘要"))
    assert rec["importance"] == 5 and rec["summary"] == "s" and rec["summary_zh"] == "摘要"


def test_system_prompt_is_built_from_taxonomy():
    prompt = build_system_prompt()
    assert "generation_nuclear" in prompt and "IMPORTANCE SCALE" in prompt and "5:" in prompt
    assert "Traditional Chinese" in prompt


def test_run_extraction_with_fake_client(conn):
    sid = db.insert_signal(conn, make_item())
    parsed = SignalExtraction(**{k: v for k, v in nuclear_deal().items() if k != "summary"})
    client = FakeClient(parsed)
    stats = run_extraction(conn, client=client, week="2026-W41")
    assert stats["processed"] == 1 and stats["relevant"] == 1 and stats["relations"] == 2 and stats["candidates"] == 1
    row = conn.execute("SELECT status, importance, summary, summary_zh, value_chain, capacity_mw FROM signals WHERE id=?", (sid,)).fetchone()
    assert row["status"] == "extracted" and row["importance"] == 5 and row["capacity_mw"] == 835
    assert row["value_chain"] == "generation_nuclear" and row["summary_zh"].startswith("微軟")
    assert "OUTPUT FORMAT" in client.messages.calls[0]["system"]
    assert "Constellation Energy" in client.messages.calls[0]["messages"][0]["content"]
    assert "cooccurrence" not in stats or stats["candidates_cooccurrence"] == 0


def test_failed_extraction_marks_row(conn):
    sid = db.insert_signal(conn, make_item())
    class Boom:
        class messages:
            @staticmethod
            def parse(**kw):
                raise RuntimeError("api down")

            @staticmethod
            def create(**kw):
                raise RuntimeError("api down")
    stats = run_extraction(conn, client=Boom(), week="2026-W41")
    assert stats["failed"] == 1
    assert conn.execute("SELECT status FROM signals WHERE id=?", (sid,)).fetchone()[0] == "failed"
