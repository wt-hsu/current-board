"""Command-line entry point.

Pipeline:   radar run | collect | extract | report | dashboard
Analyst:    radar review | workbench | note | view | candidates | accept | reject | log
Ops:        radar status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import db
from .config import DB_PATH, DOCS_DIR, REPORTS_DIR, append_accepted_company, load_sources, load_watchlist
from .extract import MissingApiKey, iso_week

log = logging.getLogger("radar")


def _sync(conn) -> dict:
    companies, investors = load_watchlist()
    stats = db.sync_watchlist(conn, companies, investors)
    return {"companies": companies, "investors": investors, "stats": stats}


# ---------- pipeline ----------

def cmd_collect(conn, args) -> int:
    run_id = db.start_run(conn, "collect")
    synced = _sync(conn)
    from .collectors import collect_all

    sources = load_sources()
    if args.lookback:
        sources.setdefault("limits", {})["lookback_days"] = args.lookback
        sources["limits"]["backfill_days"] = max(args.lookback, int(sources["limits"].get("backfill_days", 90)))
    windows = None
    if getattr(args, "since", None):
        from datetime import date
        from .collectors import date_windows
        until = getattr(args, "until", None) or date.today().isoformat()
        windows = date_windows(args.since, until, int(getattr(args, "window_days", 14) or 14))
        print(f"collect: backfill {args.since} → {until} in {len(windows)} windows", file=sys.stderr)
    stats = collect_all(conn, sources, synced["companies"], synced["investors"],
                        fetch_bodies=None if not args.no_fetch else False, windows=windows)
    db.finish_run(conn, run_id, stats)
    print(f"collect: {json.dumps(stats)}")
    return 0


def cmd_extract(conn, args) -> int:
    from .extract import run_extraction

    if getattr(args, "redo", False):
        # re-queue already-extracted signals (e.g. a cheap first pass) for a better model; relations/candidates
        # are upserted, so re-running is idempotent.
        min_imp = int(getattr(args, "min_importance", None) or 4)
        n = conn.execute("UPDATE signals SET status='new' WHERE status='extracted' AND relevant=1 AND importance>=?",
                         (min_imp,)).rowcount
        conn.commit()
        print(f"extract: re-queued {n} signals with importance >= {min_imp}", file=sys.stderr)

    run_id = db.start_run(conn, "extract")
    try:
        stats = run_extraction(conn, limit=args.limit, week=args.week)
    except MissingApiKey as exc:
        db.finish_run(conn, run_id, {"skipped": "missing_api_key"})
        print(f"extract: skipped — {exc}", file=sys.stderr)
        return 2
    db.finish_run(conn, run_id, stats)
    print(f"extract: {json.dumps(stats)}")
    return 0


def cmd_report(conn, args) -> int:
    from .report import write_report

    _sync(conn)
    private = write_report(conn, args.week, REPORTS_DIR, private=True)
    public = write_report(conn, args.week, REPORTS_DIR, private=False)
    print(f"report: {private} (private)\nreport: {public} (public)")
    return 0


def cmd_dashboard(conn, args) -> int:
    from .dashboard import write_dashboard

    _sync(conn)
    path = write_dashboard(conn, args.week, DOCS_DIR)
    print(f"dashboard: {path}")
    return 0


def cmd_fetch_bodies(conn, args) -> int:
    """Fetch article text for signals collected with --no-fetch, highest importance first."""
    from .collectors.fetch import fetch_article

    sources = load_sources()
    body_max = int((sources.get("limits") or {}).get("body_max_chars", 6000))
    min_imp = int(args.min_importance or 1)
    rows = conn.execute(
        """SELECT id, url, title FROM signals WHERE (body IS NULL OR length(body) < 200)
             AND (importance >= ? OR status='new') ORDER BY importance DESC, published_at DESC LIMIT ?""",
        (min_imp, int(args.limit or 100000))).fetchall()
    done = 0
    for r in rows:
        resolved, body = fetch_article(r["url"], body_max)
        if body or resolved:
            db.update_signal_body(conn, r["id"], resolved, body)
        if body:
            done += 1
        conn.commit()
    print(f"fetch-bodies: {done}/{len(rows)} bodies fetched")
    return 0


def cmd_run(conn, args) -> int:
    rc = cmd_collect(conn, args)
    rc_extract = cmd_extract(conn, args)
    cmd_report(conn, args)
    cmd_dashboard(conn, args)
    if rc_extract == 2:
        print("run: finished WITHOUT extraction (no API key). Report and dashboard contain only previously extracted data.",
              file=sys.stderr)
    return rc


# ---------- analyst loop ----------

def cmd_workbench(conn, args) -> int:
    from .workbench import write_workbench

    _sync(conn)
    path = write_workbench(conn, args.week, REPORTS_DIR)
    print(f"workbench: {path}")
    return 0


def cmd_review(conn, args) -> int:
    from .queries import review_queue

    queue = review_queue(conn, args.week)
    if not queue:
        print(f"review queue for {args.week} is empty")
        return 0
    print(f"Review queue · {args.week} · {len(queue)} items ({sum(1 for s in queue if not s['reviewed'])} unreviewed)\n")
    for s in queue:
        mark = "✅" if s["reviewed"] else "⬜"
        money = f" · ${s['deal_value_usd'] / 1e6:,.0f}M" if s.get("deal_value_usd") else ""
        mw = f" · {s['capacity_mw']:,.0f} MW" if s.get("capacity_mw") else ""
        print(f"{mark} #{s['id']}  [{s['importance_machine']}/5]{money}{mw}  {s['value_chain']} / {s['signal_type']}")
        print(f"   {s['title']}")
        print(f"   {s['summary_zh'] or s['summary'] or ''}")
        print(f"   {s['link']}")
        print(f"   why: {', '.join(s['reasons'])}" + (f" · note: {s['note_zh'] or s['note_en']}" if s["reviewed"] else ""))
        print()
    return 0


def cmd_note(conn, args) -> int:
    row = conn.execute("SELECT id, importance, relevant, title FROM signals WHERE id=?", (args.signal_id,)).fetchone()
    if not row:
        print(f"no signal #{args.signal_id}", file=sys.stderr)
        return 1
    db.upsert_analyst_note(conn, args.signal_id, importance_override=args.importance,
                           relevant_override=False if args.irrelevant else None,
                           note_zh=args.zh, note_en=args.en, deal_logic=args.logic)
    if args.importance is not None and args.importance != row["importance"]:
        db.log_decision(conn, "score", f"signal:{args.signal_id}", row["importance"], args.importance, args.reason, args.week)
    if args.irrelevant:
        db.log_decision(conn, "relevance", f"signal:{args.signal_id}", row["relevant"], 0, args.reason, args.week)
    conn.commit()
    print(f"noted #{args.signal_id}: {row['title'][:70]}")
    return 0


def cmd_view(conn, args) -> int:
    zh = open(args.zh, encoding="utf-8").read() if args.zh else None
    en = open(args.en, encoding="utf-8").read() if args.en else None
    db.save_weekly_view(conn, args.week, zh, en, public=True if args.public else (False if args.private else None))
    conn.commit()
    print(f"weekly view saved for {args.week}" + (" (public)" if args.public else ""))
    return 0


def cmd_candidates(conn, args) -> int:
    from .queries import candidates

    rows = candidates(conn, status=args.status, limit=args.limit, private=True)
    if not rows:
        print(f"no {args.status} candidates")
        return 0
    for c in rows:
        print(f"{c['score']:4.1f}  {c['name']:30s} {c['entity_type'] or '?':16s} {c['value_chain'] or '?':20s} "
              f"x{c['mentions']} via {c['source']}\n      {c['why_relevant'] or ''}\n      {c['first_url'] or ''}")
    return 0


def cmd_accept(conn, args) -> int:
    row = db.set_candidate_status(conn, args.name, "accepted")
    if not row:
        print(f"no candidate named {args.name!r}", file=sys.stderr)
        return 1
    entry = {"name": row["name"], "entity_type": args.entity_type or row["entity_type"] or "private_startup",
             "value_chain": args.value_chain or row["value_chain"] or "other"}
    if row["domain"]:
        entry["domain"] = row["domain"]
    if row["why_relevant"]:
        entry["notes"] = row["why_relevant"]
    append_accepted_company(entry)
    db.log_decision(conn, "candidate", row["name"], "proposed", "accepted", args.reason, args.week)
    conn.commit()
    _sync(conn)
    print(f"accepted {row['name']} → config/watchlist.accepted.yaml (tracked from next run)")
    return 0


def cmd_reject(conn, args) -> int:
    row = db.set_candidate_status(conn, args.name, "rejected")
    if not row:
        print(f"no candidate named {args.name!r}", file=sys.stderr)
        return 1
    db.log_decision(conn, "candidate", row["name"], "proposed", "rejected", args.reason, args.week)
    conn.commit()
    print(f"rejected {row['name']}")
    return 0


def cmd_log(conn, args) -> int:
    from .queries import decision_log

    rows = decision_log(conn, since_days=args.days)
    if not rows:
        print("decision log is empty for this window")
        return 0
    for r in rows:
        print(f"{r['decided_at'][:10]}  {r['kind']:10s} {r['target']:28s} {r['machine_value'] or '—':>8} → {r['human_value'] or '—':<8} {r['reason'] or ''}")
    return 0


# ---------- ops ----------

def cmd_status(conn, args) -> int:
    for table in ("companies", "investors", "signals", "relations", "funding_rounds", "candidates", "analyst_notes", "decision_log"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:15s} {n}")
    for status, n in conn.execute("SELECT status, COUNT(*) FROM signals GROUP BY status"):
        print(f"  signals.{status:10s} {n}")
    for r in conn.execute("SELECT stage, started_at, finished_at, stats_json FROM runs ORDER BY id DESC LIMIT 3").fetchall():
        print(f"run {r['stage']:9s} {r['started_at']} → {r['finished_at']} {r['stats_json']}")
    print(f"db: {DB_PATH}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="radar", description="Current Board — weekly radar of the power and infrastructure behind AI")
    p.add_argument("--week", default=iso_week(), help="ISO week, e.g. 2026-W44 (default: current)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run", help="collect → extract → report → dashboard")
    s.add_argument("--no-fetch", action="store_true", help="skip article body fetching")
    s.add_argument("--lookback", type=int, default=None, help="override lookback_days (e.g. 90 on the first run)")
    s.add_argument("--since", help="backfill from this date (YYYY-MM-DD), queried in date windows")
    s.add_argument("--until", help="backfill end date (default today)")
    s.add_argument("--window-days", type=int, default=14, help="window size for --since backfill")
    s.add_argument("--limit", type=int, default=None, help="max signals to extract")
    s = sub.add_parser("collect", help="pull new items from all sources")
    s.add_argument("--no-fetch", action="store_true")
    s.add_argument("--lookback", type=int, default=None)
    s.add_argument("--since", help="backfill from this date (YYYY-MM-DD), queried in date windows")
    s.add_argument("--until", help="backfill end date (default today)")
    s.add_argument("--window-days", type=int, default=14)
    s = sub.add_parser("extract", help="run Claude extraction on new items")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--redo", action="store_true", help="re-queue extracted signals (importance >= --min-importance) and extract again")
    s.add_argument("--min-importance", type=int, default=4)
    s = sub.add_parser("fetch-bodies", help="fetch article text for signals collected with --no-fetch")
    s.add_argument("--min-importance", type=int, default=4)
    s.add_argument("--limit", type=int, default=None)
    sub.add_parser("report", help="write reports/<week>.md (private) and <week>.public.md")
    sub.add_parser("dashboard", help="write docs/index.html (public, whitelisted)")

    sub.add_parser("review", help="print this week's review queue")
    sub.add_parser("workbench", help="write reports/workbench.html (private, local only)")
    s = sub.add_parser("note", help="record your judgment on a signal")
    s.add_argument("signal_id", type=int)
    s.add_argument("--importance", type=int, choices=range(1, 6))
    s.add_argument("--irrelevant", action="store_true")
    s.add_argument("--zh", help="note in Chinese")
    s.add_argument("--en", help="note in English")
    s.add_argument("--logic", help="deal-logic five questions, free text")
    s.add_argument("--reason", help="why you disagree with the machine (goes to the decision log)")
    s = sub.add_parser("view", help="save the weekly view from text files")
    s.add_argument("--zh", help="path to Chinese draft")
    s.add_argument("--en", help="path to English draft")
    s.add_argument("--public", action="store_true", help="include in the public report and dashboard")
    s.add_argument("--private", action="store_true")
    s = sub.add_parser("candidates", help="list candidates with scores and reasons")
    s.add_argument("--status", default="proposed")
    s.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("accept", help="accept a proposed entity into the watchlist")
    s.add_argument("name")
    s.add_argument("--entity-type")
    s.add_argument("--value-chain")
    s.add_argument("--reason")
    s = sub.add_parser("reject", help="reject a proposed entity")
    s.add_argument("name")
    s.add_argument("--reason")
    s = sub.add_parser("log", help="show the decision log")
    s.add_argument("--days", type=int, default=35)
    sub.add_parser("status", help="table counts and last runs")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    conn = db.connect()
    handler = {
        "run": cmd_run, "collect": cmd_collect, "extract": cmd_extract, "fetch-bodies": cmd_fetch_bodies, "report": cmd_report, "dashboard": cmd_dashboard,
        "review": cmd_review, "workbench": cmd_workbench, "note": cmd_note, "view": cmd_view, "candidates": cmd_candidates,
        "accept": cmd_accept, "reject": cmd_reject, "log": cmd_log, "status": cmd_status,
    }[args.cmd]
    try:
        return handler(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
