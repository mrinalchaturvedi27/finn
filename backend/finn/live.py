"""Live-pipeline rules: backfill windows, revisions, when to (re)build results cards, alerts.

Kept separate from the scheduler (finn.worker) so each rule is testable offline.
"""
import re
from datetime import date, datetime, timedelta

from sqlalchemy import select

from . import prices as px
from .classify import tier
from .events import MONTHS
from .extract.results import pick_filings
from .models import Alert, Company, Event, Filing, PriceBar, Setting

BACKFILL_DAYS = 30
OVERLAP = timedelta(days=2)  # re-read the tail so late-indexed filings are not missed
CARD_RETRY = timedelta(hours=2)  # XBRL often lands hours after the outcome PDF
CARD_RETRY_FOR = timedelta(days=10)
XBRL_RECHECK_FOR = timedelta(days=45)

REVISION_RX = re.compile(r"\b(corrigendum|addendum|erratum|errata|rectification|revised|revision)\b", re.I)


# ---------- announcement windows ----------

def announcement_windows(db, tickers: list[str], now: datetime, backfill_days: int = BACKFILL_DAYS) -> dict:
    """Per ticker (start, end, is_backfill): from the ticker's last successful fetch minus overlap, so a
    missed or failed run is backfilled by the next one; a ticker never fetched gets the full backfill."""
    cursors = get_cursors(db)
    out = {}
    for t in tickers:
        last_ok = datetime.fromisoformat(cursors[t]) if t in cursors else None
        if last_ok is None:
            out[t] = (now.date() - timedelta(days=backfill_days), now.date(), True)
        else:
            start = max(last_ok - OVERLAP, now - timedelta(days=backfill_days))  # cap very long outages
            out[t] = (min(start.date(), now.date()), now.date(), False)
    return out


def get_cursors(db) -> dict:
    s = db.get(Setting, "announcement_cursors")
    return dict(s.value) if s else {}


def set_cursor(db, ticker: str, fetched_at: datetime):
    """Record a successful fetch for this ticker (called only when the exchange call succeeded)."""
    s = db.get(Setting, "announcement_cursors") or Setting(key="announcement_cursors", value={})
    s.value = {**(s.value or {}), ticker: fetched_at.isoformat()}  # reassign so the JSON change is saved
    db.add(s)


# ---------- revisions ----------

def link_revisions(db, ticker: str) -> int:
    """A corrigendum/addendum/revised filing points at the earlier filing it amends.

    If it cites a date ("our letter dated September 30, 2026"), the target must be filed on that
    day or the next; otherwise the target is the filing within 30 days sharing the most subject
    words (at least 3). Unmatched revisions stay standalone rather than guessing (e.g. the cited
    letter predates the ingestion window).
    """
    fs = db.scalars(select(Filing).where(Filing.ticker == ticker, Filing.duplicate_of.is_(None))
                    .order_by(Filing.filed_at, Filing.id)).all()
    n = 0
    for i, f in enumerate(fs):
        if f.revision_of or not REVISION_RX.search(f"{f.subject} {f.text or ''}"[:400]):
            continue
        body = f"{f.subject} {f.text or ''}"
        words, cited = _words(body), _cited_date(body)
        best, best_score = None, -1
        for g in fs[:i]:
            if REVISION_RX.search(g.subject):
                continue
            if cited:
                if g.filed_at.date() not in (cited, cited + timedelta(days=1)):
                    continue
            elif g.filed_at < f.filed_at - timedelta(days=30):
                continue
            score = len(words & _words(f"{g.subject} {g.text or ''}"))
            if score > best_score or (score == best_score and g.filed_at > best.filed_at):
                best, best_score = g, score
        if best is not None and (cited or best_score >= 3):
            f.revision_of = best.id
            n += 1
    return n


STOP = {"the", "of", "and", "to", "for", "in", "on", "a", "an", "with", "by", "under", "regulation", "sebi",
        "listing", "obligations", "disclosure", "requirements", "regulations", "2015", "has", "informed",
        "exchange", "company", "limited", "ltd", "dated", "is", "that", "be", "as", "at", "from", "this"}


CITED_RX = re.compile(r"dated\s+(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*\.?,?\s+(\d{4})"
                      r"|dated\s+([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)


def _cited_date(s: str) -> date | None:
    m = CITED_RX.search(s)
    if not m:
        return None
    d, mon, y = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(5), m.group(4), m.group(6))
    try:
        return date(int(y), MONTHS[mon[:3].lower()], int(d))
    except (KeyError, ValueError):
        return None


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in STOP and not REVISION_RX.fullmatch(w)}


# ---------- results cards ----------

def card_due(e: Event, n_members: int, now: datetime) -> str | None:
    """Why this results event's card should be (re)built now, or None."""
    d = e.detail or {}
    card, att = d.get("results"), d.get("results_attempt") or {}
    if card is None:
        return "no card yet"
    if att.get("n_members", n_members) < n_members:
        return "new filings joined the event"
    if card.get("status") in ("failed", "partial") and now - e.occurred_at < CARD_RETRY_FOR:
        last = datetime.fromisoformat(att["at"]) if att.get("at") else None
        if last is None or now - last >= CARD_RETRY:
            return f"retry {card.get('status')} card"
    return None


def xbrl_signature(card: dict) -> dict:
    return {k: p.get("xbrl_url") for k, p in (card.get("periods") or {}).items()}


def xbrl_revised(card: dict, index: list[dict], qe: date) -> bool:
    """True when the exchange now has a later XBRL revision for any period the card used."""
    if not card.get("periods"):
        return False
    _basis, picked = pick_filings(index, qe)
    now_sig = {k: v["row"].get("xbrl") for k, v in picked.items()}
    old = xbrl_signature(card)
    return any(now_sig.get(k) and now_sig[k] != old.get(k) for k in old)


# ---------- alerts ----------

def live_since(db) -> datetime | None:
    s = db.get(Setting, "live_since")
    return datetime.fromisoformat(s.value["at"]) if s else None


def mark_live_since(db, at: datetime):
    if not db.get(Setting, "live_since"):
        db.add(Setting(key="live_since", value={"at": at.isoformat()}))
        db.flush()


def _exists(db, **kw) -> bool:
    q = select(Alert.id)
    for k, v in kw.items():
        col = getattr(Alert, k)
        q = q.where(col.is_(None) if v is None else col == v)
    return db.scalar(q.limit(1)) is not None


def record_announcement_alerts(db, settings: dict) -> int:
    """One alert per event in an alerting category and tier, filed after live ingestion started.
    Backfilled history never alerts."""
    since = live_since(db)
    if since is None:
        return 0
    n = 0
    for e in db.scalars(select(Event).where(Event.occurred_at >= since,
                                            Event.category.in_(settings["alert_categories"]))).all():
        if tier(e.materiality) == "routine" or _exists(db, kind="announcement", event_id=e.id):
            continue
        db.add(Alert(ticker=e.ticker, kind="announcement", event_id=e.id, session=None, created_at=px.now_ist(),
                     observed=e.materiality, threshold=None,
                     detail={"title": e.title, "category": e.category, "occurred_at": e.occurred_at.isoformat()}))
        n += 1
    return n


def record_price_alerts(db, settings: dict, now: datetime) -> dict:
    """Evaluate each ticker on its own: a stale ticker is reported, not alerted, and is
    evaluated when its bar arrives on a later run."""
    bars = {}
    for b in db.scalars(select(PriceBar)).all():
        bars.setdefault(b.ticker, []).append({"session": b.session, "close": b.close, "volume": b.volume})
    tickers = db.scalars(select(Company.ticker).where(Company.in_portfolio).order_by(Company.ticker)).all()
    session = px.expected_session(bars, now, settings["eod_buffer_min"])
    new, stale = 0, []
    for t in tickers:
        r = px.evaluate(t, bars.get(t, []), session, settings["volume_multiple"], settings["price_pct"])
        if r["state"] == "stale":
            stale.append(t)
            continue
        for a in r["alerts"]:
            if _exists(db, ticker=t, kind=a["kind"], session=session, event_id=None):
                continue
            db.add(Alert(ticker=t, kind=a["kind"], session=session, observed=a["observed"], created_at=now,
                         threshold=a["threshold"], detail={"close": r.get("close"),
                                                           "change_pct": r.get("change_pct")}))
            new += 1
    return {"session": session, "new": new, "stale": stale}


def drop_orphan_events(db, ticker: str) -> int:
    """Events left with no filings after regrouping (e.g. an outcome moved into its results event)."""
    used = set(db.scalars(select(Filing.event_id).where(Filing.ticker == ticker, Filing.event_id.is_not(None))))
    n = 0
    for e in db.scalars(select(Event).where(Event.ticker == ticker)).all():
        if e.id not in used and not db.scalar(select(Alert.id).where(Alert.event_id == e.id).limit(1)):
            db.delete(e)
            n += 1
    return n
