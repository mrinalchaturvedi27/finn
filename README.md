# FINN — Financial Investment Agent (ENAM build challenge)

Mobile-first investor brief: portfolio filings ranked by what matters, with results
numbers taken from the company's own XBRL filing and located on the printed statement page.

**Push:** a ranked brief of portfolio filings for a chosen window (routine collapsed), results
cards with Revenue / EBITDA / PBT / PAT QoQ and YoY from the company's XBRL filing, located on
the printed statement page, and per-stock price/volume alerts against thresholds you set.
**Pull:** promised vs delivered for any NSE ticker, using management's guidance from its own
earnings-call transcripts, checked against the quarterly results it then filed.

Hosting: the API is on Render (Singapore) and the web app on Vercel. The worker runs on GitHub
Actions, because NSE's APIs return 403 to Render (`probe/report-render.json`) but answer GitHub
runners (`probe/report-gha.json`, four runs). Live data goes to hosted Postgres. Without it, the
API serves a labelled historical snapshot recorded on 2026-11-03.

## Layout
```
backend/   FastAPI + SQLite. finn/models.py is the frozen evidence model.
  finn/extract/results.py   XBRL -> validated metrics -> page-level PDF corroboration
  finn/classify.py          category and materiality (separate)
  finn/events.py            grouping / dedup of related filings
  finn/prices.py            per-ticker EOD thresholds, staleness
  finn/research/            pull side: transcripts -> guidance -> promised vs delivered
  finn/worker.py            scheduled live ingestion (GitHub Actions), finn/migrate.py schema
frontend/  Next.js (app router), mobile-first
probe/     source-access probe, results evaluation, manually confirmed fixture
```

## Run locally
```
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python -m finn.ingest snapshot --replay data/snapshot   # offline, reproducible
../.venv/bin/uvicorn finn.api:app --port 8000
cd ../frontend && npm install && NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```
Tests: `cd backend && ../.venv/bin/python -m pytest` (add `FINN_NETWORK_TESTS=1` for the
regression run against `probe/results_confirmed.json`).

## Seeding (reproducible)
`backend/data/snapshot/` holds everything the seeded database is built from, captured
2026-11-03 11:24 IST: NSE API responses, results XBRL files, raw extracted PDF text (not the
PDFs), price bars, and the capture clock. `--replay` rebuilds the identical database offline
(asserted in `tests/test_core.py::test_snapshot_replay_is_offline_and_reproducible`).
To capture a new snapshot: `python -m finn.ingest snapshot --days 30 --record data/snapshot-<date>`.

## Research: promised vs delivered

`python -m finn.research.run TICKER` (or the worker, for queued tickers and the demo set). Sources
are the company's own filings only, with no news, broker notes or model knowledge:

1. **Delivered:** up to 10 quarters from NSE XBRL results (integrated filings from 2025, legacy
   index before that), using the latest revision of each quarter on one basis throughout. Metric
   definitions are the same as the results cards.
2. **Promised:** earnings-call transcripts among the company's NSE filings. A cover letter that only
   links to the transcript is followed to the company's PDF. Speaker turns are tagged, and only
   management's answers are read, not analysts' questions.
3. **Extraction (rules, no model):** a sentence needs explicit guidance language, a metric (revenue,
   EBITDA margin, profit, volume, capex) and a number or standard phrase ("high single digit").
   Results being described are dropped. Statements about segments, geographies, the industry or
   economy, AUM or loan books, constant currency, or an unspecified "margin" are kept but marked
   not checkable. That includes when the segment was named a sentence or two earlier.
4. **Verdicts (rules v1, `scorecard.py`):** year-to-date growth or margin against the same quarters a
   year earlier. Pending, with an on-track reading, until all four quarters are in; a finished year
   with missing data is not checkable. Standing margin bands are checked quarter by quarter.
   Tolerance is 1pp on growth and 0.5pp on margins. A later call's target supersedes an earlier one
   (shown as a revision); the same target said again is a reiteration; conflicting targets in one
   call are not checkable. Every verdict shows its calculation, the quote and its page.

Precision over recall: every claimed verdict on 11 companies was checked by hand against its
quote, and each false one became a rule and a test. Most Indian guidance is segment-level, so many
statements are listed as not checkable, with the reason.

## Live ingestion (milestone 2)

`python -m finn.worker` runs the live pipeline (`--once` for a single cron-style tick). Each tick
reads the `ingest_run` log to decide what is due, so repeating a tick is safe. Only one tick runs
at a time (Postgres advisory lock; lock file on SQLite), and a tick killed mid-way is marked
abandoned by the next one.

Deployed: `.github/workflows/worker.yml` runs `--once` on GitHub Actions (manual, plus an hourly
schedule that GitHub may delay or drop) against hosted Postgres from the `FINN_DB_URL` repository
secret; the Render API reads the same database (`FINN_DB_URL` set in the Render dashboard).

- **Announcements:** due every 15 min in market hours and hourly otherwise, but only as often as
  the worker is actually invoked (hourly on Actions for now). Each ticker is fetched from its last
  successful fetch minus 2 days, so a failed ticker or a missed run is backfilled next time; a
  ticker never fetched gets 30 days.
  Re-posts are marked duplicates. A corrigendum/addendum is linked to the filing it amends (by
  the date it cites, else by subject overlap) and joins that filing's event.
- **Results cards:** built when a results outcome or press release arrives; retried every 2 h for
  10 days while failed or partial (XBRL often lands hours after the PDF); rebuilt when new filings
  join the event. A daily check rebuilds a card when NSE publishes a later XBRL revision; values
  from superseded revisions are removed.
- **Prices:** once per session 90 min after the close, then hourly until 21:00 while any ticker
  lacks that session's bar. Alerts are evaluated per ticker; a ticker without the bar is shown as
  stale and evaluated when it arrives.
- **Alerts:** stored in `alert` and shown in the brief. Announcement alerts fire only for events
  filed after the first live run, so the backfill never alerts. "New" is tracked per viewer in the
  browser, because the deployed API is read-only.
- **Freshness:** the brief shows the actual last successful check and the failed status of a
  later attempt; a source is marked overdue after `FINN_OVERDUE_HOURS` (default 3) without success.

Exchange holidays are not modelled; a holiday produces an empty or stale run.

**Schema and rollback.** The hosted database is changed only by `python -m finn.migrate` (the
manual `migrate` workflow); the worker and the API check the schema version and never create
tables there. The historical snapshot is SQLite-only: `finn.ingest snapshot` refuses a hosted
database or one with live runs, and the image builds its seed into its own SQLite file. At startup
the API uses `FINN_DB_URL` only if it connects and is at the latest schema; otherwise it serves the
bundled seed, shows "Live data is unavailable" above the snapshot banner, and reports
`database.source = seed_fallback` in `/api/health` (error type only; details in the logs).
Manual rollback: remove `FINN_DB_URL` in the Render dashboard; the restart serves the seed.

**Where it can run.** NSE's APIs return 403 to Render (`probe/report-render.json`). The worker
needs a host NSE accepts, writing to storage the Render API can read. Storage: `FINN_DB_URL` accepts
a Postgres URL; replaying the snapshot into Postgres gives byte-identical API output to SQLite.
Candidate hosts are probed with the same script before use (`.github/workflows/source-probe.yml`
runs it on a GitHub-hosted runner).

**Classifier validation:** `probe/labels/RESULTS.md`.

## Deployment (milestone 1)
- Backend on Render (Docker). The image seeds the snapshot at build; set `FINN_CORS` to the
  Vercel origin. Free instances sleep and have ephemeral disk — fine for a labelled snapshot,
  not for persistent settings or live ingestion (those need durable storage + scheduled jobs).
- Frontend on Vercel with `NEXT_PUBLIC_API_BASE` set to the Render URL.
- The deployed API is read-only (`FINN_READ_ONLY=1`): settings changes are refused, since CORS only
  restrains browsers.
- Cloud source probe: Render's free plan has no shell or one-off jobs, so the probe runs as a temporary
  startup task inside the deployed container (`FINN_STARTUP_PROBE=1`, `FINN_PROBE_TIMEOUT=600`). It runs
  in the background, so the health check passes while it works. The report is printed to the logs between
  `=== FINN_PROBE_REPORT_JSON ===` markers and served at `GET /api/probe-report` while the flag is on.
  Save it as `probe/report-render.json`, then set the flag to `0`; the endpoint then returns 404.
- Restart/redeploy check: `GET /api/health` returns `booted_at`, the deployed commit and a fingerprint
  of the seeded events and metric values. After a restart or redeploy, `booted_at` should change and
  the fingerprint should stay the same.
- Cold start: the free instance sleeps when idle. The frontend shows "Backend waking up…" and retries
  for up to ~100 s before showing an error with a retry button.

## Data decisions
- **Results numbers** come from NSE Integrated Filing XBRL (one file per quarter × basis; latest
  revision wins). Each file is checked for company, basis and a 3-month period context before use.
- **Corroboration**: a reported value counts as located only when it sits after its row label
  *and* the next printed column equals the comparison quarter's value from that quarter's own
  XBRL filing (column alignment). States: aligned · column unconfirmed · definition differs ·
  not located · no PDF. OCR repairs are applied to a copy; raw text is kept and shown.
- **Definition differs** (e.g. HDFC Bank, Bajaj Finance PBT): the XBRL concept is kept and
  labelled, and excluded from comparisons that need the printed figure.
- **EBITDA** is not in the filing; shown as *Operating EBITDA (calculated)* with its formula.
  Banks and NBFCs use their own metric sets.
- **BSE** fallback returns 403 both locally and from Render (preserved in probe reports); not pursued in milestone 1.
