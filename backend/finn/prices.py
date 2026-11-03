"""EOD bars and per-ticker threshold evaluation.

- A session's bar is only used once the close + publication buffer has passed
  (yfinance returns a partial bar during market hours).
- Volume baseline = mean of the previous 20 *completed* sessions, excluding the
  session being evaluated.
- Each ticker is evaluated on its own; a ticker without the expected session's
  bar is marked stale and does not block the rest.
"""
from datetime import date, datetime, time, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CLOSE = time(15, 30)
BASELINE_SESSIONS = 20


def now_ist() -> datetime:
    from . import snapshot
    if snapshot.MODE == "replay" and snapshot.CAPTURED_AT:
        return snapshot.CAPTURED_AT  # replay runs on the capture clock
    return datetime.now(IST).replace(tzinfo=None)


def latest_complete_session(at: datetime, buffer_min: int = 90) -> date:
    """Most recent weekday whose close + buffer has passed (exchange holidays handled by caller)."""
    d = at.date()
    if at.time() < (datetime.combine(d, CLOSE) + timedelta(minutes=buffer_min)).time():
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fetch_bars(tickers: list[str], period: str = "90d") -> dict[str, list[dict]]:
    import yfinance as yf

    df = yf.download([f"{t}.NS" for t in tickers], period=period, group_by="ticker",
                     progress=False, auto_adjust=False, threads=True)
    out = {}
    for t in tickers:
        try:
            sub = df[f"{t}.NS"].dropna(how="all")
        except KeyError:
            out[t] = []
            continue
        out[t] = [{"session": idx.date(), "open": _f(r["Open"]), "high": _f(r["High"]), "low": _f(r["Low"]),
                   "close": _f(r["Close"]), "volume": _f(r["Volume"])} for idx, r in sub.iterrows()]
    return out


def _f(v):
    try:
        v = float(v)
        return None if v != v else v  # NaN -> None
    except (TypeError, ValueError):
        return None


def expected_session(bars_by_ticker: dict[str, list[dict]], at: datetime, buffer_min: int = 90) -> date | None:
    """Latest complete weekday, capped at the newest session any ticker actually has (covers holidays)."""
    cap = latest_complete_session(at, buffer_min)
    have = [b["session"] for bars in bars_by_ticker.values() for b in bars if b["session"] <= cap]
    return max(have) if have else None


def evaluate(ticker: str, bars: list[dict], session: date | None, volume_multiple: float, price_pct: float) -> dict:
    bars = sorted((b for b in bars if session and b["session"] <= session), key=lambda b: b["session"])
    res = {"ticker": ticker, "session": session.isoformat() if session else None, "state": "ok", "alerts": []}
    if not bars or bars[-1]["session"] != session:
        last = bars[-1]["session"].isoformat() if bars else None
        return {**res, "state": "stale", "last_session": last,
                "why": f"no bar for {session} (last: {last})"}
    cur = bars[-1]
    prior = [b for b in bars[:-1] if b["volume"] is not None][-BASELINE_SESSIONS:]
    res.update(close=cur["close"], volume=cur["volume"])
    if len(bars) >= 2 and bars[-2]["close"] and cur["close"] is not None:
        chg = (cur["close"] / bars[-2]["close"] - 1) * 100
        res["change_pct"] = chg
        if abs(chg) >= price_pct:
            res["alerts"].append({"kind": "price", "observed": chg, "threshold": price_pct})
    if len(prior) >= BASELINE_SESSIONS and cur["volume"] is not None:
        base = mean(b["volume"] for b in prior)
        if base > 0:
            ratio = cur["volume"] / base
            res["volume_ratio"] = ratio
            if ratio >= volume_multiple:
                res["alerts"].append({"kind": "volume", "observed": ratio, "threshold": volume_multiple,
                                      "baseline_sessions": BASELINE_SESSIONS})
    else:
        res["volume_ratio"] = None
        res["volume_note"] = f"needs {BASELINE_SESSIONS} prior sessions, have {len(prior)}"
    res["spark"] = [b["close"] for b in bars[-20:]]
    return res
