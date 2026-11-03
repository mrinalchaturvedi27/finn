# FINN — Financial Investment Agent (ENAM build challenge)

Mobile-first investor brief: portfolio filings ranked by what matters, with results
numbers taken from the company's own XBRL filing and located on the printed statement page.

**Status: milestone 1 deployed; milestone 2 (live ingestion) in progress** — seeded historical snapshot (visibly labelled), ranked brief,
results detail view, price/volume thresholds, freshness indicators.
Cloud source access (probe run inside the Render Singapore container, 2026-11-03,
`probe/report-render.json`): yfinance 9/9 and screener.in 9/9 work. **NSE's announcement and
results/XBRL APIs return 403 from Render (0/9 each)**, although they work from a local machine. So live
NSE ingestion cannot run from this host as deployed. The NSE archive host (PDF/XBRL files) wasn't
reached, because the index calls failed first. The deployed demo serves the recorded snapshot.

## Layout
```
backend/   FastAPI + SQLite. finn/models.py is the frozen evidence model.
  finn/extract/results.py   XBRL -> validated metrics -> page-level PDF corroboration
  finn/classify.py          category and materiality (separate)
  finn/events.py            grouping / dedup of related filings
  finn/prices.py            per-ticker EOD thresholds, staleness
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

## Live ingestion (milestone 2, in progress)

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
