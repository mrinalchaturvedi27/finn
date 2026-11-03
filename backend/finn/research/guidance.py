"""Numeric guidance stated by management on earnings calls (rules, no model).

A statement is kept only when one sentence, spoken by management, has a forward-looking cue, a
metric FINN can name, and a number or a standard verbal quantity ("high single digit"). Past-tense
sentences about results already reported are dropped. Each statement keeps its quote, page and
speaker; anything ambiguous is left out rather than guessed.
"""
import re
from dataclasses import asdict, dataclass, field
from datetime import date

from .financials import fiscal_year

EXTRACT_VERSION = 1

# explicit forward-looking language only; "this year" or "maintain" alone also describe results
FORWARD = re.compile(
    r"\b(guid\w*|target\w*|expect\w*|outlook|aim(?:ing)?\b|aspir\w*|corridor|anticipat\w*|"
    r"confident (?:of|that)|we will (?:be|deliver|achieve|close|end|grow|see|clock|reach)|"
    r"(?:should|would) (?:be|grow|close|end|see|deliver|come|reach|clock)|"
    r"going to (?:be|grow|deliver|close|end|see|clock))", re.I)
GUIDED = re.compile(r"\b(guid\w*|target\w*|expect\w*|outlook|corridor)\b", re.I)
PAST = re.compile(r"\b(registering|registered|grew|grown|was up|were up|up by|expanded by|delivered|reported|"
                  r"recorded|posted|achieved|came in at|stood at|has been|have been|we did|clocked)\b", re.I)
METRICS = [  # (metric, keyword pattern); each number is assigned to its nearest keyword
    # bare "EBITDA" means margin only straight after a percentage ("20% to 25% kind of EBITDA")
    ("ebitda_margin", re.compile(r"\b(?:ebitda|ebidta|operating)\s*(?:margin|margins|corridor|band|range)\b|"
                                 r"(?<=%)\s*(?:kind of\s+)?ebitda\b|\bmargins?\b", re.I)),
    ("capex", re.compile(r"\bcapex\b|capital expenditure", re.I)),
    ("volume_growth", re.compile(r"\bvolumes?(?:\s+growth)?\b|\buvg\b", re.I)),
    ("pat_growth", re.compile(r"\b(?:pat|net profit|profit after tax|bottom[- ]line)\b", re.I)),
    ("revenue_growth", re.compile(r"\b(?:revenue|revenues|sales|top[- ]?line|turnover|growth)\b", re.I)),
]
SEGMENT = re.compile(r"\b(segment|division|vertical|business|category|subsidiary|subsidiaries|exports?|domestic|"
                     r"international|overseas|b2b|b2c|plant|brand)\b|^\s*[A-Z][a-z]+,\s", re.I)
COMPANY = re.compile(r"\b(overall|consolidated|company level|company-level|group level|total|as a company|"
                     r"for the company|whole company)\b", re.I)
LABEL = {"revenue_growth": "Revenue growth", "ebitda_margin": "EBITDA margin", "pat_growth": "Profit growth",
         "capex": "Capex", "volume_growth": "Volume growth"}
NUM = r"(\d{1,3}(?:\.\d{1,2})?)"
RANGE = re.compile(rf"{NUM}\s*(?:%|percent|per cent)?\s*(?:to|-|–|and|,)\s*{NUM}\s*(?:%|percent|per cent)", re.I)
SINGLE = re.compile(rf"(?:(at least|minimum of|more than|over|above|upwards of|around|about|approximately|~|close to|"
                    rf"up to|at most|below|under)\s+)?{NUM}\s*(?:%|percent|per cent)", re.I)
CRORE = re.compile(rf"(?:rs\.?|₹|inr)?\s*{NUM.replace('{1,3}', '{1,5}')}\s*(?:crore|crores|cr)\b", re.I)
VERBAL = [  # standard Indian-call phrasings -> (low, high); "at least" when high is None
    (re.compile(r"\blow single[- ]digit", re.I), (1, 4)),
    (re.compile(r"\bmid single[- ]digit", re.I), (4, 7)),
    (re.compile(r"\bhigh single[- ]digit", re.I), (7, 10)),
    (re.compile(r"\blow double[- ]digit", re.I), (10, 13)),
    (re.compile(r"\b(early|low) teens?\b", re.I), (11, 14)),
    (re.compile(r"\bmid[- ]teens?\b", re.I), (14, 17)),
    (re.compile(r"\bhigh teens?\b", re.I), (17, 20)),
    (re.compile(r"\b(early|low)[- ]twenties\b", re.I), (20, 24)),
    (re.compile(r"\bdouble[- ]digit", re.I), (10, None)),
]
FY = re.compile(r"\b(?:FY|fiscal|financial year)\s*'?\s*(?:20)?(\d{2})\b", re.I)
LONG = re.compile(r"\b(next|coming)\s+(two|three|four|five|2|3|4|5)(?:\s*(?:-|to)\s*(?:three|four|five|3|4|5))?\s+years|"
                  r"medium[- ]term|long[- ]term|over the years|by 20[3-9]\d|cagr", re.I)


@dataclass
class Statement:
    metric: str
    metric_label: str
    direction: str  # range | at_least | at_most | point
    low: float | None
    high: float | None
    unit: str  # pct | crore
    period_type: str  # FY | Q | standing | long_horizon | unstated
    period_fy: int | None
    period_label: str
    quote: str
    page: int
    speaker: str
    stated_on: str
    source_url: str
    notes: list = field(default_factory=list)

    def dict(self):
        return asdict(self)


def sentences(text: str):
    for s in re.split(r"(?<=[.?!])\s+(?=[A-Z\"'(])", re.sub(r"\s+", " ", text)):
        if 25 <= len(s) <= 600:
            yield s.strip()


def extract(turns: list[dict], stated_on: date, source_url: str) -> list[Statement]:
    out = []
    for t in turns:
        if t["role"] != "management":
            continue
        for s in sentences(t["text"]):
            st = _statement(s, stated_on)
            if st:
                out.append(Statement(**st, page=t["page"], speaker=t["speaker"], stated_on=stated_on.isoformat(),
                                     source_url=source_url))
    return _dedupe(out)


def _statement(s: str, stated_on: date) -> dict | None:
    fwd = FORWARD.search(s)
    if not fwd or s.rstrip().endswith("?"):
        return None
    if PAST.search(s) and not GUIDED.search(s):
        return None  # a result being described, not a promise
    best = None
    for qty in _quantities(s):
        metric, dist = _nearest_metric(s, qty["pos"], qty["unit"])
        if metric is None:
            continue
        # prefer numbers after the forward-looking cue, then the closest metric word
        rank = (qty["pos"] < fwd.start(), dist)
        if best is None or rank < best[0]:
            best = (rank, metric, qty)
    if best is None:
        return None
    _, metric, qty = best
    notes = []
    if re.search(r"constant currency|\bcc\b", s, re.I):
        notes.append("constant-currency basis")
    if SEGMENT.search(s) and not COMPANY.search(s):
        notes.append("may refer to a segment, not the whole company")
    period = _period(s, stated_on, metric)
    return {"metric": metric, "metric_label": LABEL[metric], "direction": qty["direction"], "low": qty["low"],
            "high": qty["high"], "unit": qty["unit"], **period, "quote": s, "notes": notes}


def _nearest_metric(s: str, pos: int, unit: str) -> tuple[str | None, int]:
    best = (None, 10 ** 6)
    for metric, rx in METRICS:
        if (metric == "capex") != (unit == "crore"):
            continue
        for m in rx.finditer(s):
            d = pos - m.end() if m.end() <= pos else (m.start() - pos) * 2  # words after the number count double
            if m.group(0).lower() == "growth":
                d += 30  # bare "growth" is the weakest signal: "growth for volume" is volume growth
            if 0 <= d <= 110 and d < best[1]:
                best = (metric, d)
    return best


def _quantities(s: str) -> list[dict]:
    out, taken = [], []
    def free(a, b):
        return all(b <= x or a >= y for x, y in taken)
    for m in RANGE.finditer(s):
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        if hi - lo <= 15 and hi <= 100:
            out.append({"direction": "range", "low": lo, "high": hi, "unit": "pct", "pos": m.start()})
            taken.append(m.span())
    for rx, (lo, hi) in VERBAL:
        for m in rx.finditer(s):
            if free(*m.span()):
                out.append({"direction": "range" if hi else "at_least", "low": lo, "high": hi, "unit": "pct",
                            "pos": m.start()})
                taken.append(m.span())
    for m in SINGLE.finditer(s):
        if not free(*m.span()):
            continue
        v, q = float(m.group(2)), (m.group(1) or "").lower()
        if v > 100:
            continue
        if q in ("at least", "minimum of", "more than", "over", "above", "upwards of"):
            out.append({"direction": "at_least", "low": v, "high": None, "unit": "pct", "pos": m.start()})
        elif q in ("up to", "at most", "below", "under"):
            out.append({"direction": "at_most", "low": None, "high": v, "unit": "pct", "pos": m.start()})
        else:
            out.append({"direction": "point", "low": v, "high": v, "unit": "pct", "pos": m.start()})
        taken.append(m.span())
    for m in CRORE.finditer(s):
        if free(*m.span()):
            v = float(m.group(1).replace(",", ""))
            out.append({"direction": "point", "low": v, "high": v, "unit": "crore", "pos": m.start()})
    return out


def _period(s: str, stated_on: date, metric: str) -> dict:
    cur_fy = fiscal_year(stated_on)
    if LONG.search(s):
        return {"period_type": "long_horizon", "period_fy": None, "period_label": "multi-year"}
    m = FY.search(s)
    if m:
        fy = 2000 + int(m.group(1))
        if cur_fy - 1 <= fy <= cur_fy + 2:
            return {"period_type": "FY", "period_fy": fy, "period_label": f"FY{str(fy)[-2:]}"}
    if re.search(r"\bnext (?:year|fiscal|financial year)\b", s, re.I):
        return {"period_type": "FY", "period_fy": cur_fy + 1, "period_label": f"FY{str(cur_fy + 1)[-2:]}"}
    if re.search(r"\b(this|current|full)\s+(?:year|fiscal|financial year)\b|\bfor the (?:full )?year\b", s, re.I):
        return {"period_type": "FY", "period_fy": cur_fy, "period_label": f"FY{str(cur_fy)[-2:]}"}
    if re.search(r"\b(next|coming) quarter\b", s, re.I):
        return {"period_type": "Q", "period_fy": None, "period_label": "next quarter"}
    if metric == "ebitda_margin" and re.search(r"\b(range|band|sustain\w*|maintain\w*)\b", s, re.I):
        return {"period_type": "standing", "period_fy": None, "period_label": "standing band"}
    return {"period_type": "unstated", "period_fy": None, "period_label": "period not stated"}


def _dedupe(sts: list[Statement]) -> list[Statement]:
    """The same promise is often repeated in one call; keep the first statement of each."""
    seen, out = set(), []
    for s in sts:
        k = (s.metric, s.period_label, s.low, s.high, s.unit)
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out
