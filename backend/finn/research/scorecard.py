"""Promised vs delivered: deterministic verdicts for extracted guidance (rules v1).

Delivered numbers come only from the company's quarterly XBRL results (financials.py). A verdict is
given only when the promise and the filing measure the same thing over the same period; otherwise
the statement is shown as not comparable, with the reason. Every verdict carries its calculation.

Statuses: delivered | partial (within tolerance of the target) | missed | pending (period not
over yet; shows what the reported quarters imply) | not_comparable.
"""
import re
from datetime import date

from .financials import fiscal_year, fy_quarters

RULES_VERSION = 1
TOLERANCE = {"pct_growth": 1.0, "margin": 0.5}  # percentage points
CR = 1e7  # rupees per crore


def build(statements: list[dict], series: dict, today: date) -> list[dict]:
    q = {x["quarter_end"]: x for x in series["quarters"]}
    groups: dict[tuple, list[dict]] = {}
    for s in sorted(statements, key=lambda s: s["stated_on"]):
        groups.setdefault(_key(s), []).append(s)
    out = []
    for items in groups.values():
        last_call = [s for s in items if s["stated_on"] == items[-1]["stated_on"]]
        if len({target_text(s) for s in last_call}) > 1:
            # two targets for one metric and period in the same call: usually different scopes
            # (a segment vs the company, value vs volume); FINN does not pick one
            for s in last_call:
                out.append({**s, "target": target_text(s), "revisions": [], "reiterated_on": [],
                            "verdict": {"status": "not_comparable",
                                        "reason": "The same call gives different targets for this metric and period "
                                                  f"({', '.join(sorted({target_text(x) for x in last_call}))}); "
                                                  "FINN can't tell which is company-level."}})
            continue
        latest = items[-1]
        earlier = [{"stated_on": s["stated_on"], "target": target_text(s), "quote": s["quote"], "page": s["page"],
                    "source_url": s["source_url"]} for s in items[:-1]]
        # saying the same target again is a reiteration, not a revision
        trail = [e for e in earlier if e["target"] != target_text(latest)]
        reiterated = [e["stated_on"] for e in earlier if e["target"] == target_text(latest)]
        out.append({**latest, "target": target_text(latest), "revisions": trail, "reiterated_on": reiterated,
                    "verdict": verdict(latest, q, series, today)})
    order = {"missed": 0, "partial": 1, "delivered": 2, "pending": 3, "not_comparable": 4}
    out.sort(key=lambda s: (order[s["verdict"]["status"]], s["stated_on"]), reverse=False)
    return out


def _key(s: dict) -> tuple:
    if s["period_type"] == "FY":
        return (s["metric"], "FY", s["period_fy"])
    if s["period_type"] in ("standing", "unstated") and s["metric"] == "ebitda_margin":
        return (s["metric"], "standing")
    return (s["metric"], s["period_type"], s["quote"])  # nothing to supersede reliably


def target_text(s: dict) -> str:
    u = "%" if s["unit"] == "pct" else " cr"
    lo, hi = s["low"], s["high"]
    f = lambda v: f"{v:g}"  # noqa: E731
    if s["direction"] == "range":
        return f"{f(lo)}–{f(hi)}{u}"
    if s["direction"] == "at_least":
        return f"at least {f(lo)}{u}"
    if s["direction"] == "at_most":
        return f"at most {f(hi)}{u}"
    return f"~{f(lo)}{u}"


def verdict(s: dict, q: dict, series: dict, today: date) -> dict:
    nc = lambda reason: {"status": "not_comparable", "reason": reason}  # noqa: E731
    if "may refer to a segment, not the whole company" in s["notes"]:
        return nc("Refers to a segment; FINN checks company-level filings only.")
    if "loan book / AUM measure, not in the results filing" in s["notes"]:
        return nc("Loan book / AUM growth: a balance-sheet measure, not in the quarterly results FINN reads.")
    if (series["taxonomy"] in ("banking", "nbfc") and s["metric"] == "revenue_growth"
            and not re.search(r"\b(revenue|total income|interest income|nii|net interest income)\b", s["quote"], re.I)):
        return nc("For lenders, “growth” usually means the loan book; the quote doesn't say revenue.")
    if "refers to the industry or economy, not the company" in s["notes"]:
        return nc("About the industry or economy, not the company's own numbers.")
    if "margin type not stated (gross, EBITDA or segment)" in s["notes"]:
        return nc("Doesn't say which margin (gross, EBITDA or a segment's), so it can't be matched to the filing.")
    if "constant-currency basis" in s["notes"]:
        return nc("Constant-currency target; filings report in rupees.")
    if s["metric"] == "volume_growth":
        return nc("Volumes are not in the results filing.")
    if s["metric"] == "capex":
        return nc("Capex is in the half-yearly cash-flow statement, not the quarterly results FINN reads.")
    if s["period_type"] == "long_horizon":
        return nc("Multi-year target; beyond the quarters available.")
    if series["taxonomy"] in ("banking", "nbfc") and s["metric"] == "ebitda_margin":
        return nc("EBITDA margin is not defined for lenders.")
    if s["metric"] == "ebitda_margin" and s["period_type"] in ("standing", "unstated"):
        return _standing_margin(s, q)
    if s["period_type"] == "FY":
        v = _fy(s, q)
        fy_end = fy_quarters(s["period_fy"])[-1]
        if v["status"] == "pending" and today > fy_end:
            # the year is over: missing quarters are a data gap, not a period still running
            n = len(v.get("quarters") or [])
            return {**v, "status": "not_comparable", "tracking": None,
                    "reason": f"FY{str(s['period_fy'])[-2:]} is over, but only {n} of its 4 quarters have "
                              "year-ago figures in the XBRL filings FINN reads."}
        return v
    if s["period_type"] == "Q":
        return _next_quarter(s, q)
    return nc("No target period stated, so there is nothing definite to check it against.")


def _fy(s: dict, q: dict) -> dict:
    fy = s["period_fy"]
    qs = [d.isoformat() for d in fy_quarters(fy)]
    have = [d for d in qs if d in q]
    label = f"FY{str(fy)[-2:]}"
    if s["metric"] == "ebitda_margin":
        rows = [q[d]["values"] for d in have]
        if not rows or any(r.get("ebitda_op_proxy") is None or not r.get("revenue") for r in rows):
            return _pending_nothing(label, have)
        e, r = sum(x["ebitda_op_proxy"] for x in rows), sum(x["revenue"] for x in rows)
        value = e / r * 100
        calc = (f"{label}{_todate(have)}: operating EBITDA ₹{e / CR:,.0f} cr ÷ revenue ₹{r / CR:,.0f} cr "
                f"= {value:.1f}% (FINN's EBITDA excludes other income; the company's definition may differ)")
        return _judge(s, value, "margin", calc, final=len(have) == 4, quarters=have)
    metric = {"revenue_growth": "revenue", "pat_growth": "pat"}[s["metric"]]
    prior = {d: _year_ago(d) for d in have}
    pairs = [(d, p) for d, p in prior.items() if p in q and q[d]["values"].get(metric) is not None
             and q[p]["values"].get(metric) is not None]
    if not pairs:
        return _pending_nothing(label, have)
    cur = sum(q[d]["values"][metric] for d, _ in pairs)
    base = sum(q[p]["values"][metric] for _, p in pairs)
    if base <= 0:
        return {"status": "not_comparable", "reason": "Year-ago base is zero or negative; growth is not meaningful."}
    value = (cur / base - 1) * 100
    used = [d for d, _ in pairs]
    name = "Revenue" if metric == "revenue" else "PAT"
    calc = (f"{label}{_todate(used)}: {name} ₹{cur / CR:,.0f} cr vs ₹{base / CR:,.0f} cr in the same quarters a "
            f"year earlier = {value:+.1f}%")
    return _judge(s, value, "pct_growth", calc, final=len(used) == 4, quarters=used)


def _standing_margin(s: dict, q: dict) -> dict:
    """A margin band with no end date: checked against each quarter reported after the call."""
    stated = date.fromisoformat(s["stated_on"])
    after = [d for d in sorted(q) if date.fromisoformat(d) > stated and q[d]["values"].get("ebitda_margin") is not None]
    if not after:
        return {"status": "pending", "reason": "No quarter reported since this was said.", "value": None}
    vals = [(q[d]["label"], q[d]["values"]["ebitda_margin"]) for d in after]
    results = [_judge(s, v, "margin", "", final=True, quarters=[])["status"] for _, v in vals]
    met = sum(r == "delivered" for r in results)
    above = sum(1 for _, v in vals if s["high"] is not None and v > s["high"])
    status = ("delivered" if met == len(vals) else "missed" if all(r == "missed" for r in results)
              else "partial")
    tally = f"{met - above} of {len(vals)} within the band" + (f", {above} above it" if above else "")
    calc = ("Operating EBITDA margin by quarter since the call: " + ", ".join(f"{l} {v:.1f}%" for l, v in vals)
            + f" — {tally} (FINN's EBITDA excludes other income)")
    return {"status": status, "value": vals[-1][1], "calc": calc, "tolerance_pp": TOLERANCE["margin"],
            "quarters": after, "reason": None}


def _next_quarter(s: dict, q: dict) -> dict:
    stated = date.fromisoformat(s["stated_on"])
    nxt = next((d for d in sorted(q) if date.fromisoformat(d) > stated), None)
    if nxt is None:
        return {"status": "pending", "reason": "The quarter has not been reported yet.", "value": None}
    v = q[nxt]["values"]
    if s["metric"] == "ebitda_margin":
        if v.get("ebitda_margin") is None:
            return {"status": "not_comparable", "reason": "Margin not computable from that quarter's filing."}
        return _judge(s, v["ebitda_margin"], "margin", f"{q[nxt]['label']} operating EBITDA margin "
                      f"{v['ebitda_margin']:.1f}%", final=True, quarters=[nxt])
    metric = {"revenue_growth": "revenue", "pat_growth": "pat"}[s["metric"]]
    p = _year_ago(nxt)
    if p not in q or not q[p]["values"].get(metric) or v.get(metric) is None:
        return {"status": "not_comparable", "reason": "Year-ago quarter not available to compute growth."}
    value = (v[metric] / q[p]["values"][metric] - 1) * 100
    return _judge(s, value, "pct_growth", f"{q[nxt]['label']} {metric} growth year on year {value:+.1f}%",
                  final=True, quarters=[nxt])


def _judge(s: dict, value: float, kind: str, calc: str, final: bool, quarters: list) -> dict:
    tol = TOLERANCE[kind]
    lo, hi, d = s["low"], s["high"], s["direction"]
    if d == "range":
        ok = lo <= value <= hi or value > hi  # beating the top of a range is not a miss
        near = lo - tol <= value < lo
    elif d == "at_least":
        ok, near = value >= lo, lo - tol <= value < lo
    elif d == "at_most":
        ok, near = value <= hi, hi < value <= hi + tol
    else:  # point: "~20%"
        ok = value >= lo - tol if kind == "pct_growth" else abs(value - lo) <= tol or value > lo
        near = (lo - 2 * tol <= value < lo - tol) if kind == "pct_growth" else lo - 2 * tol <= value < lo - tol
    status = "delivered" if ok else "partial" if near else "missed"
    out = {"value": round(value, 2), "calc": calc, "tolerance_pp": tol, "quarters": quarters, "reason": None}
    if final:
        return {**out, "status": status}
    # a partial year is only a run-rate indication: never presented as the annual target being met
    tracking = {"delivered": "run-rate above target", "partial": "run-rate just below target",
                "missed": "run-rate below target"}[status]
    return {**out, "status": "pending", "tracking": tracking, "run_rate": True,
            "reason": f"Run-rate indication only ({len(quarters)} of 4 quarters filed): {tracking}. "
                      "The annual target is not delivered until the full year is reported."}


def _pending_nothing(label: str, have: list) -> dict:
    return {"status": "pending", "value": None,
            "reason": f"No {label} quarter with comparable figures has been reported yet."}


def _year_ago(d: str) -> str:
    x = date.fromisoformat(d)
    return date(x.year - 1, x.month, x.day).isoformat()


def _todate(quarters: list[str]) -> str:
    if len(quarters) == 4:
        return ""
    qs = [fy_label_q(d) for d in sorted(quarters)]
    return f" to date ({qs[0]}–{qs[-1]})" if len(qs) > 1 else f" to date ({qs[0]})"


def fy_label_q(d: str) -> str:
    x = date.fromisoformat(d)
    return f"Q{((x.month - 4) % 12) // 3 + 1}"


def summary(items: list[dict]) -> dict:
    out = {k: 0 for k in ("delivered", "partial", "missed", "pending", "not_comparable")}
    for i in items:
        out[i["verdict"]["status"]] += 1
    return out


__all__ = ["build", "summary", "RULES_VERSION", "fiscal_year"]
