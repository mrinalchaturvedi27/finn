"""Quarterly series from the company's own XBRL results filings (latest revision per quarter).

Uses the same metric definitions as the results cards, so "delivered" here means exactly what
the brief shows. One basis for the whole series: consolidated if every quarter has it, else
standalone, so growth rates never mix bases.
"""
from datetime import date

from ..extract import xbrl
from ..extract.results import fiscal_label, quarter_start
from ..metrics import compute
from ..sources.nse import NSE, SourceError, parse_nse_dt


def quarter_series(nse: NSE, ticker: str, n: int = 10) -> dict:
    """Last n quarters: enough for the last five quarters and their year-ago quarters.
    Integrated XBRL filings start in 2025; earlier quarters come from the legacy results index."""
    idx = nse.results_index(ticker)
    rows = {}
    try:
        legacy = nse.results_index_legacy(ticker)
    except SourceError:
        legacy = []
    for r in legacy:  # same XBRL taxonomy; integrated rows below win for any quarter in both
        qe = parse_nse_dt(r.get("toDate"))
        frm = parse_nse_dt(r.get("fromDate"))
        if not qe or not frm or not r.get("xbrl") or (qe - frm).days > 95:
            continue
        basis = "Consolidated" if r.get("consolidated") == "Consolidated" else "Standalone"
        stamp = parse_nse_dt(r.get("filingDate"))
        key = (qe.date(), basis)
        if key not in rows or (stamp and rows[key][0] and stamp > rows[key][0]):
            rows[key] = (stamp, {"xbrl": r["xbrl"], "consolidated": basis, "legacy": True})
    for r in idx:
        qe = parse_nse_dt(r.get("qe_Date"))
        if not qe or r.get("consolidated") not in ("Consolidated", "Standalone"):
            continue
        key = (qe.date(), r["consolidated"])
        stamp = parse_nse_dt(r.get("revised_Date") or r.get("broadcast_Date") or r.get("creation_Date"))
        if key not in rows or rows[key][1].get("legacy") or (stamp and rows[key][0] and stamp > rows[key][0]):
            rows[key] = (stamp, r)
    quarters = sorted({qe for qe, _ in rows}, reverse=True)
    # only true quarter ends (results index also lists annual rows under the March quarter)
    quarters = [q for q in quarters if (q.month, q.day) in {(3, 31), (6, 30), (9, 30), (12, 31)}][:n]
    basis = "Consolidated" if quarters and all((q, "Consolidated") in rows for q in quarters) else "Standalone"
    out, failures, taxonomy = [], [], None
    for qe in quarters:
        hit = rows.get((qe, basis))
        if not hit:
            failures.append({"quarter_end": qe.isoformat(), "error": f"no {basis.lower()} XBRL"})
            continue
        url = hit[1].get("xbrl")
        try:
            body, _sha = nse.fetch_bytes(url)
            doc = xbrl.parse(body, url)
        except (SourceError, Exception) as e:  # one bad filing must not sink the series
            failures.append({"quarter_end": qe.isoformat(), "error": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        taxonomy = taxonomy or doc.taxonomy
        ctx = doc.duration_ctx(quarter_start(qe), qe)
        if ctx is None:
            failures.append({"quarter_end": qe.isoformat(), "error": "no three-month context in XBRL"})
            continue
        m = compute(doc, ctx, doc.taxonomy)
        out.append({"quarter_end": qe.isoformat(), "label": fiscal_label(qe), "xbrl_url": url,
                    "values": {k: v["value"] for k, v in m.items()},
                    "locators": {k: v["locator"] for k, v in m.items() if v["locator"]}})
    out.sort(key=lambda q: q["quarter_end"])
    return {"basis": basis.lower(), "taxonomy": taxonomy, "quarters": out, "failures": failures,
            "company": next((r.get("cmName") or r.get("smName") for _, r in rows.values() if r.get("cmName") or r.get("smName")), None)}


def fiscal_year(d: date) -> int:
    """FY in which date d falls (April-March): 2026-11-03 -> 2027."""
    return d.year + 1 if d.month > 3 else d.year


def fy_quarters(fy: int) -> list[date]:
    return [date(fy - 1, 6, 30), date(fy - 1, 9, 30), date(fy - 1, 12, 31), date(fy, 3, 31)]
