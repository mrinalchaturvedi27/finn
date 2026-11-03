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
from .db import Session, init_db
from .ingest import DEFAULT_SETTINGS
from .models import Alert, Company, Event, Filing, IngestRun, MetricObs, PriceBar, Setting

# Deployed demo stays read-only (FINN_READ_ONLY=1): CORS only restrains browsers, not direct calls.
READ_ONLY = os.environ.get("FINN_READ_ONLY") == "1"
SNAPSHOT_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "snapshot" / "manifest.json"
BOOTED_AT = datetime.now().isoformat(timespec="seconds")

app = FastAPI(title="FINN")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("FINN_CORS", "*").split(","),
                   allow_methods=["GET"] if READ_ONLY else ["GET", "PUT"], allow_headers=["*"])

CADENCE = {"nse_announcements": "every 15 min in market hours, hourly otherwise",
           "prices": "once per session, 90 min after the 15:30 close",
           "results_xbrl": "when a results filing is detected"}
# A source is overdue when its last check is older than twice its longest scheduled interval.
OVERDUE_AFTER = {"nse_announcements": timedelta(hours=2), "prices": timedelta(hours=26 + 72),
                 "results_xbrl": timedelta(hours=2)}
WINDOWS = {"24h": timedelta(hours=24), "3d": timedelta(days=3), "7d": timedelta(days=7), "30d": timedelta(days=30)}


@app.on_event("startup")
def _startup():
    init_db()
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
            "cadence": CADENCE[src],
            "last_checked": last_any.finished_at.isoformat() if last_any and last_any.finished_at else None,
            "last_status": last_any.status if last_any else None,
            "last_success": last_ok.finished_at.isoformat() if last_ok and last_ok.finished_at else None,
            "data_through": last_ok.data_through.isoformat() if last_ok and last_ok.data_through else None,
            "mode": last_ok.mode if last_ok else None,
            "errors": (last_any.errors or [])[:5] if last_any else [],
            "overdue": bool(last_any and last_any.mode == "live" and last_any.finished_at
                            and px.now_ist() - last_any.finished_at > OVERDUE_AFTER[src]),
        }
    return out


def _as_of(db, fresh) -> tuple[datetime, str]:
    """Snapshot data is anchored at its own capture time, so '24h' means the last 24h of the snapshot."""
    mode = fresh["nse_announcements"]["mode"] or "snapshot"
    if mode == "live":
        return px.now_ist(), mode
    t = fresh["nse_announcements"]["last_success"]
    return (datetime.fromisoformat(t) if t else px.now_ist()), mode


@app.get("/api/meta")
def meta():
    with Session() as db:
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
def brief(window: str = Query("24h", pattern="^(24h|3d|7d|30d)$")):
    with Session() as db:
        fresh = _freshness(db)
        as_of, mode = _as_of(db, fresh)
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
                "totals": {"events": len(events), "filings": sum(counts.values())}}


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
def event_detail(event_id: int):
    with Session() as db:
        e = db.get(Event, event_id)
        if not e:
            raise HTTPException(404, "event not found")
        co = db.get(Company, e.ticker)
        filings = db.scalars(select(Filing).where(Filing.event_id == e.id).order_by(Filing.filed_at, Filing.id)).all()
        dups = db.scalars(select(Filing).where(Filing.duplicate_of.in_([f.id for f in filings]))).all() if filings else []
        return {
            **_event_out(e, co, len(filings)),
            "reporting_format": co.reporting_format if co else None,
            "filings": [{"id": f.id, "subject": f.subject, "text": f.text, "filed_at": f.filed_at.isoformat(),
                         "url": f.attachment_url, "exchange": f.exchange, "category": f.category,
                         "category_source": f.category_source, "is_primary": f.id == e.primary_filing_id}
                        for f in filings],
            "duplicates_hidden": len(dups),
            "results": (e.detail or {}).get("results"),
        }


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
    return {"ok": True, "booted_at": BOOTED_AT, "commit": os.environ.get("RENDER_GIT_COMMIT"),
            "read_only": READ_ONLY,
            "seed": {"captured_at": _manifest_captured_at(), "events": len(events), "metric_obs": n_obs,
                     "fingerprint": digest}}


def _manifest_captured_at():
    try:
        return json.loads(SNAPSHOT_MANIFEST.read_text()).get("captured_at")
    except (OSError, ValueError):
        return None


@app.get("/api/probe-report")
def probe_report():
    """Only while FINN_STARTUP_PROBE=1; turn the flag off after capture."""
    if not startup_probe.enabled():
        raise HTTPException(404)
    st = dict(startup_probe.STATE)
    rep = st.pop("report_json", None)
    return {**st, "report": json.loads(rep) if rep else None}
