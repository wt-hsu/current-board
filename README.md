# Current Board

**The power behind AI, on one board.** A weekly radar of the electricity and infrastructure layer underneath AI
compute: who supplies the power, who pays for it, and why now. Free sources only, classification by Claude, one
analyst's judgment on top, every line with a source.

Jensen Huang describes AI as a five-layer cake with energy at the bottom. This board watches that bottom layer.

Live board: https://wt-hsu.github.io/current-board/ (weekly, Mondays · beta)

```
Pipeline (weekly)
  collect    Google News RSS per tracked entity (phrased by entity type) + DCD, Utility Dive, Data Center Frontier,
             CTVC, Canary Media, Latitude Media + discovery queries, one or two per value-chain layer.
             Backfills are asked for in date windows (--since), because Google News caps each query at ~100 items.
  extract    Claude → layer, signal type, importance 1–5, summary, $ and MW (with capacity_kind: nameplate vs IT load),
             project stage, location (place, country, grid region, lat/lng), entities,
             relations (who → what → whom, with value_source: disclosed / reported / estimated),
             funding round, new-entity candidate
  resolve    alias/domain matching · relation de-dup · funding de-dup · three candidate rules
  report     reports/<week>.md (private, with analyst notes) + reports/<week>.public.md
  dashboard  docs/index.html — public, built only from whitelisted fields and scanned for leaks before publish

Analyst loop (Monday morning, about one hour)
  radar review                 the 8–12 signals worth reading
  radar note <id> …            score, note, deal logic → analyst_notes + decision_log
  radar candidates / accept / reject
  radar view … --public        this week's view → bottom half of the report
```

## Brand system

| | Name |
|---|---|
| Platform / dashboard | **Current Board** |
| Weekly report | **On the Board** |
| Relations table (who buys power from whom) | **Circuits** |
| Tracked entities | **The Panel** |
| Startup funding sub-brand | **Sparks** |
| Slogan | *Follow the current.* |

## Run locally

```bash
python3 -m venv .venv                             # any Python >= 3.10
.venv/bin/pip install -e ".[dev]"
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env        # needed only for extract

.venv/bin/radar collect --since 2026-08-15        # first run: windowed backfill
.venv/bin/radar extract
.venv/bin/radar report
.venv/bin/radar dashboard
.venv/bin/radar run                               # weekly: all four stages
.venv/bin/pytest                                  # no network, no key
```

Stages: `radar collect | extract [--limit N] | report | dashboard`. Add `--week 2026-W44` to work on another week.
Without an API key, `run` still collects, reports and renders; nothing new gets classified.

The real watchlist (`config/watchlist.yaml`) carries private analyst notes and is not in this repo;
`config/examples/watchlist.yaml` is a public sample and the code falls back to it on a fresh clone.

## The analyst loop

```bash
radar review                                   # queue: importance ≥ 4, or 3 with $/MW, or a new relation
radar note 123 --importance 5 --en "First state-level plan making data centers pay for grid upgrades" --reason "machine scored on deal size, I score on precedent"
radar note 124 --irrelevant --reason "consumer EV story"
radar note 123 --logic "1 who pays: … 2 who gains/loses: … 3 bottleneck: … 4 counter-view: … 5 prediction by 2027-03: …"
radar candidates                               # with scores, reasons and which rule proposed them
radar accept "Holtec International" --entity-type public_company --value-chain generation_nuclear --reason "…"
radar view --en view.en.md --public
radar log --days 35                            # your disagreements with the machine, for the monthly review
```

Everything the `note`, `accept`, `reject` and `view` commands write is private: it lives in `analyst_notes`,
`decision_log` and `weekly_views`, and the dashboard build refuses to run if any of those field names reach the payload.

## Configure

- `config/taxonomy.yaml` — value-chain layers, signal types, entity types, relation types, **and the importance scale
  that goes verbatim into Claude's prompt**. Edit the scale after reading `radar log`; the machine follows.
- `config/watchlist.yaml` — The Panel. Each entity needs `entity_type` and `value_chain`; `notes` is yours and private.
- `config/sources.yaml` — Google News query templates per entity type, discovery queries per layer, RSS feeds,
  windows, and the review-queue thresholds.

## Public / private split

Code, templates and the published board live in this public repo. The database (which holds article text),
the real watchlist, private reports and the API key stay out of it (`.gitignore`); the next step is a separate
private data repo that `RADAR_DATA_DIR` points the code at. The dashboard is built from whitelisted fields only,
and the build aborts if a private field name or note text reaches the output.

## Layout

```
config/          taxonomy.yaml, sources.yaml, examples/watchlist.yaml (sample panel)
radar/
  collectors/    google_news.py (windowed search), feeds.py, fetch.py
  extract.py     Pydantic schema + prompt (built from the taxonomy); JSON output validated with pydantic
  resolve.py     alias/domain matching, relations, funding de-dup, candidate rules
  queries.py     snapshot(private=…), review_queue, decision_log
  report.py      templates/weekly.md.j2 → reports/
  dashboard.py   whitelist + leak check → templates/dashboard.html.j2 → docs/index.html
  cli.py         radar run | collect | extract | report | dashboard | review | note | view | candidates | accept | reject | log | status
data/radar.db    SQLite (local only); opens older databases and migrates them in place
```

## Costs and limits

Free sources only. Roughly 100–250 new items a week at the current panel size; at ~3k input tokens each, extraction
with `claude-sonnet-5-5` is a few dollars a month. `RADAR_MODEL` changes the model. Money and MW figures carry a
`value_source` (disclosed / reported / estimated): verify against the source link before quoting. Google News URL
decoding depends on an undocumented endpoint; when it breaks, extraction falls back to title + RSS summary.
