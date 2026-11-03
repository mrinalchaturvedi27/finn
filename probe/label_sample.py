"""Classifier validation on a labelled holdout sample.

The rules in finn/classify.py were tuned on Oct-Nov 2026 portfolio filings, so the sample
is drawn from a different period (Jul-Aug 2026) and includes non-portfolio tickers.

    python probe/label_sample.py sample                  # Jul-Aug 2026 -> probe/labels/sample.json
    python probe/label_sample.py evaluate                # labels.json vs the classifier -> eval.json
    python probe/label_sample.py sample --set h2 --start 2026-04-01 --end 2026-06-30
    python probe/label_sample.py evaluate --set h2       # files get the "h2-" prefix

Holdout 1 (Jul-Aug) was used to find classifier errors, so its post-fix score is optimistic;
holdout 2 (Apr-Jun) was labelled after the fixes and is the unbiased measurement.

labels.json: [{"exch_id", "category", "tier", "labeller", "note"?}]; the classifier's output is
never shown to the labeller (sample.json holds only ticker, date, subject and text).
"""
import argparse
import json
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from finn.classify import classify, tier  # noqa: E402
from finn.events import dedup_key  # noqa: E402
from finn.sources.nse import NSE, parse_nse_dt  # noqa: E402
from finn.versions import CLASSIFIER_VERSION  # noqa: E402

OUT = ROOT / "probe" / "labels"
START, END = date(2026, 7, 1), date(2026, 8, 31)
SIZE, SEED = 100, 20261103


def tickers() -> list[str]:
    p = json.loads((ROOT / "backend" / "portfolio.json").read_text())
    return [x["ticker"] for x in p["portfolio"]] + p.get("research_demo", []) + p.get("unseen_check", [])


def sample(start: date, end: date, prefix: str):
    nse = NSE()
    rows, seen = [], set()
    for t in tickers():
        for r in nse.announcements(t, start, end):
            k = dedup_key(t, r)
            if k in seen:
                continue
            seen.add(k)
            filed = parse_nse_dt(r.get("an_dt")) or parse_nse_dt(r.get("sort_date"))
            rows.append({"exch_id": str(r.get("seq_id") or r.get("dt")), "ticker": t,
                         "filed_at": filed.isoformat() if filed else None,
                         "subject": r.get("desc") or "", "text": r.get("attchmntText") or ""})
    random.Random(SEED).shuffle(rows)
    picked = sorted(rows[:SIZE], key=lambda r: (r["ticker"], r["filed_at"] or ""))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{prefix}sample.json").write_text(json.dumps(
        {"period": [start.isoformat(), end.isoformat()], "seed": SEED, "population": len(rows),
         "filings": picked}, indent=1))
    print(f"population {len(rows)} filings from {len(tickers())} tickers; sampled {len(picked)}")


def evaluate(prefix: str):
    s = json.loads((OUT / f"{prefix}sample.json").read_text())
    labels = {x["exch_id"]: x for x in json.loads((OUT / f"{prefix}labels.json").read_text())}
    rows, cat_ok, tier_ok = [], 0, 0
    conf, tier_conf = Counter(), Counter()
    for f in s["filings"]:
        lab = labels.get(f["exch_id"])
        if not lab:
            continue
        c = classify(f["subject"], f["text"])
        pred_tier = tier(c.materiality)
        rows.append({**f, "label": lab["category"], "pred": c.category, "label_tier": lab["tier"],
                     "pred_tier": pred_tier, "score": c.materiality, "reasons": c.reasons,
                     "read_state": c.read_state, "note": lab.get("note")})
        cat_ok += c.category == lab["category"]
        tier_ok += pred_tier == lab["tier"]
        if c.category != lab["category"]:
            conf[(lab["category"], c.category)] += 1
        tier_conf[(lab["tier"], pred_tier)] += 1
    n = len(rows)
    # the costly error is burying something important: labelled top/look but predicted lower
    rank = {"routine": 0, "look": 1, "top": 2}
    buried = [r for r in rows if rank[r["pred_tier"]] < rank[r["label_tier"]]]
    over = [r for r in rows if rank[r["pred_tier"]] > rank[r["label_tier"]]]
    report = {
        "classifier_version": CLASSIFIER_VERSION, "n": n, "period": s["period"], "population": s["population"],
        "category_accuracy": round(cat_ok / n, 3), "tier_accuracy": round(tier_ok / n, 3),
        "label_distribution": Counter(r["label"] for r in rows),
        "category_confusions": [{"label": a, "pred": b, "n": k} for (a, b), k in conf.most_common()],
        "tier_confusion": [{"label": a, "pred": b, "n": k} for (a, b), k in sorted(tier_conf.items())],
        "buried": [{k: r[k] for k in ("ticker", "subject", "text", "label", "pred", "label_tier", "pred_tier",
                                       "score", "read_state")} for r in buried],
        "over_ranked": len(over),
        "rows": rows,
    }
    (OUT / f"{prefix}eval.json").write_text(json.dumps(report, indent=1, default=str))
    print(f"n={n}  category {cat_ok}/{n}  tier {tier_ok}/{n}  buried {len(buried)}  over-ranked {len(over)}")
    for c in report["category_confusions"][:12]:
        print(f"  {c['label']:>18} -> {c['pred']:<18} {c['n']}")
    for r in buried:
        print(f"  BURIED {r['ticker']}: {r['subject'][:50]} | {r['text'][:80]}  ({r['label_tier']} -> {r['pred_tier']})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sample", "evaluate"])
    ap.add_argument("--set", default="", help="name of a further holdout set")
    ap.add_argument("--start", type=date.fromisoformat, default=START)
    ap.add_argument("--end", type=date.fromisoformat, default=END)
    a = ap.parse_args()
    prefix = f"{a.set}-" if a.set else ""
    sample(a.start, a.end, prefix) if a.cmd == "sample" else evaluate(prefix)
