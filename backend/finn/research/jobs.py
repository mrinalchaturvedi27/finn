"""Research jobs: what the worker should research on this tick, and running one job."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from ..models import ResearchJob

TICKER = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")
MAX_QUEUED = 10
PER_TICK = 3
DEMO_REFRESH = timedelta(hours=24)
PORTFOLIO = Path(__file__).resolve().parents[2] / "portfolio.json"


def demo_tickers() -> list[str]:
    p = json.loads(PORTFOLIO.read_text())
    return p.get("research_demo", []) + p.get("unseen_check", [])


def latest(db, ticker: str) -> ResearchJob | None:
    """Newest finished report for the ticker (done or partial), else None."""
    return db.scalar(select(ResearchJob).where(ResearchJob.ticker == ticker, ResearchJob.state.in_(["done", "partial"]))
                     .order_by(ResearchJob.finished_at.desc()).limit(1))


def enqueue(db, ticker: str, via: str, now: datetime) -> tuple[ResearchJob | None, str]:
    ticker = ticker.upper().strip()
    if not TICKER.match(ticker):
        return None, "not an NSE symbol"
    open_job = db.scalar(select(ResearchJob).where(ResearchJob.ticker == ticker,
                                                   ResearchJob.state.in_(["queued", "running"])).limit(1))
    if open_job:
        return open_job, "already queued"
    n = db.query(ResearchJob).filter(ResearchJob.state == "queued").count()
    if n >= MAX_QUEUED:
        return None, "queue full"
    j = ResearchJob(ticker=ticker, state="queued", requested_via=via, created_at=now, updated_at=now, attempts=0,
                    doc_failures=[])
    db.add(j)
    db.commit()
    return j, "queued"


def needed(db, now: datetime) -> bool:
    """Read-only: is there a queued request or a demo report to refresh? (used by the schedule)"""
    if db.scalar(select(ResearchJob.id).where(ResearchJob.state == "queued").limit(1)):
        return True
    for t in demo_tickers():
        last = latest(db, t)
        if not (last and last.finished_at and now - last.finished_at < DEMO_REFRESH):
            return True
    return False


def targets(db, now: datetime) -> list[ResearchJob]:
    """Queued requests first, then demo companies whose report is missing or over a day old."""
    jobs = list(db.scalars(select(ResearchJob).where(ResearchJob.state == "queued")
                           .order_by(ResearchJob.created_at).limit(PER_TICK)))
    for t in demo_tickers():
        if len(jobs) >= PER_TICK:
            break
        last = latest(db, t)
        if any(j.ticker == t for j in jobs) or (last and last.finished_at and now - last.finished_at < DEMO_REFRESH):
            continue
        j, _ = enqueue(db, t, "demo", now)
        if j and j.state == "queued" and j not in jobs:
            jobs.append(j)
    return jobs


def run(db, job: ResearchJob, nse, now: datetime, research_fn=None):
    from .run import research
    research_fn = research_fn or research
    job.state, job.attempts, job.updated_at = "running", (job.attempts or 0) + 1, now
    db.commit()
    try:
        report = research_fn(job.ticker, now.date(), nse, log=lambda m: print(m, flush=True))
    except Exception as e:  # recorded on the job; the tick carries on
        report = {"ticker": job.ticker, "status": "failed",
                  "failures": [{"stage": "research", "error": f"{type(e).__name__}: {str(e)[:200]}"}]}
    job.report = report
    job.state = report.get("status", "failed")
    job.cache_key = report.get("cache_key")
    job.doc_failures = report.get("failures", [])
    job.finished_at = job.updated_at = now
    db.commit()
    return job
