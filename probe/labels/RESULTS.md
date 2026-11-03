# Classifier validation (2026-11-03)

Two random samples of 100 NSE filings each, from the 18 portfolio tickers plus 5 non-portfolio
tickers (HAL, CDSL, ASTRAL, PIDILITIND, KAYNES), deduplicated, seed 20261103. The rules were
originally tuned on Oct–Nov 2026 portfolio filings, so both samples come from earlier periods.

| Set | Period | Population | File |
|---|---|---|---|
| Holdout 1 | Jul–Aug 2026 | 588 | `sample.json`, `labels.json` |
| Holdout 2 | Apr–Jun 2026 | 833 | `h2-sample.json`, `h2-labels.json` |

**Who labelled.** Each set was labelled by a separate Claude subagent that saw only ticker, date,
subject and text, never the classifier code or output, using the written guide in the prompt
(categories plus top/look/routine). These are model labels, not human labels; 33 (H1) and 45 (H2)
are marked low confidence with a note. A human spot-check of the low-confidence rows is the
obvious next step.

## Scores

"Buried" = the label's tier is higher than the classifier's (the costly error: something that
matters filed as routine). "Over-ranked" is the reverse.

| Classifier | Scored on | Category | Tier | Buried | Over-ranked | Honest? |
|---|---|---|---|---|---|---|
| v1 (initial rules) | Holdout 1 | 77 | 86 | 8 | 6 | yes: unseen |
| v2 (fixes from H1) | Holdout 1 | 92 | 91 | 1 | 8 | no: tuned on it |
| **v2** | **Holdout 2** | **82** | **77** | **17** | **6** | **yes: labelled after v2** |
| v3 (fixes from H2) | Holdout 2 | 86 | 83 | 13 | 4 | no: tuned on it |

The unbiased current estimate is the v2-on-holdout-2 row. v3 has no clean holdout yet; a third
labelled set (e.g. Jan–Mar 2026) would give one.

## What the errors were

v1 → v2 (from holdout 1):
- SEBI Takeover Regulation 31(4) annual promoter declarations were scored as **M&A, top tier**
  (the word "takeover"); now insider/SAST, routine.
- Described updates that matched no rule (client wins, an internal-review conclusion, a stake
  subscription) fell to "routine paperwork" (10); now surfaced at 40 ("update not recognised").
- Investor decks / quarterly updates, "Change in Directors" board outcomes, takeover-offer press
  releases, subsidiary IPOs, newspaper notices by topic, USD senior notes, NCD allotments.

v2 → v3 (from holdout 2):
- "Business Combination Agreement" (Persistent–Nagarro) was **general news, routine**; now M&A, top.
- Chairman tenure extension (HDFC Bank) matched "approval" as a press release; now management change, top.
- Cost-auditor reappointment counted as a management change; partnerships/collaborations scored 25 → 45.

## Known disagreements left as they are

- **Bare "Copy of Newspaper Publication"** (9 of the 13 v3 buried rows): the guide said both
  "newspaper ads → routine" and "too thin to judge → look". Labeller 1 chose routine, labeller 2
  chose look. FINN keeps them routine (12). This is a guide ambiguity, not a classifier finding.
- Subsidiary-level acquisitions are scored top (70); labellers called small ones "look". The
  metadata carries no deal size.
- An undescribed board outcome is 40 (look); a labeller inferred results from the date.
