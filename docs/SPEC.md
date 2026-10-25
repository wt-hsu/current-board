# venture-radar — Spec v2

Status: implemented (2026-10-07). Supersedes the v1 note (three-table Airtable schema + seed list).

## Goal

A weekly, mostly automatic radar of international energy-software startups and the investors backing them, so that one person can (a) write a Monday briefing in minutes and (b) let the team watch a dashboard. Free data sources only. The user curates the watchlist; the system proposes one or two additions a week.

## Decisions (and why)

| Question | Decision | Why |
|---|---|---|
| Consumers | Primary: the maintainer. Secondary: team via a static dashboard. Weekly report as Markdown. | No Airtable / Notion sync needed; Markdown pastes into anything. |
| Budget | Free sources only. LLM cost is the only spend (well under $1/week). | Crunchbase / PitchBook / Tracxn APIs are paid; scraping them breaks ToS. LinkedIn likewise. |
| Scope v1 | Track a known list **and** propose candidates from discovery sources. | Tracking alone misses the "who is new" question the user cares about; proposing (not auto-adding) keeps the list curated. |
| Stack | Python, SQLite committed to the repo, GitHub Actions cron, Claude structured outputs, static HTML on GitHub Pages. | No servers. The DB file *is* the versioned history. |
| Language | Dashboard and report in English. Config comments in Chinese. | Team may be international; config is for the maintainer. |

## What was wrong with v1

- **Facts and analysis in one table.** `Core Value Prop`, `Technical Stack`, `Energy Thesis` are human judgments; a crawler would either overwrite or never fill them. v2 keeps them as maintainer-owned columns the pipeline never writes.
- **Funding Rounds had no columns**, yet it is the pipeline's main output.
- **No inbox for non-funding events** (M&A, partnerships, product, people, policy, investor theses).
- **No provenance.** LLM extraction is wrong sometimes; every fact needs a source URL and fetch time.
- **Free-text sub-verticals** can't be aggregated. v2 uses a controlled vocabulary.
- **Company name as key** breaks on "Lunar Energy" / "Lunar Energy Inc." / "Lunar". v2 keys on domain + aliases.

## Data model (SQLite, `radar/db.py`)

```
companies(slug PK, name, domain, sub_vertical ∈ taxonomy, hq_country, status, core_value_prop*, tech_stack*, traction_notes*, notes*)
company_aliases(company_slug, alias)
investors(slug PK, name, domain, fund_type ∈ taxonomy, stage_focus, energy_thesis*, conflict_risk*, status: manual|auto)
investor_aliases(investor_slug, alias)
signals(id, url UNIQUE, resolved_url, title, title_norm, source, published_at, fetched_at, raw_summary, body,
        scope: company|investor|discovery, query, seed_company_slug, seed_investor_slug,
        status: new|extracted|failed, relevant, signal_type ∈ taxonomy, importance 1–5, summary, extracted_json, extracted_at)
signal_companies(signal_id, company_slug)        signal_investors(signal_id, investor_slug)
funding_rounds(id, company_slug, company_name_raw, announced_on, round_type ∈ taxonomy, amount_raw, currency, amount_usd,
               signal_id, confidence, source_url)
round_investors(round_id, investor_slug, role: lead|participant)
candidates(id, name, name_norm UNIQUE, domain, sub_vertical, why_relevant, score, mentions, first_signal_id,
           status: proposed|accepted|rejected, proposed_week)
runs(id, stage, started_at, finished_at, stats_json)
```

`*` = maintainer-owned, never overwritten by the pipeline. The watchlist YAML is synced into `companies` / `investors` on every run, so the YAML stays the source of truth.

## Sources (`config/sources.yaml`)

| Source | Used for | Notes |
|---|---|---|
| Google News RSS, one query per tracked company | tracked-company signals | Free, no key. Links are redirect wrappers; `collectors/fetch.py` decodes them to the publisher URL and fetches the article body. |
| Google News RSS, one query per manual investor | investor signals | Auto-created investors are not queried (would explode query count). |
| Google News RSS, 7 topic queries | discovery | VPP, grid software, forecasting, BESS, interconnection, energy management, data-center power. |
| CTVC, Canary Media, Latitude Media RSS | discovery | Highest-density deal coverage in climate tech. |

Windows: `lookback_days` (10) for routine runs; `backfill_days` (180) the first time a company is on the list. Dedupe: URL, then normalized title (source suffix stripped).

Not used, deliberately: Crunchbase / PitchBook / Tracxn / Dealroom scraping, LinkedIn. SEC Form D and investor portfolio pages are good v3 candidates.

## Pipeline

1. **sync** watchlist YAML → DB.
2. **collect** (`radar/collectors/`) → `signals(status='new')`, body fetched once per new item.
3. **extract** (`radar/extract.py`) → Claude `messages.parse` with a Pydantic schema (`SignalExtraction`): relevant, signal_type, importance, summary, companies[], investors[], funding?, new_company_candidate?. One call per signal, `claude-sonnet-5-5` by default. Failures mark the row `failed` and the run continues.
4. **resolve** (`radar/resolve.py`) → alias / domain matching; the seed company of a company-scoped query is always linked; unknown investors become `auto` rows; rounds for the same company + round type within 45 days and ±15 % amount are merged; discovery subjects not on the list become `candidates` with score = importance (+2 if funding, +1 if ≥ $10M), accumulating over mentions.
5. **report** (`radar/report.py`) → `reports/<ISO week>.md`: headlines (importance ≥ 4), funding table, activity per sub-vertical, investor activity, up to 3 proposed additions with accept/reject commands, data-quality footer.
6. **dashboard** (`radar/dashboard.py`) → `docs/index.html`: stat tiles, signals-per-week bars, signals by sub-vertical, filterable feed, funding table, company cards, candidates, investors with conflict-risk flag. Data is embedded JSON; no external dependencies.

## Operations

- GitHub Actions `weekly.yml`: Monday 00:00 UTC, also manual with an optional lookback override. Commits `data/radar.db`, `reports/`, `docs/`, `config/watchlist.accepted.yaml`; deploys `docs/` to Pages.
- Secrets: `ANTHROPIC_API_KEY`. Without it the run still collects and renders, and warns.
- Human loop: `radar accept "<name>"` / `radar reject "<name>"`, then commit the YAML change.

## Known limits / next

- Google News URL decoding depends on an undocumented endpoint; when it breaks, extraction falls back to title + RSS summary (confidence drops, nothing crashes).
- No currency conversion table: `amount_usd` is the model's estimate. Treat as approximate and check the source link before quoting.
- Candidate proposals are only as good as discovery queries. Tune `config/sources.yaml` when they drift.
- v3 ideas: SEC Form D (EDGAR) for US rounds, investor portfolio-page scraping, APAC coverage (Japan / Australia VPP markets), e-mail delivery of the report.
