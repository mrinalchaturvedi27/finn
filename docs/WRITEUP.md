# FINN — covering note (draft)

**What it is.** A mobile-first brief for a 18-stock NSE portfolio that tells you what changed and
what to look at first, plus an on-demand "promised vs delivered" check on any NSE company.

**Try it on a phone:** https://finn-eta-hazel.vercel.app (the first load can take about a minute
while the free backend wakes up).

## What I built
- **Brief (push, digest).** Every filing in the window you pick (24h / 3d / 7d / 30d), grouped into
  events: a results outcome, its press release, deck and newspaper notice are one item. Ranked by
  materiality, with routine filings collapsed. Category (what kind of filing) and materiality (how
  much to care) are separate. Filings too thin to judge are surfaced at a middle priority as
  "unread", never buried.
- **Results cards.** Revenue, EBITDA, PBT and PAT, QoQ and YoY, from the company's own XBRL filing.
  Each number is also located on the printed PDF statement page and in the right column, checked
  against the comparison quarter's XBRL. Where the company's printed PBT has a different definition,
  the card says so rather than forcing a match.
- **Alerts (push, triggered).** Per-stock price and volume thresholds you set, evaluated after each
  close against a 20-session baseline that excludes the session itself. A stock missing that
  session's bar is shown as stale, not silently skipped. Announcement alerts fire only for filings
  that arrive after live ingestion starts.
- **Promised vs delivered (pull).** For any NSE ticker: management's numeric guidance from its last
  five earnings calls, checked against the results it then filed. Each verdict shows the
  calculation, the quote and the page it came from.

## Key decisions and trade-offs
- **Primary filings for every number.** XBRL is the source of truth; screener.in was only used to
  discover links. Calculated metrics (EBITDA) are labelled as calculated, with their formula.
- **Rules before models.** Classification, guidance extraction and verdicts are deterministic and
  versioned. It's cheap (no model spend at all), reproducible, and every output can be traced. A model
  pass to improve recall on transcripts is the obvious next step, behind the same verdict rules.
- **Abstain rather than guess.** Segment-level, industry, AUM or loan-book, constant-currency or
  "which margin?" statements are shown as not checkable, with the reason. Every claimed verdict was
  checked by hand against its quote.
- **Classifier measured, not assumed.** Two blind-labelled holdouts of 100 filings each from
  earlier periods. On the one labelled after the fixes, the classifier scored 82/100 on category
  and 77/100 on tier (`probe/labels/RESULTS.md`).
- **Hosting from evidence.** A probe run inside each candidate host showed NSE blocks Render but
  answers GitHub runners. So the worker runs on Actions and writes to Postgres, and the API on
  Render reads it, with a fallback to the seeded demo if the database is unavailable.
- **Honest freshness.** The brief shows the actual last successful check and labels historical
  data, instead of promising "within 15 minutes".

## Deliberately left out
- LinkedIn bios for management changes: needs an authorised data source.
- Bull/bear, business snapshot, balance sheet and cash quality: they need annual-report parsing,
  and I chose depth on one research view over breadth.
- Web push notifications (alerts are in-app), an ask bar, per-stock overrides, in-app cost display.

## Where I'd take it next
- A model pass over transcripts for recall (cheap model to extract, verdicts still rule-based),
  plus segment-level checks against XBRL segment reporting.
- Capex promises checked against the half-yearly cash-flow statement.
- Web push for triggered alerts; per-stock thresholds.
