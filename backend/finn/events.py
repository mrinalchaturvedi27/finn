"""Group filings into events and de-duplicate re-posts.

A results outcome, its newspaper notice, deck and press release become one
results event. Same-day filings of the same kind (three credit-rating letters,
an AGM notice + proceedings + scrutiniser report) collapse into one event.
"""
import hashlib
import re
from datetime import date, datetime, timedelta

from .classify import classify, tier
from .extract.results import fiscal_label

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
QE = {(3, 31), (6, 30), (9, 30), (12, 31)}
DATE_RX = [
    re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*\.?,?\s+(\d{4})", re.I),
    re.compile(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I),
]
DAY_GROUPED = {"credit_rating", "management_change", "agm_egm", "postal_ballot", "earnings_call",
               "investor_meetings", "fund_raise"}


def last_quarter_end(d: date) -> date:
    for back in range(0, 120):
        x = d - timedelta(days=back)
        if (x.month, x.day) in QE and x < d:
            return x
    raise ValueError(d)


def infer_quarter_end(text: str, filed: datetime) -> date:
    for rx in DATE_RX:
        for m in rx.finditer(text or ""):
            g = m.groups()
            try:
                if g[0].isdigit():
                    d = date(int(g[2]), MONTHS[g[1][:3].lower()], int(g[0]))
                else:
                    d = date(int(g[2]), MONTHS[g[0][:3].lower()], int(g[1]))
            except (KeyError, ValueError):
                continue
            if (d.month, d.day) in QE and d <= filed.date():
                return d
    return last_quarter_end(filed.date())


def group_key(ticker: str, c, filed: datetime, text: str) -> str:
    day = filed.date().isoformat()
    if c.category == "results":
        qe = infer_quarter_end(text, filed).isoformat()
        return f"{ticker}|results{'_intimation' if c.subkind == 'results_intimation' else ''}|{qe}"
    if c.category in DAY_GROUPED:
        return f"{ticker}|{c.category}|{day}"
    if c.category == "unclassified":
        return f"{ticker}|{'unread' if c.read_state == 'unread' else 'routine'}|{day}"
    h = hashlib.sha1(c.summary.lower().encode()).hexdigest()[:10]
    return f"{ticker}|{c.category}|{day}|{h}"


def dedup_key(ticker: str, row: dict) -> str:
    att = (row.get("attchmntFile") or "").rsplit("/", 1)[-1].lower()
    basis = att or f"{row.get('desc')}|{row.get('attchmntText')}"
    return f"{ticker}|{hashlib.sha1(basis.encode()).hexdigest()[:16]}"


TITLES = {
    "credit_rating": "Credit rating update", "agm_egm": "Shareholder meeting", "postal_ballot": "Postal ballot",
    "earnings_call": "Earnings call", "investor_meetings": "Investor meetings", "fund_raise": "Fund raise",
}


def event_title(category: str, members: list, key: str) -> str:
    primary = members[0]
    if category == "results":
        qe = date.fromisoformat(key.rsplit("|", 1)[-1])
        return f"{fiscal_label(qe)} results" + (" — date announced" if "intimation" in key else "")
    if "|unread|" in key:
        n = len(members)
        return f"{n} filing{'s' if n > 1 else ''} without a descriptive subject"
    if "|routine|" in key:
        return primary["c"].summary if len(members) == 1 else f"{len(members)} routine filings"
    base = primary["c"].summary
    if category in TITLES and len(members) > 1:
        base = f"{TITLES[category]}: {base}"
    return base


def build_events(filings: list[dict]) -> list[dict]:
    """filings: [{id, ticker, filed_at, subject, text, ...}] -> event dicts with member ids."""
    groups: dict[str, list] = {}
    for f in filings:
        if f.get("duplicate_of"):
            continue
        c = classify(f["subject"], f["text"])
        f["c"] = c
        groups.setdefault(group_key(f["ticker"], c, f["filed_at"], f["text"] or ""), []).append(f)
    # A board outcome whose metadata doesn't mention results still belongs to a same-day results event.
    results_keys = {k: min(f["filed_at"] for f in v) for k, v in groups.items() if "|results|" in k}
    for key in [k for k in groups if "|results" not in k]:
        for f in list(groups[key]):
            if f["subject"].strip().lower() != "outcome of board meeting":
                continue
            for rk, t0 in results_keys.items():
                if rk.startswith(f["ticker"] + "|") and abs((f["filed_at"] - t0).total_seconds()) < 86400:
                    groups[key].remove(f)
                    f["c"].category, f["c"].subkind, f["c"].materiality = "results", "results_outcome", 85
                    f["c"].reasons = ["results:results_outcome (same-day board outcome)"]
                    groups[rk].append(f)
                    break
    groups = {k: v for k, v in groups.items() if v}

    events = []
    for key, members in groups.items():
        members.sort(key=lambda f: (-f["c"].materiality, f["filed_at"]))
        primary = members[0]
        cat = primary["c"].category
        reasons = list(dict.fromkeys(r for m in members for r in m["c"].reasons))
        events.append({
            "group_key": key, "ticker": primary["ticker"], "category": cat,
            "title": event_title(cat, members, key),
            "occurred_at": primary["filed_at"], "materiality": primary["c"].materiality,
            "tier": tier(primary["c"].materiality), "materiality_reasons": reasons,
            "read_state": "unread" if all(m["c"].read_state == "unread" for m in members) else "read",
            "summary": primary["c"].summary, "primary_filing_id": primary["id"],
            "member_ids": [m["id"] for m in members], "subkind": primary["c"].subkind,
        })
    return events
