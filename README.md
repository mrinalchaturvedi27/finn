# FINN

A portfolio briefing and company research tool, built for the ENAM AI Engineer challenge.

**[Open the app](https://finn-eta-hazel.vercel.app)** · [Build notes](docs/WRITEUP.md)

FINN groups exchange filings into events, puts material changes first, and collapses routine
paperwork. Results pages show quarterly numbers with their source evidence. The research view
compares management's guidance with the results the company subsequently filed.

The interface is a dark financial terminal, designed for phones and desktop browsers.

## Try it

Start with **Demo briefing**. It replays real filings as of 30 October 2026, 20:00 IST.
Open a results story, expand a number to inspect its evidence, then follow **Dig in** to research.
Research reports have their own dates; they were generated after the briefing's reference date.

**Live** shows the connected database's data and last successful source checks. If the database
is unavailable, the API falls back to a clearly labelled snapshot. The first request can take
about a minute while the Render service wakes up.

Preferences are saved in your browser. They change which price moves and announcement types
are flagged in your briefing. They do not change the worker's monitoring settings or send
notifications.

## Run locally

Use Python 3.12 and Node.js 20 or later. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cd backend
../.venv/bin/python -m finn.ingest snapshot --replay data/snapshot
../.venv/bin/uvicorn finn.api:app --port 8000
```

In a second terminal, from the repository root:

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

Open http://localhost:3000. Leave `FINN_DB_URL` unset for the local snapshot.
The replay command needs no source downloads: recorded API responses, XBRL files, extracted
PDF text and price bars are included in `backend/data/snapshot/`. Demo research reports are in
`backend/data/demo/research/`.

## How the data is checked

Results come from NSE's XBRL filings. FINN checks the company, reporting period and
consolidated/standalone basis, and uses the latest revision for each quarter.

PDF corroboration is a separate check. A value is marked aligned only when it follows the
expected row label and the adjacent comparison column matches that quarter's XBRL value.
The evidence drawer distinguishes aligned values, unconfirmed columns, definition differences,
missing values and missing PDFs. OCR repairs preserve the original text.

Calculated operating EBITDA is labelled with its formula. Banks and NBFCs have separate metric
sets. An XBRL concept that differs from the printed statement is retained with that distinction
and excluded from comparisons that require the printed definition.

## Research coverage

Research uses the company's earnings-call transcripts and up to ten quarters of filed results.
Transcript cover letters are followed to the company-hosted document where needed. Extraction
reads management's answers and looks for explicit numeric guidance. It uses rules, with no LLM
calls or model API cost.

A comparison needs matching metrics, scope, periods and accounting basis. Segment targets,
loan-book growth and ambiguous margin definitions cannot be scored against group revenue or
profit. FINN lists unsupported statements with a reason.

Verdicts are calculated in code. Growth comparisons use a 1 percentage point tolerance;
margin comparisons use 0.5 percentage points. Partial-year figures are run-rate indications,
not completed annual outcomes. A different target on a later call replaces an earlier one only
when the statement explicitly establishes a revision. Otherwise conflicting targets remain visible
without a verdict.

Manual review across 11 companies produced two completed comparisons and one pending comparison:

| Company | Guidance | Result |
| --- | --- | --- |
| Pidilite | 20–24% EBITDA margin corridor | Delivered |
| Astral | 15–16% consolidated EBITDA margin | Near miss |
| Kaynes | Approximately 55% FY27 revenue growth | Pending; one-quarter run-rate only |

Dixon's two FY26 growth targets are shown alongside the actual result, without a verdict.
These examples are checks on a small sample, not an accuracy estimate for all NSE companies.
The main research limitation is coverage: most extracted statements cannot yet be compared
with company-level results.

Run research directly from `backend/`:

```bash
../.venv/bin/python -m finn.research.run PIDILITIND --out /tmp/pidilite-report.json
```

## Worker and deployment

```text
GitHub Actions worker ──> hosted Postgres <── Render / FastAPI
                                                  ↑
                                           Vercel / Next.js
```

Source probes found that NSE requests worked from GitHub-hosted runners but returned 403 from
Render Singapore. That is why ingestion runs separately from the API. Access can change;
[probe reports](probe/) record the observations. BSE returned 403 in the tested environments
and is not a working fallback.

For a hosted database, set `FINN_DB_URL` as a GitHub Actions secret and a Render environment
variable. Keep credentials out of repository files. Run the manual `migrate` workflow before
starting the worker. For a local migration or worker run, from `backend/`:

```bash
../.venv/bin/python -m finn.migrate
../.venv/bin/python -m finn.migrate --status
../.venv/bin/python -m finn.worker --once
../.venv/bin/python -m finn.worker --report
```

The worker and API check the schema version. Snapshot seeding is restricted to SQLite and
refuses a database containing live runs. The Docker image includes a separate seeded SQLite
database for fallback. Removing `FINN_DB_URL` from Render switches the API back to that seed.

The worker workflow has a manual trigger and an hourly schedule at minute 17. Scheduled runs
can be delayed or dropped; the app reports actual successful checks. Announcements backfill
from each ticker's last successful fetch. Repeated runs deduplicate filings and events. A database
lock prevents concurrent ticks, and results cards are retried when their source data is incomplete.

Prices are checked after the close with a 90-minute buffer. Volume alerts use the previous
20 completed sessions, excluding the session being evaluated. A missing bar leaves that ticker
unevaluated without blocking the rest. Exchange holidays are not modelled.

Deployment configuration:

| Service | Setting |
| --- | --- |
| Vercel | Root directory `frontend`; `NEXT_PUBLIC_API_BASE` points to the Render API |
| Render | Root `Dockerfile`; `FINN_CORS` is the Vercel origin |
| Render | `FINN_READ_ONLY=1` for the shared demo |
| Render and Actions | `FINN_DB_URL` points to the same migrated Postgres database |

`/api/health` reports the database mode, schema version, boot time, deployed commit and seed
fingerprint. A temporary runtime source probe can be enabled with `FINN_STARTUP_PROBE=1`;
its report is available at `/api/probe-report` while enabled. Leave it off during normal use.

## Checks

From `backend/`:

```bash
../.venv/bin/python -m pytest
FINN_NETWORK_TESTS=1 ../.venv/bin/python -m pytest tests/test_results_regression.py
```

The default suite runs offline. Network regression tests use manually confirmed filings in
`probe/results_confirmed.json`. Classifier evaluation is documented in
[probe/labels/RESULTS.md](probe/labels/RESULTS.md).

From `frontend/`:

```bash
npm run lint
npx tsc --noEmit
npm run build
```

## Code map

| Path | Purpose |
| --- | --- |
| `backend/finn/api.py` | Brief, results, research and settings endpoints |
| `backend/finn/extract/` | Results extraction and PDF evidence checks |
| `backend/finn/research/` | Transcript extraction and guidance comparisons |
| `backend/finn/classify.py`, `events.py` | Classification, ranking and event grouping |
| `backend/finn/prices.py` | EOD prices and threshold evaluation |
| `backend/finn/worker.py`, `migrate.py` | Ingestion and schema migrations |
| `frontend/` | Next.js interface and browser preferences |
| `probe/` | Source probes, evaluation reports and labelled fixtures |

## Scope left out

There are no browser push notifications, brokerage connections or user accounts. Research does
not yet include annual-report analysis, business snapshots, balance-sheet analysis, cash quality
or bull/bear cases. Unseen symbols depend on source availability and worker execution.

The next research step is broader guidance extraction and segment-level comparisons, with the
same source checks and deterministic verdict rules.
