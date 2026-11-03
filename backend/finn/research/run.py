"""Research one NSE ticker: promised (earnings-call guidance) vs delivered (XBRL results).

    python -m finn.research.run PIDILITIND [--out report.json]

Works for any NSE ticker with integrated XBRL results and filed transcripts; nothing here is
specific to the demo companies. Sources are the company's own filings only.
"""
import argparse
import hashlib
import json
from datetime import date, datetime

from ..prices import now_ist
from ..sources.nse import NSE, SourceError
from . import financials, guidance, scorecard, transcripts

CALLS = 5  # the last four quarters' calls, plus one so a revision trail has a starting point


def research(ticker: str, today: date | None = None, nse: NSE | None = None, log=print) -> dict:
    nse = nse or NSE()
    today = today or now_ist().date()
    ticker = ticker.upper().strip()
    report = {"ticker": ticker, "generated_at": now_ist().isoformat(timespec="seconds"),
              "rules_version": scorecard.RULES_VERSION, "extract_version": guidance.EXTRACT_VERSION,
              "sources": {"transcripts": [], "xbrl": []}, "failures": []}
    try:
        series = financials.quarter_series(nse, ticker)
    except SourceError as e:
        return {**report, "status": "failed", "failures": [{"stage": "results", "error": str(e)}]}
    report["company"] = series["company"]
    report["financials"] = series
    report["sources"]["xbrl"] = [{"quarter": q["label"], "url": q["xbrl_url"]} for q in series["quarters"]]
    report["failures"] += [{"stage": "results", **f} for f in series["failures"]]
    if not series["quarters"]:
        return {**report, "status": "failed",
                "failures": report["failures"] + [{"stage": "results", "error": "no XBRL results found on NSE"}]}
    log(f"  {ticker}: {len(series['quarters'])} quarters ({series['basis']}, {series['taxonomy']})")

    try:
        found = transcripts.find(nse, ticker, today)[:CALLS]
    except SourceError as e:
        found = []
        report["failures"].append({"stage": "transcripts", "error": str(e)})
    statements = []
    for f in found:
        try:
            t = transcripts.load(nse, f)
        except Exception as e:  # one unreadable call must not sink the report
            report["failures"].append({"stage": "transcript", "call_date": f["call_date"], "url": f["nse_url"],
                                       "error": f"{type(e).__name__}: {str(e)[:200]}"})
            report["sources"]["transcripts"].append({**f, "status": "failed"})
            continue
        turns = transcripts.turns(t["pages"])
        found_here = guidance.extract(turns, date.fromisoformat(f["call_date"]), t["url"])
        statements += [s.dict() for s in found_here]
        report["sources"]["transcripts"].append({
            "call_date": f["call_date"], "filed_at": f["filed_at"], "url": t["url"], "nse_url": f["nse_url"],
            "source": t["source"], "pages": len(t["pages"]), "sha256": t["sha256"], "status": "read",
            "management_turns": sum(x["role"] == "management" for x in turns), "statements": len(found_here)})
        log(f"  {ticker}: call {f['call_date']} {len(t['pages'])}p, {len(found_here)} statements")

    items = scorecard.build(statements, series, today)
    report["guidance"] = items
    report["summary"] = {**scorecard.summary(items), "statements": len(items),
                         "calls_read": sum(t["status"] == "read" for t in report["sources"]["transcripts"]),
                         "calls_found": len(found)}
    report["status"] = "partial" if report["failures"] else "done"
    report["cache_key"] = cache_key(report)
    return report


def cache_key(report: dict) -> str:
    """Changes when an input document, the extraction rules or the verdict rules change."""
    parts = [f"x{report['extract_version']}", f"r{report['rules_version']}"]
    parts += sorted(t.get("sha256") or t.get("nse_url", "") for t in report["sources"]["transcripts"])
    parts += sorted(x["url"] for x in report["sources"]["xbrl"])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = research(a.ticker)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(r, f, indent=1, default=str)
    print(json.dumps(r.get("summary"), indent=None), r["status"], len(r["failures"]), "failures")
    for g in r.get("guidance", []):
        v = g["verdict"]
        print(f"  {v['status']:<15} {g['metric_label']:<15} {g['target']:<16} {g['period_label']:<18} "
              f"{(v.get('calc') or v.get('reason') or '')[:110]}")


if __name__ == "__main__":
    main()
