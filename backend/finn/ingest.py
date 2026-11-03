"""Ingestion runner. Every run is logged to ingest_run for freshness display.

    python -m finn.ingest snapshot --days 30     # seed a labelled historical snapshot
    python -m finn.worker                        # live: scheduled, incremental (see finn.worker)
"""
import argparse
import json
import socket
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from . import live
from . import prices as px
from . import snapshot
from .versions import cache_key
from . import db as dbmod
from .db import Session
from .events import build_events, dedup_key
from .extract.results import build_results_card
from .models import Company, Document, Event, Filing, IngestRun, MetricObs, PriceBar, Setting
from .sources.nse import NSE, SourceError, parse_nse_dt

PORTFOLIO_FILE = Path(__file__).resolve().parent.parent / "portfolio.json"
DEFAULT_SETTINGS = {
    "volume_multiple": 2.0, "price_pct": 4.0, "eod_buffer_min": 90,
    "alert_categories": ["results", "M&A", "management_change", "fund_raise", "litigation",
                         "credit_rating", "pledging"],
}


def _settings_or_default(db) -> dict:
    s = db.get(Setting, "alerts")
    return {**DEFAULT_SETTINGS, **(s.value if s else {})}


def load_portfolio() -> list[dict]:
    return json.loads(PORTFOLIO_FILE.read_text())["portfolio"]


def _run(db, source, mode) -> IngestRun:
    r = IngestRun(source=source, mode=mode, started_at=px.now_ist(), status="running", host=socket.gethostname())
    db.add(r)
    db.commit()
    return r


def _finish(db, run, status, items, errors, data_through):
    run.finished_at, run.status, run.items, run.errors, run.data_through = (
        px.now_ist(), status, items, errors, data_through)
    db.commit()


def ingest_announcements(db, nse: NSE, tickers: list[str], days: int, mode: str,
                         windows: dict | None = None) -> dict[str, list[dict]]:
    """windows: {ticker: (start, end, is_backfill)} for incremental live runs; else the last `days`."""
    run = _run(db, "nse_announcements", mode)
    end = px.now_ist().date()
    start = end - timedelta(days=days)
    raw, errors, n = {}, [], 0
    # one round trip each for what already exists (the database may be far from the worker)
    known = set(db.scalars(select(Filing.exch_id).where(Filing.exchange == "NSE", Filing.ticker.in_(tickers))))
    first_by_key = {}
    for fid, dk in db.execute(select(Filing.id, Filing.dedup_key).where(Filing.ticker.in_(tickers),
                                                                        Filing.duplicate_of.is_(None))
                              .order_by(Filing.id)):
        first_by_key.setdefault(dk, fid)
    cos = {c.ticker: c for c in db.scalars(select(Company).where(Company.ticker.in_(tickers)))}
    new_dups = []  # (filing, earlier filing in this batch) — ids exist only after the flush
    for t in tickers:
        t_start, t_end = (windows[t][0], windows[t][1]) if windows else (start, end)
        try:
            rows = nse.announcements(t, t_start, t_end)
        except SourceError as e:
            errors.append({"ticker": t, "error": str(e)})
            continue
        raw[t] = rows
        if windows:
            live.set_cursor(db, t, run.started_at)
        co = cos.get(t)
        if rows and co and not co.name:
            co.name, co.isin = rows[0].get("sm_name"), rows[0].get("sm_isin")
        seen = {}  # dedup key -> first new Filing of this batch
        with db.no_autoflush:
            for r in sorted(rows, key=lambda r: r.get("sort_date") or ""):
                exch_id = str(r.get("seq_id") or r.get("dt"))
                if exch_id in known:
                    continue
                known.add(exch_id)
                filed = parse_nse_dt(r.get("an_dt")) or parse_nse_dt(r.get("sort_date"))
                dk = dedup_key(t, r)
                f = Filing(ticker=t, exchange="NSE", exch_id=exch_id, filed_at=filed, subject=r.get("desc") or "",
                           text=r.get("attchmntText"), attachment_url=r.get("attchmntFile"),
                           category="pending", category_source="none", dedup_key=dk)
                if dk in first_by_key:
                    f.duplicate_of = first_by_key[dk]
                elif dk in seen:
                    new_dups.append((f, seen[dk]))
                else:
                    seen[dk] = f
                db.add(f)
                n += 1
    db.flush()  # one batched insert
    for f, first in new_dups:
        f.duplicate_of = first.id
    for t in raw:
        live.link_revisions(db, t)
    db.commit()
    latest = db.scalar(select(Filing.filed_at).order_by(Filing.filed_at.desc()).limit(1))
    _finish(db, run, "ok" if not errors else ("partial" if raw else "failed"), n, errors, latest)
    return raw


def rebuild_events(db, tickers: list[str], raw: dict[str, list[dict]], mode: str):
    run = _run(db, "results_xbrl", mode)
    nse = NSE()
    errors, n_cards = [], 0
    for t in tickers:
        filings = db.scalars(select(Filing).where(Filing.ticker == t).order_by(Filing.filed_at, Filing.id)).all()
        dicts = [{"id": f.id, "ticker": t, "filed_at": f.filed_at, "subject": f.subject, "text": f.text,
                  "duplicate_of": f.duplicate_of, "revision_of": f.revision_of} for f in filings]
        by_id = {f.id: f for f in filings}
        existing = {e.group_key: e for e in db.scalars(select(Event).where(Event.ticker == t))}
        built = build_events(dicts)
        with db.no_autoflush:
            for ev in built:
                e = existing.get(ev["group_key"]) or Event(group_key=ev["group_key"])
                for k in ("ticker", "category", "title", "occurred_at", "materiality", "materiality_reasons",
                          "read_state", "summary", "primary_filing_id"):
                    setattr(e, k, ev[k])
                db.add(e)
                existing[ev["group_key"]] = e
        db.flush()  # one batched insert for new events
        for ev in built:
            e = existing[ev["group_key"]]
            for fid in ev["member_ids"]:
                f = by_id[fid]
                f.event_id = e.id
                cls = next(d["c"] for d in dicts if d["id"] == fid)
                f.category, f.category_source = cls.category, cls.source
            why = (live.card_due(e, len(ev["member_ids"]), px.now_ist())
                   if ev["category"] == "results" and ev["subkind"] in ("results_outcome", "results_press") else None)
            if why:
                from datetime import date
                qe = date.fromisoformat(ev["group_key"].rsplit("|", 1)[-1])
                co = db.get(Company, t)
                ann = raw.get(t, [])
                if mode == "live":  # an incremental window may not reach back to the PDF's filing day
                    try:
                        ann = nse.announcements(t, e.occurred_at.date() - timedelta(days=3), px.now_ist().date())
                    except SourceError as ex:
                        errors.append({"ticker": t, "error": f"announcements for card: {ex}"})
                card = build_results_card(nse, t, co.name if co else None, qe, ann)
                e.detail = {**(e.detail or {}), "results": card,
                            "results_attempt": {"at": px.now_ist().isoformat(), "why": why,
                                                "count": ((e.detail or {}).get("results_attempt") or {}).get("count", 0) + 1,
                                                "n_members": len(ev["member_ids"])}}
                if card.get("taxonomy") and co:
                    co.reporting_format = {"indas": "industrial", "banking": "bank", "nbfc": "nbfc"}[card["taxonomy"]]
                if card["status"] == "failed":
                    errors.append({"ticker": t, "quarter_end": qe.isoformat(), "problems": card["problems"]})
                else:
                    n_cards += 1
                    e.materiality = max(e.materiality, 85)  # a parsed results filing is always top-tier
                    persist_observations(db, t, card, e.primary_filing_id)
                    m = {r["id"]: r for r in card["metrics"]}
                    pat = m.get("pat", {})
                    if pat.get("yoy_q_change", {}).get("state") == "ok":
                        e.summary = _results_line(card)
        db.flush()
        live.drop_orphan_events(db, t, list(existing.values()))
        db.commit()
    _finish(db, run, "ok" if not errors else "partial", n_cards, errors, px.now_ist())


def _doc(db, known: dict, ticker, kind, url, sha, **kw) -> Document:
    d = known.get(url) or Document(url=url, ticker=ticker, kind=kind)
    d.sha256, d.fetch_state, d.parse_state = sha, "ok", "ok"
    for k, v in kw.items():
        setattr(d, k, v)
    db.add(d)
    known[url] = d
    return d


def persist_observations(db, ticker: str, card: dict, related_filing_id: int | None):
    """Write each displayed number as a MetricObs (frozen evidence model), one per metric x period."""
    from datetime import date
    from .extract.results import quarter_start
    from .metrics import SETS
    defs = {m.id: m for m in SETS[card["taxonomy"]]}
    basis = card["basis"].lower()
    periods = {k: p for k, p in card["periods"].items() if p.get("sha256")}
    urls = [p["xbrl_url"] for p in periods.values()] + ([card["pdf"]["url"]] if card.get("pdf") else [])
    known = {d.url: d for d in db.scalars(select(Document).where(Document.url.in_(urls)))}
    pdf_doc = None
    if card.get("pdf") and not card["pdf"].get("rejected") and card["pdf"].get("sha256"):
        pdf_doc = _doc(db, known, ticker, "filing_pdf", card["pdf"]["url"], card["pdf"]["sha256"],
                       period_end=date.fromisoformat(card["quarter_end"]), basis=basis)
    xdocs = {}
    for k, period in periods.items():
        qe = date.fromisoformat(period["quarter_end"])
        xdocs[k] = _doc(db, known, ticker, "results_xbrl", period["xbrl_url"], period["sha256"],
                        period_start=quarter_start(qe), period_end=qe, basis=basis,
                        revision=f"supersedes {period['revisions_superseded']}")
    db.flush()  # document ids, one round trip
    # the card always uses the latest XBRL revision: every earlier observation of these periods is replaced
    qes = [date.fromisoformat(p["quarter_end"]) for p in periods.values()]
    db.query(MetricObs).filter(MetricObs.ticker == ticker, MetricObs.basis == basis, MetricObs.period_type == "Q",
                               MetricObs.period_end.in_(qes)).delete(synchronize_session=False)
    for k, period in periods.items():
        qe = date.fromisoformat(period["quarter_end"])
        xdoc, ck = xdocs[k], cache_key(period["sha256"])
        for row in card["metrics"]:
            value = row["current"] if k == "current" else row.get(k)
            m = defs[row["id"]]
            corr = (row.get("corroboration") or {}) if k == "current" else {}
            db.add(MetricObs(
                ticker=ticker, metric=row["id"], metric_def_id=row["id"], metric_def_version=m.version,
                value_kind=m.value_kind, scope="company", basis=basis, period_type="Q",
                period_start=quarter_start(qe), period_end=qe, value=value,
                verification_status="primary_verified" if value is not None else "unavailable",
                calculation_kind=m.kind, formula=m.formula,
                source_doc_id=xdoc.id, source_locator=row["locator"] if k == "current" else None,
                corroboration_doc_id=pdf_doc.id if pdf_doc and corr.get("status") == "aligned" else None,
                corroboration_page=corr.get("page") if corr.get("status") == "aligned" else None,
                related_filing_id=related_filing_id,
                unavailable_reason=row["unavailable_reason"] if value is None else None,
                cache_key=ck))


def _results_line(card) -> str:
    m = {r["id"]: r for r in card["metrics"]}
    parts = []
    top = ("revenue", "Revenue") if m.get("revenue", {}).get("current") is not None else ("nii", "NII")
    for mid, label in (top, ("pat", "PAT")):
        r = m.get(mid)
        if r and r["current"] is not None and r["yoy_q_change"]["state"] == "ok":
            parts.append(f"{label} {r['yoy_q_change']['value']:+.0f}% YoY")
    return " · ".join(parts)


def ingest_prices(db, tickers: list[str], mode: str):
    run = _run(db, "prices", mode)
    errors = []
    try:
        if snapshot.MODE == "replay":
            bars = {t: [{**b, "session": datetime.fromisoformat(b["session"]).date()} for b in rows]
                    for t, rows in snapshot.json_get("prices.json").items()}
        else:
            bars = px.fetch_bars(tickers)
            if snapshot.MODE == "record":
                snapshot.json_put("prices.json", bars)
    except Exception as e:  # yfinance raises a variety of things
        _finish(db, run, "failed", 0, [{"error": repr(e)}], None)
        return
    cap = px.latest_complete_session(px.now_ist(), DEFAULT_SETTINGS["eod_buffer_min"])
    have = {(b.ticker, b.session): b for b in db.scalars(select(PriceBar).where(PriceBar.ticker.in_(list(bars))))}
    n = 0
    for t, rows in bars.items():
        if not rows:
            errors.append({"ticker": t, "error": "no bars returned"})
        for b in rows:
            if b["session"] > cap:
                continue  # partial / unpublished session
            n += 1
            old = have.get((t, b["session"]))
            if old is None:
                db.add(PriceBar(ticker=t, **b))
            else:  # only rows whose values changed are written (yfinance may adjust recent bars)
                for k, v in b.items():
                    if k != "session" and getattr(old, k) != v:
                        setattr(old, k, v)
    db.commit()
    last = db.scalar(select(PriceBar.session).order_by(PriceBar.session.desc()).limit(1))
    _finish(db, run, "ok" if not errors else "partial", n, errors,
            datetime.combine(last, px.CLOSE) if last else None)


def seed_companies(db):
    port = load_portfolio()
    have = {c.ticker: c for c in db.scalars(select(Company).where(Company.ticker.in_([p["ticker"] for p in port])))}
    for p in port:
        co = have.get(p["ticker"]) or Company(ticker=p["ticker"])
        co.sector, co.in_portfolio = p["sector"], True
        db.add(co)
    if not db.get(Setting, "alerts"):
        db.add(Setting(key="alerts", value=DEFAULT_SETTINGS))
    db.commit()


DEMO_RESEARCH = Path(__file__).resolve().parent.parent / "data" / "demo" / "research"


def load_research_fixtures(db) -> int:
    """Research reports generated from real filings (python -m finn.research.run), bundled so the
    offline demo briefing can show promised vs delivered. Stored as they were produced, with their
    own generation date; nothing is edited."""
    from .models import ResearchJob
    n = 0
    for p in sorted(DEMO_RESEARCH.glob("*.json")):
        r = json.loads(p.read_text())
        at = datetime.fromisoformat(r["generated_at"])
        db.query(ResearchJob).filter(ResearchJob.ticker == r["ticker"]).delete()
        db.add(ResearchJob(ticker=r["ticker"], state=r["status"], report=r, cache_key=r.get("cache_key"),
                           doc_failures=r.get("failures", []), attempts=1, requested_via="demo-fixture",
                           created_at=at, updated_at=at, finished_at=at))
        n += 1
    db.commit()
    return n


def _refuse_live_target(mode: str):
    """The historical snapshot is only ever written to local SQLite, never to the live database."""
    if mode == "snapshot" and not dbmod.DB_URL.startswith("sqlite"):
        raise SystemExit(f"refusing to write the historical snapshot to {dbmod.redacted_url()}: "
                         "snapshot seeding is SQLite-only (unset FINN_DB_URL)")
    if mode == "snapshot":
        from sqlalchemy import inspect
        if "ingest_run" in inspect(dbmod.engine).get_table_names():
            with Session() as db:
                if db.scalar(select(IngestRun.id).where(IngestRun.mode == "live").limit(1)):
                    raise SystemExit("refusing to write the historical snapshot into a database with live runs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["snapshot", "live"])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--skip-prices", action="store_true")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--record", metavar="DIR", help="fetch live and record every response to DIR")
    g.add_argument("--replay", metavar="DIR", help="rebuild offline from a recorded snapshot")
    a = ap.parse_args()
    if a.record:
        snapshot.configure("record", a.record)
        snapshot.set_captured_at(px.now_ist())
    elif a.replay:
        snapshot.configure("replay", a.replay)
    _refuse_live_target(a.mode)
    dbmod.init_db()
    with Session() as db:
        seed_companies(db)
        tickers = [p["ticker"] for p in load_portfolio()]
        raw = ingest_announcements(db, NSE(), tickers, a.days, a.mode)
        rebuild_events(db, tickers, raw, a.mode)
        if not a.skip_prices:
            ingest_prices(db, tickers, a.mode)
        if a.mode == "snapshot":
            print(f"research fixtures loaded: {load_research_fixtures(db)}")
        for r in db.scalars(select(IngestRun).order_by(IngestRun.id.desc()).limit(3)):
            print(f"{r.source:<18} {r.status:<8} items={r.items:<5} through={r.data_through} errors={len(r.errors)}")


if __name__ == "__main__":
    main()
