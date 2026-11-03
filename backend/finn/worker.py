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
from contextlib import contextmanager
from datetime import datetime, time as dtime, timedelta

from sqlalchemy import event, select, text

from . import live
from . import prices as px
from . import db as dbmod
from .db import DATA_DIR, Session
from .extract.results import build_results_card
from .ingest import (_finish, _run, _settings_or_default, ingest_announcements, ingest_prices, load_portfolio,
                     persist_observations, rebuild_events, seed_companies)
from .models import Company, Event, IngestRun
from .sources.nse import NSE, SourceError

MARKET_OPEN, MARKET_CLOSE = dtime(9, 0), dtime(15, 45)
PRICE_RETRY_UNTIL = dtime(21, 0)
LOCK_KEY = 0x46494E4E  # "FINN"
ABANDONED_AFTER = timedelta(minutes=30)  # longer than the job timeout


@contextmanager
def single_worker():
    """Yield True if this process holds the worker lock; False if another run is in progress.
    Postgres: session advisory lock (released if the runner dies). SQLite: a lock file."""
    if dbmod.engine.dialect.name == "postgresql":
        with dbmod.engine.connect() as c:
            # if this runner dies (job killed), the server closes the idle session and frees the lock;
            # longer than the 15 min job timeout so a live run never loses it
            c.execute(text("set idle_session_timeout = '20min'"))
            got = c.execute(text("select pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
            if not got and take_over_stale_lock(c):
                for _ in range(10):  # termination is a signal: the old session takes a moment to exit
                    time.sleep(1)
                    got = c.execute(text("select pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
                    if got:
                        break
            try:
                yield bool(got)
            finally:
                if got:
                    c.execute(text("select pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                c.commit()
    else:
        import fcntl
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "worker.lock", "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def take_over_stale_lock(c, idle_minutes: int = 30) -> bool:
    """End sessions that hold FINN's worker lock but have been idle longer than any run can take
    (a killed runner whose connection the server still thinks is open). Only that exact lock
    matches: advisory, single bigint key LOCK_KEY (classid 0, objsubid 1), this database, this
    user, granted, idle past the threshold. No other session can be selected."""
    pids = c.execute(text(
        "select a.pid from pg_locks l join pg_stat_activity a on a.pid = l.pid "
        "where l.locktype = 'advisory' and l.classid = 0 and l.objid = :k and l.objsubid = 1 and l.granted "
        "and l.database = (select oid from pg_database where datname = current_database()) "
        "and a.usename = current_user and a.pid <> pg_backend_pid() "
        "and a.state = 'idle' and a.state_change < now() - make_interval(mins => :m)"),
        {"k": LOCK_KEY, "m": idle_minutes}).scalars().all()
    for pid in pids:
        c.execute(text("select pg_terminate_backend(:p)"), {"p": pid})
        print(f"ended stale worker session {pid} (idle > {idle_minutes} min)", flush=True)
    return bool(pids)


def close_abandoned(db, now: datetime) -> int:
    """Runs left 'running' by a killed job (timeout, cancelled runner) are marked abandoned."""
    n = 0
    for r in db.scalars(select(IngestRun).where(IngestRun.status == "running",
                                                IngestRun.started_at < now - ABANDONED_AFTER)):
        r.status, r.finished_at = "abandoned", now
        r.errors = [*(r.errors or []), {"error": "run did not finish (job killed or timed out)"}]
        n += 1
    db.commit()
    return n


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
    from .research import jobs as rjobs
    if rjobs.needed(db, now):
        out.append("research")
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
    with single_worker() as mine:
        if not mine:
            print("another worker run holds the lock; skipping", flush=True)
            return []
        return _tick(now)


class _Stages:
    """Logs each stage's duration and database round trips, so a slow run explains itself."""
    def __init__(self):
        self.q = 0
        event.listen(dbmod.engine, "before_cursor_execute", self._count)

    def _count(self, *a, **k):
        self.q += 1

    @contextmanager
    def __call__(self, name: str):
        t, q = time.monotonic(), self.q
        print(f"  {name} ...", flush=True)
        try:
            yield
        finally:
            print(f"  {name} done in {time.monotonic() - t:.1f}s, {self.q - q} db round trips", flush=True)

    def close(self):
        event.remove(dbmod.engine, "before_cursor_execute", self._count)


def db_round_trip_ms() -> float:
    with dbmod.engine.connect() as c:
        c.execute(text("select 1"))  # connect outside the measurement
        t = time.monotonic()
        for _ in range(5):
            c.execute(text("select 1"))
        return (time.monotonic() - t) / 5 * 1000


def _tick(now: datetime) -> list[str]:
    nse = NSE()
    stage = _Stages()
    print(f"  db round trip {db_round_trip_ms():.0f} ms", flush=True)
    try:
        with Session() as db:
            with stage("setup"):
                close_abandoned(db, now)
                seed_companies(db)
                tickers = [p["ticker"] for p in load_portfolio()]
                jobs = due(db, now)
            print(f"  due: {', '.join(jobs) or 'nothing'}", flush=True)
            if "announcements" in jobs:
                with stage("announcements"):
                    windows = live.announcement_windows(db, tickers, now)
                    raw = ingest_announcements(db, nse, tickers, live.BACKFILL_DAYS, "live", windows=windows)
                    if raw:
                        live.mark_live_since(db, now)  # alerts only for what arrives after the first live run
                with stage("events and results cards"):
                    rebuild_events(db, tickers, raw, "live")
            if "prices" in jobs:
                with stage("prices"):
                    ingest_prices(db, tickers, "live")
            if "xbrl_recheck" in jobs:
                with stage("xbrl revision check"):
                    recheck_xbrl(db, nse, now)
            if "research" in jobs:
                from .research import jobs as rjobs
                with stage("research"):
                    for job in rjobs.targets(db, now):
                        done = rjobs.run(db, job, nse, now)
                        print(f"  research {done.ticker}: {done.state}", flush=True)
            with stage("alerts"):
                st = _settings_or_default(db)
                live.record_announcement_alerts(db, st)
                live.record_price_alerts(db, st, now)
                db.commit()
    finally:
        stage.close()
    return jobs


def report() -> str:
    """What the database holds after a run (no credentials): used to verify a deployment."""
    from sqlalchemy import func
    from .migrate import current
    from .models import Alert, Document, Filing, MetricObs, PriceBar
    lines = [f"database {dbmod.redacted_url()} schema v{current(dbmod.engine)}"]
    with Session() as db:
        counts = {m.__tablename__: db.scalar(select(func.count()).select_from(m))
                  for m in (Filing, Event, MetricObs, Document, PriceBar, Alert, IngestRun)}
        lines.append("rows " + " ".join(f"{k}={v}" for k, v in counts.items()))
        for src in ("nse_announcements", "results_xbrl", "prices", "results_xbrl_recheck"):
            r = db.scalar(select(IngestRun).where(IngestRun.source == src).order_by(IngestRun.started_at.desc()).limit(1))
            if r:
                secs = (r.finished_at - r.started_at).total_seconds() if r.finished_at else None
                lines.append(f"last {src}: {r.status} items={r.items} errors={len(r.errors or [])} "
                             f"started={r.started_at:%Y-%m-%d %H:%M} took={secs and round(secs)}s "
                             f"through={r.data_through} mode={r.mode}")
        lines.append(f"cursors={len(live.get_cursors(db))} live_since={live.live_since(db)}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--report", action="store_true", help="print what the database holds and exit")
    a = ap.parse_args()
    from .migrate import require_latest
    dbmod.init_db()  # local SQLite only; hosted databases are migrated explicitly
    require_latest(dbmod.engine)
    if a.report:
        print(report())
        return
    print(f"worker using {dbmod.redacted_url()}", flush=True)
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
            print(report(), flush=True)
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
