# Current Board · 電流看板

**The power behind AI, on one board.** A weekly radar of the electricity and infrastructure layer underneath AI compute:
who supplies the power, who pays for it, and why now. Free sources only, classification by Claude, one analyst's
judgment on top, every line with a source.

Jensen Huang describes AI as a five-layer cake with energy at the bottom. This board watches that bottom layer.

```
Monday 08:00 Taipei (GitHub Actions)
  collect    Google News RSS per tracked entity (phrased by entity type) + DCD, Utility Dive, Data Center Frontier,
             CTVC, Canary Media, Latitude Media + 11 discovery queries, one or two per value-chain layer
  extract    Claude structured output → layer, signal type, importance 1–5, bilingual summary, $ and MW,
             entities, relations (who → what → whom), funding round, new-entity candidate
  resolve    alias/domain matching · relation de-dup · funding de-dup · three candidate rules
  report     reports/<week>.md (private, with analyst notes) + reports/<week>.public.md
  dashboard  docs/index.html — public, bilingual, built only from whitelisted fields and scanned for leaks

Monday morning, the analyst (about one hour)
  radar review                 the 8–12 signals worth reading
  radar note <id> …            score, note, deal logic → analyst_notes + decision_log
  radar candidates / accept / reject
  radar view --zh … --public   this week's view → bottom half of the report
```

## Brand system

| | Name | 中文 |
|---|---|---|
| Platform / dashboard | **Current Board** | 電流看板 |
| Weekly report | **On the Board** | 本週上板 |
| Relations table (who buys power from whom) | **Circuits** | 電路圖 |
| Tracked entities | **The Panel** | 配電盤 |
| Startup funding sub-brand | **Sparks** | 火花 |
| Slogan | *Follow the current.* | 跟著電流走。 |

## Run locally

```bash
/opt/anaconda3/bin/python3.13 -m venv .venv      # any Python >= 3.10
.venv/bin/pip install -e ".[dev]"
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env        # needed only for extract

.venv/bin/radar run --lookback 90    # first run: backfill
.venv/bin/radar run                  # weekly
.venv/bin/radar status
.venv/bin/pytest                     # 28 tests, no network, no key
```

Stages: `radar collect | extract [--limit N] | report | dashboard`. Add `--week 2026-W44` to work on another week.
Without an API key, `run` still collects, reports and renders; nothing new gets classified.

Open `docs/index.html` for the dashboard (EN / 中文 toggle top right). `reports/latest.md` is your private weekly;
`reports/latest.public.md` is what the dashboard links to.

## The analyst loop

```bash
radar review                                   # queue: importance ≥ 4, or 3 with $/MW, or a new relation
radar note 123 --importance 5 --zh "首個要求資料中心分攤電網成本的州級計畫" --reason "machine scored on deal size, I score on precedent"
radar note 124 --irrelevant --reason "consumer EV story"
radar note 123 --logic "1 who pays: … 2 who gains/loses: … 3 bottleneck: … 4 counter-view: … 5 prediction by 2027-03: …"
radar candidates                               # with scores, reasons and which rule proposed them
radar accept "Holtec International" --entity-type public_company --value-chain generation_nuclear --reason "…"
radar view --zh view.zh.md --en view.en.md --public
radar log --days 35                            # your disagreements with the machine, for the monthly review
```

Everything the `note`, `accept`, `reject` and `view` commands write is private: it lives in `analyst_notes`,
`decision_log` and `weekly_views`, and the dashboard build refuses to run if any of those field names reach the payload.
In practice you say these things to Claude Code in VS Code and it runs the commands.

## Configure

- `config/taxonomy.yaml` — value-chain layers, signal types, entity types, relation types, **and the importance scale
  that goes verbatim into Claude's prompt**. Edit the scale after reading `radar log`; the machine follows.
- `config/watchlist.yaml` — The Panel. Each entity needs `entity_type` and `value_chain`; `notes` is yours and private.
- `config/sources.yaml` — Google News query templates per entity type, discovery queries per layer, RSS feeds,
  windows, and the review-queue thresholds.

## Public / private split (planned, see docs/SPEC-v3.md §2.7)

Code and templates live in this public repo; the real `config/`, `data/radar.db` and `reports/` move to a private
`current-board-data` repo. `RADAR_DATA_DIR` points the code at it. The dashboard is built from whitelisted fields only.

## Layout

```
config/          taxonomy.yaml, watchlist.yaml, watchlist.accepted.yaml, sources.yaml
radar/
  collectors/    google_news.py, feeds.py, fetch.py
  extract.py     Pydantic schema + prompt (built from the taxonomy)
  resolve.py     alias/domain matching, relations, funding de-dup, candidate rules
  queries.py     snapshot(private=…), review_queue, decision_log
  report.py      templates/weekly.md.j2 → reports/
  dashboard.py   whitelist + leak check → templates/dashboard.html.j2 → docs/index.html
  cli.py         radar run | collect | extract | report | dashboard | review | note | view | candidates | accept | reject | log | status
data/radar.db    SQLite; opens v2 databases and migrates them in place
docs/SPEC-v3.md  design spec (user journeys, data model, brand, roadmap)
```

## Costs and limits

Free sources only. Roughly 100–250 new items a week at the v3 panel size; at ~3k input tokens each, extraction with
`claude-sonnet-5-5` is a few dollars a month. `RADAR_MODEL` changes the model. Money and MW figures are model estimates:
verify against the source link before quoting. Google News URL decoding depends on an undocumented endpoint; when it
breaks, extraction falls back to title + RSS summary.
