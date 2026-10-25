# Current Board — working rules for Claude Code

Read `README.md` first. This file is the short list of rules that are easy to break.

## What this is
A weekly radar of the power and infrastructure behind AI compute. One analyst, free sources, Claude classifies,
the analyst scores and writes. Public output: `docs/` (GitHub Pages). Everything else is the analyst's.

## Privacy rules (never relax these)
- `data/`, `.env`, `config/watchlist.yaml`, `config/watchlist.accepted.yaml`, `reports/*.md` (non-`.public.md`),
  `reports/workbench.html`, `CLAUDE.local.md` are gitignored. Do not add them, do not add paths that would include them.
- The database holds article text; it never leaves this machine.
- The public board is built only from `PUBLIC_FIELDS` in `radar/dashboard.py`; `check_public()` aborts the build if a
  private field name or note text reaches the payload. Add new public fields there deliberately.
- `config/examples/watchlist.yaml` is the public sample (no `notes`); the real panel is private. Keep them in sync when
  entities change, minus the notes.

## Language
- Everything public is English only: README, `docs/`, `*.public.md`, dashboard template, code and comments.
- Chinese appears only as data for the analyst's private workbench: `label_zh` / `zh` in `config/taxonomy.yaml`,
  `summary_zh`, `note_zh`, `draft_zh`, `radar/templates/workbench.html.j2`, and the `_zh` brand strings.

## Pipeline
- `radar collect [--since YYYY-MM-DD]` → `radar extract` → `radar report` → `radar dashboard`; `radar run` does all four.
- Backfills must use `--since`: Google News returns ~100 items per query, so the collector slices the range into
  date windows with `after:`/`before:`.
- Extraction is JSON-in-prompt validated by pydantic (`radar/extract.py`). The schema is too large for the API's
  strict structured-output mode; `RADAR_STRICT=1` re-enables it only if the schema shrinks.
- Any new extraction field must be added in four places: the pydantic model, `db._MIGRATIONS`, `db.save_extraction`
  (or `upsert_relation`), and `dashboard.PUBLIC_FIELDS` if public. Add fields before a backfill, never after.

## Conventions
- Python ≥ 3.10, run everything through `.venv/bin/…`; `pytest` must pass with no network and no API key.
- `.github/workflows/weekly.yml` is manual-dispatch only until the private data repo exists.
- Commit messages describe the change in one line; no co-author trailers.
- Design decisions live in the owner's Claude project (SPEC v3.3), not in this repo.
