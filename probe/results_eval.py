"""Results-extraction evaluation over real filings.

For each ticker: which PDF was selected and why, in-document confirmation
checks, XBRL values, and the page each value was located on. Output feeds the
manual confirmation fixture (probe/results_confirmed.json).

    python probe/results_eval.py --qe 2026-09-30 --out probe/results-eval.json
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from finn.extract.results import build_results_card  # noqa: E402
from finn.sources.nse import NSE  # noqa: E402

TICKERS = ("HDFCBANK ICICIBANK BAJFINANCE INFY PERSISTENT KPITTECH RELIANCE LT SUNPHARMA DIVISLAB "
           "TITAN TRENT ASIANPAINT DIXON POLYCAB ETERNAL IRCTC DEEPAKNTR KAYNES").split()


def cr(v):
    return None if v is None else round(v / 1e7, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qe", default="2026-09-30")
    ap.add_argument("--tickers", nargs="*", default=TICKERS)
    ap.add_argument("--out", default="probe/results-eval.json")
    a = ap.parse_args()
    qe = date.fromisoformat(a.qe)
    nse = NSE()
    cards = []
    for t in a.tickers:
        try:
            ann = nse.announcements(t, qe, min(date.today(), qe + timedelta(days=75)))
        except Exception as e:
            ann = []
            print(f"{t}: announcements failed {e}")
        name = next((x.get("sm_name") for x in ann if x.get("sm_name")), None)
        card = build_results_card(nse, t, name, qe, ann)
        cards.append(card)
        pdf = card.get("pdf") or {}
        print(f"\n== {t} [{card['status']}] {card.get('label')} {card.get('basis')} {card.get('taxonomy')} "
              f"rounding={card.get('rounding')}")
        for p in card["problems"]:
            print("   problem:", p)
        if pdf:
            fails = [c["check"] for c in pdf.get("checks", []) if not c["ok"]]
            print(f"   pdf: {'REJECTED ' if pdf.get('rejected') else ''}{pdf.get('subject')} | "
                  f"{(pdf.get('url') or '')[-55:]} | pages={pdf.get('n_pages')} failed_checks={fails}")
        else:
            print("   pdf: none selected")
        for m in card["metrics"]:
            ch = lambda k: (f"{m[k]['value']:+.1f}{m[k].get('unit','')}" if m[k]["state"] == "ok" else m[k]["state"])  # noqa: E731
            print(f"   {m['label'][:30]:<30} cur={cr(m['current']) if m['value_kind']=='absolute' else m['current'] and round(m['current'],2)} "
                  f"QoQ={ch('prev_q_change')} YoY={ch('yoy_q_change')} page={m.get('pdf_page') or m.get('input_pages')}"
                  + (f" UNAVAILABLE: {m['unavailable_reason']}" if m["unavailable_reason"] else ""))
    Path(a.out).write_text(json.dumps(cards, indent=1, default=str))

    ok = [c for c in cards if c["status"] != "failed"]
    pdf_ok = [c for c in ok if c.get("pdf") and not c["pdf"].get("rejected")]
    rep = [m for c in pdf_ok for m in c["metrics"] if m["calculation_kind"] == "reported" and m["current"] is not None]
    located = [m for m in rep if m.get("pdf_page")]
    print(f"\nSUMMARY xbrl cards {len(ok)}/{len(cards)} | confirmed results PDF {len(pdf_ok)}/{len(ok)} | "
          f"reported values located on a PDF page {len(located)}/{len(rep)}")


if __name__ == "__main__":
    main()
