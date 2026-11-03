"""Throwaway source-access probe for FINN milestone 1.

Run from the intended backend host, not just locally:
    python probe/source_probe.py --out probe/report-<host>.json

Records, per source and ticker: HTTP status, content validity, extraction
coverage and failure reasons. HTTP 200 alone is not treated as success.
"""
import argparse
import io
import json
import platform
import re
import socket
import time
import traceback
from datetime import date, datetime, timedelta

import sys
from pathlib import Path

import pdfplumber
import requests
import yfinance as yf
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# Varied sample: bank, NBFC, IT, conglomerate, pharma, consumer, mid-cap
# manufacturing, new-age. KAYNES is the unseen generalisation ticker.
TICKERS = ["HDFCBANK", "BAJFINANCE", "INFY", "RELIANCE", "SUNPHARMA",
           "TITAN", "DIXON", "ETERNAL"]
UNSEEN = "KAYNES"

RESULT_HEADER_PATTERNS = {
    "quarter_ended": r"quarter\s+ended|three\s+months\s+ended",
    "revenue": r"revenue\s+from\s+operations|total\s+income|interest\s+earned",
    "pbt": r"profit\s*/?\s*\(?loss\)?\s+before\s+(exceptional\s+items\s+and\s+)?tax|profit\s+before\s+tax",
    "pat": r"(net\s+)?profit\s*/?\s*\(?loss\)?\s+(after\s+tax|for\s+the\s+(period|quarter))",
    "finance_cost": r"finance\s+costs?|interest\s+expended",
    "depreciation": r"depreciation",
    "consolidated": r"consolidated",
}


def rec(source, ticker, **kw):
    return {"source": source, "ticker": ticker, "at": datetime.now().isoformat(timespec="seconds"), **kw}


def nse_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                      "Accept": "*/*", "Referer": "https://www.nseindia.com/"})
    r = s.get("https://www.nseindia.com/", timeout=15)
    return s, r.status_code


def probe_nse(s, ticker, days=30):
    to_d, from_d = date.today(), date.today() - timedelta(days=days)
    url = ("https://www.nseindia.com/api/corporate-announcements?index=equities"
           f"&symbol={ticker}&from_date={from_d:%d-%m-%Y}&to_date={to_d:%d-%m-%Y}")
    try:
        r = s.get(url, timeout=20)
        out = rec("nse_announcements", ticker, status=r.status_code, bytes=len(r.content))
        try:
            data = r.json()
        except ValueError:
            out.update(valid=False, reason="non-JSON body (likely bot block)", snippet=r.text[:120])
            return out, []
        rows = data if isinstance(data, list) else data.get("data", [])
        fields_ok = all(k in rows[0] for k in ("desc", "attchmntFile", "an_dt")) if rows else None
        out.update(valid=isinstance(rows, list), count=len(rows), fields_ok=fields_ok,
                   reason=None if rows else "empty list for window")
        return out, rows
    except Exception as e:
        return rec("nse_announcements", ticker, status=None, valid=False, reason=repr(e)), []


def probe_bse(scrip_code, ticker, days=30):
    to_d, from_d = date.today(), date.today() - timedelta(days=days)
    url = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1"
           f"&strPrevDate={from_d:%Y%m%d}&strScrip={scrip_code}&strSearch=P"
           f"&strToDate={to_d:%Y%m%d}&strType=C&subcategory=-1")
    try:
        r = requests.get(url, timeout=20, headers={
            "User-Agent": UA, "Referer": "https://www.bseindia.com/",
            "Origin": "https://www.bseindia.com"})
        out = rec("bse_announcements", ticker, status=r.status_code, scrip=scrip_code)
        try:
            rows = r.json().get("Table", [])
        except ValueError:
            out.update(valid=False, reason="non-JSON body", snippet=r.text[:120])
            return out
        out.update(valid=True, count=len(rows),
                   fields_ok=all(k in rows[0] for k in ("NEWSSUB", "ATTACHMENTNAME", "NEWS_DT")) if rows else None,
                   reason=None if rows else "empty list for window")
        return out
    except Exception as e:
        return rec("bse_announcements", ticker, status=None, valid=False, reason=repr(e))


def probe_screener(ticker):
    url = f"https://www.screener.in/company/{ticker}/consolidated/"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": UA})
        out = rec("screener", ticker, status=r.status_code, final_url=r.url)
        if r.status_code != 200:
            out.update(valid=False, reason=f"HTTP {r.status_code}")
            return out, None
        soup = BeautifulSoup(r.text, "lxml")
        sections = {sid: bool(soup.select_one(f"section#{sid} table"))
                    for sid in ("quarters", "profit-loss", "balance-sheet", "cash-flow")}
        q = soup.select_one("section#quarters table")
        q_cols = [th.get_text(strip=True) for th in q.select("thead th")][1:] if q else []
        ar = [a["href"] for a in soup.select(".annual-reports a[href]")]
        concall = [a["href"] for a in soup.select(".concalls a[href]")
                   if "transcript" in a.get_text(strip=True).lower()]
        bse = re.search(r"bseindia\.com/stock-share-price/[^/]+/[^/]+/(\d{6})", r.text)
        out.update(valid=all(sections.values()), sections=sections,
                   quarter_cols=q_cols[-6:], n_quarters=len(q_cols),
                   annual_reports=len(ar), transcripts=len(concall),
                   bse_code=bse.group(1) if bse else None,
                   sample_ar=ar[:1], sample_transcript=concall[:1],
                   reason=None if all(sections.values()) else "missing table sections")
        return out, (bse.group(1) if bse else None)
    except Exception as e:
        return rec("screener", ticker, status=None, valid=False, reason=repr(e)), None


def probe_results_pdf(s, ticker, rows):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from finn.extract.results import results_pdf_candidates
    hits = results_pdf_candidates(rows, None)
    if not hits:
        return rec("results_pdf", ticker, valid=None, reason="no results filing in window")
    row = hits[0]
    url = row.get("attchmntFile")
    out = rec("results_pdf", ticker, filing_dt=row.get("an_dt"), url=url, subject=row.get("desc"))
    try:
        r = s.get(url, timeout=40)
        out.update(status=r.status_code, bytes=len(r.content),
                   content_type=r.headers.get("content-type"))
        if not r.content.startswith(b"%PDF"):
            out.update(valid=False, reason="not a PDF")
            return out
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages[:15]]
            n_pages = len(pdf.pages)
        text_pages = sum(1 for t in pages if len(t.strip()) > 200)
        joined = "\n".join(pages).lower()
        coverage = {k: bool(re.search(p, joined)) for k, p in RESULT_HEADER_PATTERNS.items()}
        # Page most likely to hold the results table
        best = max(range(len(pages)), key=lambda i: sum(bool(re.search(p, pages[i].lower())) for p in RESULT_HEADER_PATTERNS.values()), default=None)
        out.update(valid=text_pages > 0, n_pages=n_pages, text_pages_first15=text_pages,
                   scanned_suspect=text_pages == 0, coverage=coverage,
                   coverage_score=f"{sum(coverage.values())}/{len(coverage)}",
                   table_page_guess=(best + 1) if best is not None else None,
                   reason=None if text_pages else "no extractable text (scanned?)")
        return out
    except Exception as e:
        out.update(valid=False, reason=repr(e))
        return out


def probe_results_xbrl(ticker):
    """Integrated-filing results index + one XBRL fetch/parse — what the results card depends on."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from finn.extract import xbrl
    from finn.sources.nse import NSE, SourceError
    nse = NSE(min_interval=0.4)
    try:
        idx = nse.results_index(ticker)
    except SourceError as e:
        return rec("nse_results_xbrl", ticker, valid=False, reason=str(e))
    out = rec("nse_results_xbrl", ticker, count=len(idx))
    if not idx:
        return {**out, "valid": False, "reason": "empty results index"}
    row = idx[0]
    try:
        body = nse._get(row["xbrl"], timeout=40).content
        doc = xbrl.parse(body, row["xbrl"])
        ok = (doc.meta.get("symbol") or "").upper() in (ticker, "") or bool(doc.meta.get("company"))
        return {**out, "valid": ok, "latest_qe": row.get("qe_Date"), "basis": row.get("consolidated"),
                "taxonomy": doc.taxonomy, "facts": len(doc.facts), "reason": None if ok else "XBRL meta mismatch"}
    except Exception as e:
        return {**out, "valid": False, "reason": f"xbrl fetch/parse: {e!r}"}


def probe_prices(tickers):
    out = []
    try:
        df = yf.download([f"{t}.NS" for t in tickers], period="40d", group_by="ticker",
                         progress=False, auto_adjust=False, threads=True)
    except Exception as e:
        return [rec("yfinance", t, valid=False, reason=repr(e)) for t in tickers]
    for t in tickers:
        try:
            sub = df[f"{t}.NS"].dropna(how="all")
            last = sub.index[-1].date() if len(sub) else None
            vol_ok = bool(len(sub) and sub["Volume"].iloc[-1] > 0)
            out.append(rec("yfinance", t, valid=len(sub) >= 21, sessions=len(sub),
                           last_bar=str(last), last_volume_positive=vol_ok,
                           reason=None if len(sub) >= 21 else "fewer than 21 sessions"))
        except Exception as e:
            out.append(rec("yfinance", t, valid=False, reason=repr(e)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="probe/report-local.json", help="'-' prints the JSON report to stdout")
    args = ap.parse_args()
    all_tickers = TICKERS + [UNSEEN]
    report = {"host": socket.gethostname(), "platform": platform.platform(),
              "run_at": datetime.now().isoformat(timespec="seconds"), "records": []}
    R = report["records"]

    R.extend(probe_prices(all_tickers))

    try:
        s, home = nse_session()
        R.append(rec("nse_home", None, status=home, valid=home == 200))
    except Exception as e:
        s = None
        R.append(rec("nse_home", None, status=None, valid=False, reason=repr(e)))

    for t in all_tickers:
        scr, bse_code = probe_screener(t)
        R.append(scr)
        if bse_code:
            R.append(probe_bse(bse_code, t))
        else:
            R.append(rec("bse_announcements", t, valid=False, reason="no BSE code discovered from screener"))
        if s:
            nse, rows = probe_nse(s, t)
            R.append(nse)
            R.append(probe_results_pdf(s, t, rows))
        R.append(probe_results_xbrl(t))
        time.sleep(1.2)  # be polite to screener / NSE

    if args.out == "-":
        print("=== FINN_PROBE_REPORT_JSON ===")
        print(json.dumps(report, default=str))
    else:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2, default=str)

    # Summary
    by_src = {}
    for r in R:
        by_src.setdefault(r["source"], []).append(r)
    print(f"host={report['host']}  run_at={report['run_at']}")
    for src, rs in by_src.items():
        ok = sum(1 for r in rs if r.get("valid") is True)
        na = sum(1 for r in rs if r.get("valid") is None)
        print(f"\n[{src}] valid {ok}/{len(rs)}" + (f"  (n/a {na})" if na else ""))
        for r in rs:
            extra = {k: r[k] for k in ("status", "count", "sessions", "last_bar", "n_quarters",
                                        "annual_reports", "transcripts", "bse_code",
                                        "coverage_score", "text_pages_first15", "table_page_guess")
                     if k in r and r[k] is not None}
            flag = {True: "OK ", False: "ERR", None: "n/a"}[r.get("valid")]
            print(f"  {flag} {str(r['ticker']):<11} {extra}" + (f"  reason={r['reason']}" if r.get("reason") else ""))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
