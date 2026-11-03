"""Live ingestion scheduler.

    python -m finn.worker            # loop: check every minute what is due
    python -m finn.worker --once     # one tick (for cron-style hosts)

What is due is decided from the ingest_run log, so a tick is stateless and safe to repeat:
  - announcements: every 15 min in market hours (Mon-Fri 09:00-15:45 IST), hourly otherwise;
    the first run backfills 30 days, later runs fetch from the last filing minus 2 days.
  - prices: once per session, 90 min after the 15:30 close; retried hourly until 21:00 while
    any ticker is still missing that session's bar.
  - results XBRL recheck: once a day, for results events from the last 45 days.
Exchange holidays are not modelled: a holiday just produces an empty or stale run.
"""
import argparse
import time
from datetime import datetime, time as dtime, timedelta

from sqlalchemy import select

from . import live
from . import prices as px
from .db import Session, init_db
from .extract.results import build_results_card
from .ingest import (_finish, _run, _settings_or_default, ingest_announcements, ingest_prices, load_portfolio,
                     persist_observations, rebuild_events, seed_companies)
from .models import Company, Event, IngestRun
from .sources.nse import NSE, SourceError

MARKET_OPEN, MARKET_CLOSE = dtime(9, 0), dtime(15, 45)
PRICE_RETRY_UNTIL = dtime(21, 0)


def market_hours(now: datetime) -> bool:
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def _last(db, source: str) -> IngestRun | None:
    return db.scalar(select(IngestRun).where(IngestRun.source == source, IngestRun.mode == "live")
                     .order_by(IngestRun.started_at.desc()).limit(1))


def due(db, now: datetime) -> list[str]:
    out = []
    a = _last(db, "nse_announcements")
    every = timedelta(minutes=15) if market_hours(now) else timedelta(hours=1)
    if a is None or now - a.started_at >= every:
        out.append("announcements")

    st = _settings_or_default(db)
    session = px.latest_complete_session(now, st["eod_buffer_min"])
    p = _last(db, "prices")
    have = p.data_through.date() if p and p.data_through else None
    published = datetime.combine(session, px.CLOSE) + timedelta(minutes=st["eod_buffer_min"])
    retry_ok = p is None or p.started_at < published or now - p.started_at >= timedelta(hours=1)
    if (have is None or have < session) and retry_ok:
        out.append("prices")  # first try after the session is published, then hourly
    elif p and p.errors and p.started_at.date() == now.date() and now.time() <= PRICE_RETRY_UNTIL and retry_ok:
        out.append("prices")  # some tickers still lack the session's bar

    x = _last(db, "results_xbrl_recheck")
    if x is None or x.started_at.date() < now.date():
        out.append("xbrl_recheck")
    return out


def recheck_xbrl(db, nse: NSE, now: datetime):
    """Rebuild a results card when the exchange has published a later XBRL revision."""
    run = _run(db, "results_xbrl_recheck", "live")
    errors, n = [], 0
    events = db.scalars(select(Event).where(Event.category == "results",
                                            Event.occurred_at >= now - live.XBRL_RECHECK_FOR)).all()
    index_cache = {}
    for e in events:
        card = (e.detail or {}).get("results")
        if not card or card.get("status") == "failed":
            continue
        from datetime import date
        qe = date.fromisoformat(card["quarter_end"])
        try:
            idx = index_cache.get(e.ticker) or index_cache.setdefault(e.ticker, nse.results_index(e.ticker))
        except SourceError as ex:
            errors.append({"ticker": e.ticker, "error": str(ex)})
            continue
        if not live.xbrl_revised(card, idx, qe):
            continue
        co = db.get(Company, e.ticker)
        try:
            ann = nse.announcements(e.ticker, e.occurred_at.date() - timedelta(days=3), now.date())
        except SourceError:
            ann = []
        new = build_results_card(nse, e.ticker, co.name if co else None, qe, ann)
        if new["status"] == "failed":
            errors.append({"ticker": e.ticker, "error": "revised XBRL card failed", "problems": new["problems"]})
            continue
        e.detail = {**e.detail, "results": new,
                    "results_attempt": {**(e.detail.get("results_attempt") or {}), "at": now.isoformat(),
                                        "why": "later XBRL revision published"},
                    "xbrl_revisions": [*(e.detail.get("xbrl_revisions") or []),
                                       {"at": now.isoformat(), "previous": live.xbrl_signature(card)}]}
        persist_observations(db, e.ticker, new, e.primary_filing_id)
        n += 1
    db.commit()
    _finish(db, run, "ok" if not errors else "partial", n, errors, now)


def tick(now: datetime | None = None) -> list[str]:
    now = now or px.now_ist()
    nse = NSE()
    with Session() as db:
        seed_companies(db)
        tickers = [p["ticker"] for p in load_portfolio()]
        jobs = due(db, now)
        if "announcements" in jobs:
            windows = live.announcement_windows(db, tickers, now)
            raw = ingest_announcements(db, nse, tickers, live.BACKFILL_DAYS, "live", windows=windows)
            if raw:
                live.mark_live_since(db, now)  # alerts only for what arrives after the first live run
            rebuild_events(db, tickers, raw, "live")
        if "prices" in jobs:
            ingest_prices(db, tickers, "live")
        if "xbrl_recheck" in jobs:
            recheck_xbrl(db, nse, now)
        st = _settings_or_default(db)
        live.record_announcement_alerts(db, st)
        live.record_price_alerts(db, st, now)
        db.commit()
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    init_db()
    while True:
        try:
            jobs = tick()
            if jobs:
                print(f"{px.now_ist():%Y-%m-%d %H:%M} ran {', '.join(jobs)}", flush=True)
        except Exception as e:  # keep the loop alive; the failure is in ingest_run / logs
            print(f"{px.now_ist():%Y-%m-%d %H:%M} tick failed: {e!r}", flush=True)
            if a.once:
                raise
        if a.once:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
