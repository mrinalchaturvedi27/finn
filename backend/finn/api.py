"""FINN HTTP API (milestone 1: brief, event detail, settings, freshness)."""
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import prices as px
from . import startup_probe
from .classify import tier
from . import db as dbmod
from .db import Session
from .ingest import DEFAULT_SETTINGS
from .models import Alert, Company, Event, Filing, IngestRun, MetricObs, PriceBar, Setting

# Deployed demo stays read-only (FINN_READ_ONLY=1): CORS only restrains browsers, not direct calls.
READ_ONLY = os.environ.get("FINN_READ_ONLY") == "1"
SNAPSHOT_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "snapshot" / "manifest.json"
BOOTED_AT = datetime.now().isoformat(timespec="seconds")

app = FastAPI(title="FINN")
# Read-only still allows POST /api/research/{ticker}: it only queues a research job (validated, capped).
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("FINN_CORS", "*").split(","),
                   allow_methods=["GET", "POST"] if READ_ONLY else ["GET", "POST", "PUT"], allow_headers=["*"])

# Describes the real schedule of the deployment (set where the worker is scheduled); not a promise.
SCHEDULE_NOTE = os.environ.get("FINN_SCHEDULE_NOTE", "not scheduled (historical snapshot)")
CADENCE = {"nse_announcements": SCHEDULE_NOTE,
           "prices": "after each session's close, when the worker runs",
           "results_xbrl": "when a results filing is detected"}
# A source is overdue when its last successful check is older than this (scheduled runs can be
# delayed or dropped, so the line shows the actual last success either way).
_OVERDUE_H = float(os.environ.get("FINN_OVERDUE_HOURS", "3"))
OVERDUE_AFTER = {"nse_announcements": timedelta(hours=_OVERDUE_H), "prices": timedelta(hours=26 + 72),
                 "results_xbrl": timedelta(hours=_OVERDUE_H)}
WINDOWS = {"24h": timedelta(hours=24), "3d": timedelta(days=3), "7d": timedelta(days=7), "30d": timedelta(days=30)}


@app.on_event("startup")
def _startup():
    dbmod.use_for_api()
    startup_probe.start()


def _settings(db) -> dict:
    s = db.get(Setting, "alerts")
    return {**DEFAULT_SETTINGS, **(s.value if s else {})}


def _freshness(db) -> dict:
    out = {}
    for src in CADENCE:
        last_ok = db.scalar(select(IngestRun).where(IngestRun.source == src, IngestRun.status.in_(["ok", "partial"]))
                            .order_by(IngestRun.started_at.desc()).limit(1))
        last_any = db.scalar(select(IngestRun).where(IngestRun.source == src)
                             .order_by(IngestRun.started_at.desc()).limit(1))
        out[src] = {
            "cadence": CADENCE[src] if last_any and last_any.mode == "live" else "not scheduled (historical snapshot)",
            "last_checked": last_any.finished_at.isoformat() if last_any and last_any.finished_at else None,
            "last_status": last_any.status if last_any else None,
            "last_success": last_ok.finished_at.isoformat() if last_ok and last_ok.finished_at else None,
            "data_through": last_ok.data_through.isoformat() if last_ok and last_ok.data_through else None,
            "mode": last_ok.mode if last_ok else None,
            "errors": (last_any.errors or [])[:5] if last_any else [],
            "overdue": bool(last_any and last_any.mode == "live"
                            and (last_ok is None or px.now_ist() - last_ok.finished_at > OVERDUE_AFTER[src])),
        }
    return out


def _as_of(db, fresh) -> tuple[datetime, str]:
    """Snapshot data is anchored at its own capture time, so '24h' means the last 24h of the snapshot."""
    mode = fresh["nse_announcements"]["mode"] or "snapshot"
    if mode == "live":
        return px.now_ist(), mode
    t = fresh["nse_announcements"]["last_success"]
    return (datetime.fromisoformat(t) if t else px.now_ist()), mode


VIEW = Query("live", pattern="^(live|demo)$")
# The demo briefing is a real day from the recorded snapshot; relative times are anchored to it.
DEMO_AS_OF = datetime.fromisoformat(os.environ.get("FINN_DEMO_AS_OF", "2026-10-30T20:00:00"))
DEMO_LABEL = "Demo briefing — recorded NSE filings and prices, shown as of 30 Oct 2026, 20:00 IST"


@app.get("/api/meta")
def meta(view: str = VIEW):
    with dbmod.session_for(view) as db:
        fresh = _freshness(db)
        as_of, mode = _as_of(db, fresh)
        n = db.scalar(select(Company).where(Company.in_portfolio).limit(1))
        return {"mode": mode, "as_of": as_of.isoformat(), "freshness": fresh,
                "portfolio_size": len(db.scalars(select(Company.ticker).where(Company.in_portfolio)).all()),
                "has_data": n is not None,
                "label": ("Historical snapshot — not live. Filings and prices as captured at the time shown."
                          if mode == "snapshot" else None)}


def _event_out(e: Event, co: Company | None, n_filings: int) -> dict:
    res = (e.detail or {}).get("results")
    return {
        "id": e.id, "ticker": e.ticker, "company": co.name if co else e.ticker, "sector": co.sector if co else None,
        "category": e.category, "title": e.title, "summary": e.summary if e.summary != e.title else None,
        "occurred_at": e.occurred_at.isoformat(), "materiality": e.materiality, "tier": tier(e.materiality),
        "reasons": e.materiality_reasons, "read_state": e.read_state, "filings": n_filings,
        "has_detail": bool(res and res.get("status") != "failed"),
        "results_headline": _headline(res) if res and res.get("status") != "failed" else None,
    }


def _headline(card) -> list[dict]:
    keep = ("revenue", "nii", "ebitda_op_proxy", "pat")
    out = []
    for m in card["metrics"]:
        if m["id"] in keep and m["current"] is not None:
            out.append({"id": m["id"], "label": m["label"].replace(" (calculated)", "*"),
                        "value": m["current"], "yoy": m["yoy_q_change"], "qoq": m["prev_q_change"]})
    return out[:3]


@app.get("/api/brief")
def brief(window: str = Query("24h", pattern="^(24h|3d|7d|30d)$"), view: str = VIEW):
    with dbmod.session_for(view) as db:
        fresh = _freshness(db)
        as_of, mode = _as_of(db, fresh)
        if view == "demo":
            as_of, mode = DEMO_AS_OF, "demo"
        since = as_of - WINDOWS[window]
        events = db.scalars(select(Event).where(Event.occurred_at >= since, Event.occurred_at <= as_of)
                            .order_by(Event.materiality.desc(), Event.occurred_at.desc(), Event.id)).all()
        cos = {c.ticker: c for c in db.scalars(select(Company)).all()}
        counts = {}
        for f in db.scalars(select(Filing).where(Filing.filed_at >= since, Filing.filed_at <= as_of)).all():
            counts[f.event_id] = counts.get(f.event_id, 0) + 1
        out = {"top": [], "look": [], "routine": []}
        for e in events:
            ev = _event_out(e, cos.get(e.ticker), counts.get(e.id, 0))
            out[ev["tier"]].append(ev)
        st = _settings(db)
        movers = _movers(db, st, as_of)
        live_since = db.get(Setting, "live_since")
        return {"as_of": as_of.isoformat(), "mode": mode, "window": window, "since": since.isoformat(),
                "freshness": fresh, "tiers": out, "movers": movers, "settings": st,
                "alerts": _alerts(db, 20), "alerts_since": live_since.value["at"] if live_since else None,
                "data_source": "seed" if view == "demo" else dbmod.SOURCE,  # live | seed | seed_fallback
                "view": view,
                "reference": ({"as_of": DEMO_AS_OF.isoformat(), "label": DEMO_LABEL,
                               "captured_at": _manifest_captured_at()} if view == "demo" else None),
                "spotlight": _spotlight(db),
                "totals": {"events": len(events), "filings": sum(counts.values())}}


def _spotlight(db) -> dict | None:
    """The strongest checkable promised-vs-delivered item available (final verdicts before run-rates)."""
    from .models import ResearchJob
    rank = {"delivered": 0, "missed": 0, "partial": 1, "pending": 2}
    best = None
    for j in db.scalars(select(ResearchJob).where(ResearchJob.state.in_(["done", "partial"]))
                        .order_by(ResearchJob.finished_at.desc())):
        for g in (j.report or {}).get("guidance", []):
            st = g["verdict"]["status"]
            if st in rank and (best is None or rank[st] < best[0]):
                best = (rank[st], j, g)
    if not best:
        return None
    _, j, g = best
    return {"ticker": j.ticker, "company": (j.report or {}).get("company"), "generated_at": (j.report or {}).get("generated_at"),
            "summary": (j.report or {}).get("summary"),
            "item": {k: g[k] for k in ("metric_label", "period_label", "target", "quote", "page", "speaker", "stated_on",
                                       "source_url", "verdict")}}


def _alerts(db, limit: int) -> list[dict]:
    """In-app alerts, newest first. Read state is kept per viewer in the browser."""
    out = []
    for a in db.scalars(select(Alert).order_by(Alert.id.desc()).limit(limit)):
        d = a.detail or {}
        out.append({"id": a.id, "ticker": a.ticker, "kind": a.kind, "event_id": a.event_id,
                    "session": a.session.isoformat() if a.session else None,
                    "observed": a.observed, "threshold": a.threshold, "title": d.get("title"),
                    "category": d.get("category"), "change_pct": d.get("change_pct"),
                    "created_at": a.created_at.isoformat() if a.created_at else None})
    return out


@app.get("/api/alerts")
def alerts(limit: int = Query(50, ge=1, le=200)):
    with Session() as db:
        return _alerts(db, limit)


def _movers(db, st, as_of) -> dict:
    bars = {}
    for b in db.scalars(select(PriceBar)).all():
        bars.setdefault(b.ticker, []).append({"session": b.session, "close": b.close, "volume": b.volume})
    tickers = [c.ticker for c in db.scalars(select(Company).where(Company.in_portfolio).order_by(Company.ticker))]
    session = px.expected_session(bars, as_of, st["eod_buffer_min"])
    rows = [px.evaluate(t, bars.get(t, []), session, st["volume_multiple"], st["price_pct"]) for t in tickers]
    return {"session": session.isoformat() if session else None,
            "triggered": [r for r in rows if r.get("alerts")],
            "quiet": [r for r in rows if r["state"] == "ok" and not r.get("alerts")],
            "stale": [r for r in rows if r["state"] == "stale"]}


@app.get("/api/events/{event_id}")
def event_detail(event_id: int, view: str = VIEW):
    with dbmod.session_for(view) as db:
        e = db.get(Event, event_id)
        if not e:
            raise HTTPException(404, "event not found")
        co = db.get(Company, e.ticker)
        filings = db.scalars(select(Filing).where(Filing.event_id == e.id).order_by(Filing.filed_at, Filing.id)).all()
        later = 0
        if view == "demo":  # the demo is shown as of its reference date: nothing filed after it
            if e.occurred_at > DEMO_AS_OF:
                raise HTTPException(404, "not in the demo briefing")
            later = sum(f.filed_at > DEMO_AS_OF for f in filings)
            filings = [f for f in filings if f.filed_at <= DEMO_AS_OF]
        dups = db.scalars(select(Filing).where(Filing.duplicate_of.in_([f.id for f in filings]))).all() if filings else []
        return {
            **_event_out(e, co, len(filings)),
            "reporting_format": co.reporting_format if co else None,
            "filings": [{"id": f.id, "subject": f.subject, "text": f.text, "filed_at": f.filed_at.isoformat(),
                         "url": f.attachment_url, "exchange": f.exchange, "category": f.category,
                         "category_source": f.category_source, "is_primary": f.id == e.primary_filing_id}
                        for f in filings],
            "duplicates_hidden": len(dups),
            "later_filings_hidden": later,
            "results": (e.detail or {}).get("results"),
            "research": _research_brief(db, e.ticker),
        }


def _research_brief(db, ticker: str) -> dict | None:
    """For the event page's "Dig in" link: is there a report, and what does it say in one line?"""
    from .models import ResearchJob
    j = db.scalar(select(ResearchJob).where(ResearchJob.ticker == ticker, ResearchJob.state.in_(["done", "partial"]))
                  .order_by(ResearchJob.finished_at.desc()).limit(1))
    if not j:
        return None
    return {"ticker": ticker, "summary": (j.report or {}).get("summary"), "generated_at": (j.report or {}).get("generated_at")}


class SettingsIn(BaseModel):
    volume_multiple: float = Field(ge=1.0, le=20)
    price_pct: float = Field(ge=0.5, le=50)
    alert_categories: list[str]


@app.get("/api/settings")
def get_settings(response: Response):
    response.headers["x-finn-read-only"] = "1" if READ_ONLY else "0"
    with Session() as db:
        return {**_settings(db), "read_only": READ_ONLY}


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    if READ_ONLY:
        raise HTTPException(403, "This deployment is read-only.")
    with Session() as db:
        s = db.get(Setting, "alerts") or Setting(key="alerts", value={})
        s.value = {**_settings(db), **body.model_dump()}
        db.add(s)
        db.commit()
        return s.value


@app.get("/api/health")
def health():
    """Liveness plus a fingerprint of the seeded data, to check it survives restarts and redeploys."""
    with Session() as db:
        events = sorted(db.scalars(select(Event.group_key)))  # Python sort: DB collations differ
        obs = db.scalars(select(MetricObs.value).order_by(MetricObs.id)).all()
        n_obs = len(obs)
    digest = hashlib.sha256(json.dumps([events, obs], default=str).encode()).hexdigest()[:16]
    from .migrate import current
    return {"ok": True, "booted_at": BOOTED_AT, "commit": os.environ.get("RENDER_GIT_COMMIT"),
            "read_only": READ_ONLY,
            "database": {"source": dbmod.SOURCE, "fallback_reason": dbmod.FALLBACK_REASON,
                         "schema_version": current(dbmod.engine)},
            "seed": {"captured_at": _manifest_captured_at(), "events": len(events), "metric_obs": n_obs,
                     "fingerprint": digest}}


def _manifest_captured_at():
    try:
        return json.loads(SNAPSHOT_MANIFEST.read_text()).get("captured_at")
    except (OSError, ValueError):
        return None


# ---------- research (pull) ----------

def _research_row(j) -> dict:
    r = j.report or {}
    return {"ticker": j.ticker, "company": r.get("company"), "state": j.state,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "requested_at": j.created_at.isoformat() if j.created_at else None,
            "summary": r.get("summary"), "requested_via": j.requested_via}


@app.get("/api/research")
def research_index(view: str = VIEW):
    from .models import ResearchJob
    from .research.jobs import demo_tickers
    with dbmod.session_for(view) as db:
        done, open_jobs = {}, []
        for j in db.scalars(select(ResearchJob).order_by(ResearchJob.id.desc())):
            if j.state in ("queued", "running"):
                open_jobs.append(_research_row(j))
            elif j.state in ("done", "partial") and j.ticker not in done:
                done[j.ticker] = _research_row(j)
        return {"reports": sorted(done.values(), key=lambda r: r["ticker"]), "queue": open_jobs,
                "demo": demo_tickers(), "can_request": dbmod.SOURCE == "live" and view == "live",
                "schedule": SCHEDULE_NOTE if dbmod.SOURCE == "live" else None}


@app.get("/api/research/{ticker}")
def research_report(ticker: str, view: str = VIEW):
    from .models import ResearchJob
    t = ticker.upper()
    with dbmod.session_for(view) as db:
        last = db.scalar(select(ResearchJob).where(ResearchJob.ticker == t, ResearchJob.state.in_(["done", "partial"]))
                         .order_by(ResearchJob.finished_at.desc()).limit(1))
        pending = db.scalar(select(ResearchJob).where(ResearchJob.ticker == t, ResearchJob.state.in_(["queued", "running"]))
                            .limit(1))
        failed = db.scalar(select(ResearchJob).where(ResearchJob.ticker == t, ResearchJob.state == "failed")
                           .order_by(ResearchJob.id.desc()).limit(1))
        if not (last or pending or failed):
            raise HTTPException(404, "not researched yet")
        return {"ticker": t, "report": last.report if last else None,
                "pending": _research_row(pending) if pending else None,
                "failed": {**_research_row(failed), "failures": (failed.report or {}).get("failures", [])}
                if failed and (not last or failed.id > last.id) else None,
                "can_request": dbmod.SOURCE == "live" and view == "live"}


@app.post("/api/research/{ticker}")
def research_request(ticker: str):
    from .research.jobs import enqueue
    if dbmod.SOURCE != "live":
        raise HTTPException(503, "Research requests need the live database; this deployment is showing the snapshot.")
    with Session() as db:
        job, why = enqueue(db, ticker, "app", px.now_ist())
        if job is None:
            raise HTTPException(400 if why == "not an NSE symbol" else 429, why)
        return {**_research_row(job), "message": why, "schedule": SCHEDULE_NOTE}


@app.get("/api/probe-report")
def probe_report():
    """Only while FINN_STARTUP_PROBE=1; turn the flag off after capture."""
    if not startup_probe.enabled():
        raise HTTPException(404)
    st = dict(startup_probe.STATE)
    rep = st.pop("report_json", None)
    return {**st, "report": json.loads(rep) if rep else None}
