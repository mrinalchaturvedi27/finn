# FINN — covering note

Before sending: attach the AI build history and confirm the reviewers can access the private repository.

To: assessment@enam.com

Subject: ENAM - IIT screening - 2027

Hello,

I built FINN, a mobile-first briefing for an 18-stock NSE portfolio, with company research focused
on comparing management's guidance against filed results.

- [Working prototype](https://finn-eta-hazel.vercel.app)
- [Repository](https://github.com/mrinalchaturvedi27/finn)

Start with **Demo briefing**. It opens a recorded results-heavy period so you can inspect a
results story, expand its evidence, and follow the company into research. The demo is anchored
to 30 October 2026; research reports show their own later dates. The Live view shows source
freshness and labels any fallback to historical data. The backend can take about a minute to
wake on the first visit.

## What I built

The brief groups related filings into one event and ranks material changes above routine
paperwork. Results pages compare revenue, calculated operating EBITDA, PBT and PAT with the
previous quarter and year-ago quarter. Financial companies use a separate metric set.

Numbers come from the company's XBRL results. A separate check tries to locate each reported
value in the PDF statement and confirm the comparison column. The interface exposes the
source, page and checking status, including missing matches and differences between the XBRL
concept and the printed definition. Calculated figures show their formulas.

Price and volume flags use end-of-day data and a volume baseline of the previous 20 completed
sessions. Missing data is shown per stock. Browser preferences change which moves and filing
types the reader sees flagged; they do not reconfigure background monitoring. Alerts are in-app.

Research reads management's numeric guidance from earnings-call transcripts and compares it
with company-level results for the matching period. Each comparison shows its quote, source
page, actual and calculation. Extraction and verdicts use rules; there are no LLM calls in the
running application.

## Decisions and trade-offs

I concentrated the research work on one question: did the company deliver what management said
it would? Coverage is limited. Review across 11 companies produced two completed comparisons
and one pending comparison: Pidilite's EBITDA margin corridor was delivered; Astral's consolidated
margin target was a near miss; Kaynes's FY27 revenue growth remains pending. Its partial-year
figures are labelled as a run-rate indication.

Dixon illustrates a case where FINN withholds a verdict. Management gave different FY26 growth
targets on two calls without explicitly replacing the earlier target. FINN shows both statements
and the actual result. Segment-level targets and statements with uncertain definitions are also
shown with an explanation when they cannot be compared.

The classifier was evaluated on two sets of 100 filings from earlier periods. A separate model
labelled each set without seeing classifier output. Version 2 agreed with the second set on
82 categories and 77 priority tiers out of 100. These are agreement scores against model labels,
not human-validated accuracy. The current rules include fixes from that set and need a new
holdout for an independent estimate.

Hosting was chosen after testing source access. NSE requests returned 403 from Render Singapore
but worked from GitHub-hosted runners, so the worker runs on Actions and writes to Postgres.
The Render API reads that database and can serve a labelled snapshot if it is unavailable.
Scheduled updates are best effort; the app reports actual check times.

## Scope and next steps

I left out annual-report analysis, business snapshots, balance-sheet and cash-quality views,
bull/bear cases, external executive profiles, chat and browser push notifications. The interface
uses a compact terminal layout, with source evidence available on demand.

The next research work would be broader transcript extraction and segment-level comparisons.
A model could help extract more guidance while leaving comparability checks and verdicts in
code. I would also validate the classifier against human-labelled filings and verify scheduled
ingestion over a longer period.

Regards,

Mrinal Chaturvedi
