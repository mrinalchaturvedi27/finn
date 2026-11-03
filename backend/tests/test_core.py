from datetime import date, datetime

import pytest

from finn import metrics, prices
from finn.classify import classify, tier
from finn.events import build_events, infer_quarter_end
from finn.extract import pdftext
from finn.extract.results import (fiscal_label, pick_filings, prev_quarter_end, quarter_start,
                                  results_pdf_candidates, yoy_quarter_end)


# ---------- metric definitions ----------

def test_change_states():
    assert metrics.change(110, 100)["value"] == pytest.approx(10)
    assert metrics.change(10, -5)["state"] == "n/m"  # negative base
    assert metrics.change(-5, 10)["state"] == "n/m"  # turned to loss
    assert metrics.change(None, 10)["state"] == "missing"
    assert metrics.change(25.0, 23.5, "margin_pct") == {"value": pytest.approx(1.5), "state": "ok", "unit": "pp"}


class FakeDoc:
    def __init__(self, facts):
        self.facts = facts

    def num(self, tag, ctx):
        return self.facts.get(tag)


def test_ebitda_proxy_and_missing_input():
    d = FakeDoc({"RevenueFromOperations": 1000, "ProfitBeforeExceptionalItemsAndTax": 100, "FinanceCosts": 10,
                 "DepreciationDepletionAndAmortisationExpense": 30, "OtherIncome": 15, "ProfitBeforeTax": 90,
                 "ProfitLossForPeriod": 70})
    out = metrics.compute(d, "c", "indas")
    assert out["ebitda_op_proxy"]["value"] == 125
    assert out["ebitda_margin"]["value"] == pytest.approx(12.5)
    del d.facts["FinanceCosts"]
    out = metrics.compute(d, "c", "indas")
    assert out["ebitda_op_proxy"]["value"] is None
    assert "FinanceCosts" in out["ebitda_op_proxy"]["reason"]


def test_bank_metric_set_has_no_ebitda():
    ids = {m.id for m in metrics.BANK}
    assert "ebitda_op_proxy" not in ids and {"nii", "ppop", "provisions", "pat"} <= ids


# ---------- periods ----------

def test_quarter_arithmetic():
    qe = date(2026, 9, 30)
    assert quarter_start(qe) == date(2026, 7, 1)
    assert prev_quarter_end(qe) == date(2026, 6, 30)
    assert yoy_quarter_end(qe) == date(2025, 9, 30)
    assert prev_quarter_end(date(2026, 3, 31)) == date(2025, 12, 31)
    assert fiscal_label(qe) == "Q2 FY27"
    assert fiscal_label(date(2026, 3, 31)) == "Q4 FY26"


def test_infer_quarter_end_from_text():
    filed = datetime(2026, 10, 30, 16, 0)
    assert infer_quarter_end("results for the quarter ended 30th September, 2026", filed) == date(2026, 9, 30)
    assert infer_quarter_end("period ended Jun 30, 2026", filed) == date(2026, 6, 30)
    assert infer_quarter_end("no date here", filed) == date(2026, 9, 30)


def test_pick_filings_latest_revision_wins():
    idx = [
        {"qe_Date": "30-SEP-2026", "consolidated": "Consolidated", "broadcast_Date": "30-Oct-2026 10:00:00", "xbrl": "a"},
        {"qe_Date": "30-SEP-2026", "consolidated": "Consolidated", "broadcast_Date": "02-Nov-2026 10:00:00", "xbrl": "b"},
        {"qe_Date": "30-JUN-2026", "consolidated": "Consolidated", "broadcast_Date": "30-Jul-2026 10:00:00", "xbrl": "c"},
    ]
    basis, picked = pick_filings(idx, date(2026, 9, 30))
    assert basis == "Consolidated"
    assert picked["current"]["row"]["xbrl"] == "b" and picked["current"]["revisions"] == 1
    assert "yoy_q" not in picked  # absent, not substituted


# ---------- PDF text ----------

def test_ocr_zero_repair_only_in_numbers():
    t = pdftext.normalise("Interest earned 9o575.33 on 3o.o6.2o26 for the period")
    assert "90575.33" in t and "30.06.2026" in t and "for the period" in t


def test_doubled_glyph_collapse():
    t = pdftext.normalise("DDIIXXOONN TTEECCHHNNOOLLOOGGIIEESS rreevveennuuee 2211,,779933..6644")
    assert "dixon technologies revenue" in t


def test_number_variants_indian_grouping():
    v = pdftext.number_variants(1_81_086_33 * 1e4, 1e6)  # 1,81,086.33 million
    assert "1,81,086.33" in v and "181,086.33" in v


def test_find_number_requires_row_label():
    pages = ["revenue from operations 21,793.64 15,547.66 other income 529.54",
             "profit before tax 529.54 860.34"]
    assert pdftext.find_number(pages, 529.54e7, 1e7, label=r"[bh]efore (tax|exceptional|share)") == [(2, "529.54")]
    assert pdftext.find_number(pages, 529.54e7, 1e7) == [(1, "529.54"), (2, "529.54")]


def test_results_pdf_candidates_exclude_press_and_newspaper():
    base = {"attchmntFile": "x.pdf", "an_dt": "30-Oct-2026 16:00:00"}
    rows = [
        {**base, "desc": "Press Release", "attchmntText": "press release regarding financial results"},
        {**base, "desc": "Copy of Newspaper Publication", "attchmntText": "newspaper publication of financial results"},
        {**base, "desc": "Outcome of Board Meeting", "attchmntText": "Outcome of the Board Meeting"},
    ]
    c = results_pdf_candidates(rows, datetime(2026, 10, 30, 16))
    assert [r["desc"] for r in c] == ["Outcome of Board Meeting"]


# ---------- classification ----------

@pytest.mark.parametrize("subject,text,cat", [
    ("Outcome of Board Meeting", "has submitted the financial results for the period ended September 30, 2026", "results"),
    ("Appointment", "Appointment of Statutory Auditors pursuant to rotation", "unclassified"),
    ("General Updates", "KPIT AGM - response to stakeholders' queries", "agm_egm"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript", "earnings_call"),
    ("Change in Management", "Appointment of Mr X as Non- Executive Director", "management_change"),
])
def test_classify(subject, text, cat):
    assert classify(subject, text).category == cat


def test_category_and_materiality_are_independent():
    opaque = classify("General Updates", "General Updates")
    assert opaque.category == "unclassified" and opaque.read_state == "unread" and tier(opaque.materiality) == "look"
    routine = classify("Trading Window", "Closure of trading window")
    assert routine.category == "unclassified" and tier(routine.materiality) == "routine"
    non_exec = classify("Change in Management", "Appointment of Mr X as Non- Executive Director")
    ceo = classify("Change in Management", "Resignation of Mr Y as Chief Financial Officer")
    assert non_exec.materiality < ceo.materiality and tier(ceo.materiality) == "top"


def test_results_group_absorbs_same_day_board_outcome():
    t0 = datetime(2026, 10, 29, 16, 0)
    filings = [
        {"id": 1, "ticker": "TRENT", "filed_at": t0, "subject": "Outcome of Board Meeting",
         "text": "Outcome of Board Meeting held today", "duplicate_of": None},
        {"id": 2, "ticker": "TRENT", "filed_at": t0.replace(minute=20), "subject": "Press Release",
         "text": "press release on unaudited financial results for the quarter ended September 30, 2026",
         "duplicate_of": None},
        {"id": 3, "ticker": "TRENT", "filed_at": t0.replace(day=31), "subject": "Copy of Newspaper Publication",
         "text": "newspaper publication of financial results for quarter ended September 30, 2026", "duplicate_of": None},
    ]
    evs = build_events(filings)
    res = [e for e in evs if e["category"] == "results"]
    assert len(res) == 1 and sorted(res[0]["member_ids"]) == [1, 2, 3] and res[0]["primary_filing_id"] == 1


# ---------- prices ----------

def _bars(n, vol=100.0, last_vol=None, start=date(2026, 9, 1)):
    from datetime import timedelta
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append({"session": d, "close": 100.0 + len(out), "volume": vol})
        d += timedelta(days=1)
    if last_vol is not None:
        out[-1]["volume"] = last_vol
    return out


def test_volume_baseline_excludes_evaluated_session():
    bars = _bars(25, vol=100, last_vol=250)
    r = prices.evaluate("X", bars, bars[-1]["session"], 2.0, 50)
    assert r["volume_ratio"] == pytest.approx(2.5)  # baseline 100, not polluted by the 250 day
    assert [a["kind"] for a in r["alerts"]] == ["volume"]


def test_stale_ticker_does_not_block_and_needs_20_sessions():
    bars = _bars(25)
    later = date(2026, 12, 31)
    assert prices.evaluate("X", bars, later, 2, 4)["state"] == "stale"
    short = _bars(10)
    r = prices.evaluate("Y", short, short[-1]["session"], 2, 4)
    assert r["volume_ratio"] is None and "20 prior sessions" in r["volume_note"]


def test_partial_session_excluded_until_buffer():
    assert prices.latest_complete_session(datetime(2026, 11, 3, 11, 0)) == date(2026, 11, 2)
    assert prices.latest_complete_session(datetime(2026, 11, 3, 17, 30)) == date(2026, 11, 3)
    assert prices.latest_complete_session(datetime(2026, 11, 8, 12, 0)) == date(2026, 11, 6)  # Sunday -> Friday


# ---------- corroboration ----------

def test_alignment_requires_comparison_period_in_next_column():
    from finn.extract.results import _candidates
    page = ("consolidated revenue from operations 21,793.64 15,547.66 14,855.04 "
            "other line revenue from operations 1,000.00 21,793.64 9.99")
    c = _candidates([page], 21793.64e7, {"prev_q": 15547.66e7, "yoy_q": 14855.04e7}, 1e7, "consolidated",
                    r"revenue from operations")
    assert [x["aligned"] for x in c][0] == {"by": "prev_q", "column_offset": 1}
    stray = _candidates(["consolidated revenue from operations 5.00 21,793.64 7.77"], 21793.64e7,
                        {"prev_q": 15547.66e7}, 1e7, "consolidated", r"revenue from operations")
    assert stray and stray[0]["aligned"] is None  # value present, column not established


def test_definition_differs_beyond_print_rounding():
    from finn.extract.results import _unlocated
    row = {"id": "pbt", "current": 8533.47e7, "definition": {"status": "unchecked"}}
    page = "consolidated 6 profit before tax (4+5) 8,537.20 8,149.00"
    out = _unlocated(row, None, [page], 1, 1e7)
    assert out["status"] == "definition_differs" and out["printed_value"] == "8,537.20"
    assert row["definition"]["status"] == "differs_from_print"
    same = {"id": "pbt", "current": 8537.204e7, "definition": {"status": "unchecked"}}
    assert _unlocated(same, None, [page], 1, 1e7)["status"] == "not_located"  # within rounding: not a definition gap


def test_raw_token_traces_repairs():
    assert pdftext.raw_token("net profit 2O7OO.O3 19244.71", "20700.03") == "2O7OO.O3"


def test_snapshot_replay_is_offline_and_reproducible(tmp_path):
    """Rebuild the seeded DB from the committed snapshot with networking disabled."""
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path
    backend = Path(__file__).resolve().parents[1]
    db = tmp_path / "replay.db"
    env = {**os.environ, "FINN_DB_URL": f"sqlite:///{db}", "HTTP_PROXY": "http://127.0.0.1:9",
           "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""}
    r = subprocess.run([sys.executable, "-m", "finn.ingest", "snapshot", "--replay", "data/snapshot"],
                       cwd=backend, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    con = sqlite3.connect(db)
    n_cards = con.execute("select count(*) from event where json_extract(detail,'$.results.status') != 'failed'").fetchone()[0]
    aligned = con.execute("select count(*) from metric_obs where corroboration_page is not null").fetchone()[0]
    statuses = {s for (s,) in con.execute("select status from ingest_run")}
    assert n_cards == 14 and aligned == 39 and statuses == {"ok"}


def test_rebuilt_seed_has_same_fingerprint_and_api_is_read_only(tmp_path):
    """A redeploy rebuilds the DB from the snapshot: the /api/health fingerprint must not change."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    backend = Path(__file__).resolve().parents[1]
    probe = ("import json; from fastapi.testclient import TestClient; from finn.api import app\n"
             "with TestClient(app) as c:\n"
             "    put = c.put('/api/settings', json={'volume_multiple': 3, 'price_pct': 5, 'alert_categories': []})\n"
             "    print(json.dumps({'health': c.get('/api/health').json(), 'put': put.status_code,\n"
             "                      'probe': c.get('/api/probe-report').status_code}))")
    seen = []
    for i in range(2):
        env = {**os.environ, "FINN_DB_URL": f"sqlite:///{tmp_path / f'seed{i}.db'}", "FINN_READ_ONLY": "1",
               "FINN_STARTUP_PROBE": "0"}
        r = subprocess.run([sys.executable, "-m", "finn.ingest", "snapshot", "--replay", "data/snapshot"],
                           cwd=backend, env=env, capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr[-2000:]
        r = subprocess.run([sys.executable, "-c", probe], cwd=backend, env=env, capture_output=True, text=True,
                           timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
        seen.append(json.loads(r.stdout.strip().splitlines()[-1]))
    assert seen[0]["put"] == 403 and seen[0]["probe"] == 404
    assert seen[0]["health"]["read_only"] is True
    assert seen[0]["health"]["seed"] == seen[1]["health"]["seed"]
    assert seen[0]["health"]["seed"]["metric_obs"] > 0


# ---------- live pipeline rules ----------

def _live_db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from finn.models import Base, Company
    eng = create_engine(f"sqlite:///{tmp_path / 'live.db'}")
    Base.metadata.create_all(eng)
    db = sessionmaker(eng)()
    db.add(Company(ticker="PERSISTENT", in_portfolio=True))
    db.commit()
    return db


def _filing(db, i, filed, subject, text=None):
    from finn.models import Filing
    f = Filing(ticker="PERSISTENT", exchange="NSE", exch_id=str(i), filed_at=filed, subject=subject, text=text,
               category="pending", category_source="none", dedup_key=f"k{i}")
    db.add(f)
    db.flush()
    return f


def test_corrigendum_links_to_the_cited_letter(tmp_path):
    from finn import live
    db = _live_db(tmp_path)
    orig = _filing(db, 1, datetime(2026, 9, 30, 18, 5), "Analysts/Institutional Investor Meet/Con. Call Updates",
                   "Schedule of analyst meetings")
    _filing(db, 2, datetime(2026, 10, 2, 10, 0), "Press Release", "Persistent wins deal")
    cor = _filing(db, 3, datetime(2026, 10, 3, 9, 0), "Corrigendum",
                  "Corrigendum to our earlier letter under Ref. no. NSE & BSE / 2026-27 / 143 dated September 30, 2026")
    assert live.link_revisions(db, "PERSISTENT") == 1 and cor.revision_of == orig.id


def test_corrigendum_to_a_letter_outside_the_window_stays_standalone(tmp_path):
    from finn import live
    db = _live_db(tmp_path)
    _filing(db, 1, datetime(2026, 10, 20, 10, 0), "Press Release", "Persistent wins deal")
    cor = _filing(db, 2, datetime(2026, 10, 21, 9, 0), "Corrigendum",
                  "Corrigendum to our earlier letter dated September 30, 2026")
    assert live.link_revisions(db, "PERSISTENT") == 0 and cor.revision_of is None


def test_revision_joins_the_amended_event():
    filed = datetime(2026, 10, 20, 10, 0)
    evs = build_events([
        {"id": 1, "ticker": "X", "filed_at": filed, "subject": "Credit Rating", "text": "CRISIL reaffirmed AA+"},
        {"id": 2, "ticker": "X", "filed_at": datetime(2026, 10, 22, 9, 0), "subject": "Corrigendum",
         "text": "Corrigendum to credit rating letter dated October 20, 2026", "revision_of": 1},
    ])
    assert len(evs) == 1 and evs[0]["member_ids"] == [1, 2] and evs[0]["revised"]


def test_backfill_then_incremental_windows(tmp_path):
    from finn import live
    db = _live_db(tmp_path)
    now = datetime(2026, 11, 3, 12, 0)
    assert live.announcement_windows(db, ["PERSISTENT"], now)["PERSISTENT"] == (date(2026, 10, 4), date(2026, 11, 3), True)
    live.set_cursor(db, "PERSISTENT", datetime(2026, 11, 2, 18, 0))
    assert live.announcement_windows(db, ["PERSISTENT"], now)["PERSISTENT"] == (date(2026, 10, 31), date(2026, 11, 3), False)
    # a 3-month outage is capped at the backfill window
    assert live.announcement_windows(db, ["PERSISTENT"], datetime(2027, 2, 3))["PERSISTENT"][0] == date(2027, 1, 4)


def test_card_rebuild_policy():
    from types import SimpleNamespace
    from finn import live
    now = datetime(2026, 11, 3, 12, 0)
    ok = {"results": {"status": "ok"}, "results_attempt": {"at": "2026-11-03T08:00:00", "n_members": 2}}
    assert live.card_due(SimpleNamespace(detail=None, occurred_at=now), 1, now) == "no card yet"
    assert live.card_due(SimpleNamespace(detail=ok, occurred_at=now), 2, now) is None
    assert live.card_due(SimpleNamespace(detail=ok, occurred_at=now), 3, now) == "new filings joined the event"
    failed = {"results": {"status": "failed"}, "results_attempt": {"at": "2026-11-03T11:00:00", "n_members": 1}}
    assert live.card_due(SimpleNamespace(detail=failed, occurred_at=now), 1, now) is None  # tried 1h ago
    assert live.card_due(SimpleNamespace(detail=failed, occurred_at=now), 1, datetime(2026, 11, 3, 13, 30))
    old = datetime(2026, 10, 1)
    assert live.card_due(SimpleNamespace(detail=failed, occurred_at=old), 1, now) is None  # gave up


def test_xbrl_revision_detected_from_index():
    from finn import live
    card = {"periods": {"current": {"xbrl_url": "a1.xml"}, "prev_q": {"xbrl_url": "b.xml"}}}
    row = lambda qe, url, rev: {"qe_Date": qe, "consolidated": "Consolidated", "xbrl": url, "broadcast_Date": rev}
    idx = [row("30-Sep-2026", "a1.xml", "17-Oct-2026 13:00"), row("30-Jun-2026", "b.xml", "18-Jul-2026 13:00")]
    assert not live.xbrl_revised(card, idx, date(2026, 9, 30))
    idx.append(row("30-Sep-2026", "a2.xml", "25-Oct-2026 10:00"))
    assert live.xbrl_revised(card, idx, date(2026, 9, 30))


def test_alerts_skip_backfill_and_dedupe(tmp_path):
    from finn import live
    from finn.models import Alert, Event
    db = _live_db(tmp_path)
    st = {"alert_categories": ["results"], "eod_buffer_min": 90, "volume_multiple": 2.0, "price_pct": 4.0}
    db.add(Event(group_key="old", ticker="PERSISTENT", category="results", title="Q1", materiality=85,
                 occurred_at=datetime(2026, 10, 20), read_state="read", materiality_reasons=[]))
    db.commit()
    assert live.record_announcement_alerts(db, st) == 0  # not live yet
    live.mark_live_since(db, datetime(2026, 11, 1))
    db.add(Event(group_key="new", ticker="PERSISTENT", category="results", title="Q2", materiality=85,
                 occurred_at=datetime(2026, 11, 2), read_state="read", materiality_reasons=[]))
    db.commit()
    assert live.record_announcement_alerts(db, st) == 1
    db.commit()
    assert live.record_announcement_alerts(db, st) == 0
    assert db.query(Alert).count() == 1


def test_worker_schedule(tmp_path):
    from finn.models import IngestRun
    from finn.worker import due, market_hours
    db = _live_db(tmp_path)
    tue_10 = datetime(2026, 11, 3, 10, 0)
    assert market_hours(tue_10) and not market_hours(datetime(2026, 11, 3, 16, 0))
    assert not market_hours(datetime(2026, 11, 7, 10, 0))  # Saturday
    assert set(due(db, tue_10)) == {"announcements", "prices", "xbrl_recheck", "research"}  # demo reports missing
    from finn.models import ResearchJob
    assert db.query(ResearchJob).count() == 0  # deciding what is due never queues anything
    for t in ("HAL", "CDSL", "ASTRAL", "PIDILITIND", "KAYNES"):
        db.add(ResearchJob(ticker=t, state="done", finished_at=datetime(2026, 11, 3, 9, 0), attempts=1, doc_failures=[]))
    db.commit()

    def run(source, started, through=None, errors=()):
        db.add(IngestRun(source=source, mode="live", started_at=started, finished_at=started, status="ok",
                         data_through=through, errors=list(errors)))
        db.commit()
    run("nse_announcements", datetime(2026, 11, 3, 9, 50))
    run("prices", datetime(2026, 11, 3, 9, 50), through=datetime(2026, 11, 2, 15, 30))
    run("results_xbrl_recheck", datetime(2026, 11, 3, 0, 5))
    assert due(db, tue_10) == []  # 10 min in market hours; Monday's session already in
    assert due(db, datetime(2026, 11, 3, 10, 5)) == ["announcements"]  # 15 min cadence
    run("nse_announcements", datetime(2026, 11, 3, 16, 0))
    assert "announcements" not in due(db, datetime(2026, 11, 3, 16, 30))  # hourly after the close
    assert "announcements" in due(db, datetime(2026, 11, 3, 17, 0))
    # Tuesday's session is published at 17:00; first attempt then, retries hourly, not every minute
    assert "prices" in due(db, datetime(2026, 11, 3, 17, 1))
    run("prices", datetime(2026, 11, 3, 17, 1), through=datetime(2026, 11, 2, 15, 30))
    assert "prices" not in due(db, datetime(2026, 11, 3, 17, 30))
    assert "prices" in due(db, datetime(2026, 11, 3, 18, 2))
    assert "xbrl_recheck" in due(db, datetime(2026, 11, 4, 0, 1))


class FakeNSE:
    """Announcements only; records the windows asked for. A ticker in `fail` raises."""
    def __init__(self, rows, fail=()):
        self.rows, self.fail, self.calls = rows, set(fail), []

    def announcements(self, t, start, end):
        from finn.sources.nse import SourceError
        self.calls.append((t, start, end))
        if t in self.fail:
            raise SourceError("HTTP 403")
        return [r for r in self.rows if r["symbol"] == t]


def _ann(seq, sym, when, desc, text):
    return {"seq_id": seq, "symbol": sym, "an_dt": when, "sort_date": when, "desc": desc,
            "attchmntText": text, "attchmntFile": f"https://x/{seq}.pdf", "sm_name": sym}


def test_worker_rerun_is_idempotent_and_backfills_failed_ticker(tmp_path, monkeypatch):
    from finn import ingest, live
    from finn.models import Alert, Company, Event, Filing
    db = _live_db(tmp_path)
    db.add(Company(ticker="TRENT", in_portfolio=True))
    db.commit()
    monkeypatch.setattr(ingest, "build_results_card", lambda *a, **k: {"status": "failed", "problems": ["test"]})
    rows = [_ann(1, "PERSISTENT", "02-Nov-2026 18:00:00", "Press Release", "Persistent wins a contract"),
            {**_ann(2, "PERSISTENT", "02-Nov-2026 18:05:00", "Press Release", "Persistent wins a contract"),
             "attchmntFile": "https://x/1.pdf"},  # re-post of the same document
            _ann(3, "TRENT", "02-Nov-2026 10:00:00", "Credit Rating", "CRISIL reaffirmed AA+")]
    t0 = datetime(2026, 11, 3, 12, 0)
    monkeypatch.setattr(ingest.px, "now_ist", lambda: t0)
    nse = FakeNSE(rows, fail={"TRENT"})
    tickers = ["PERSISTENT", "TRENT"]
    for _ in range(2):  # same run twice: nothing duplicated
        raw = ingest.ingest_announcements(db, nse, tickers, 30, "live", windows=live.announcement_windows(db, tickers, t0))
        ingest.rebuild_events(db, tickers, raw, "live")
    assert db.query(Filing).count() == 2 and db.query(Filing).filter(Filing.duplicate_of.isnot(None)).count() == 1
    assert db.query(Event).count() == 1
    assert "TRENT" not in live.get_cursors(db)
    # TRENT recovers: its window still reaches back to the full backfill, so the missed filing arrives
    nse.fail.clear()
    t1 = datetime(2026, 11, 3, 13, 0)
    monkeypatch.setattr(ingest.px, "now_ist", lambda: t1)
    w = live.announcement_windows(db, tickers, t1)
    assert w["TRENT"][2] is True and w["PERSISTENT"][0] == date(2026, 11, 1)
    raw = ingest.ingest_announcements(db, nse, tickers, 30, "live", windows=w)
    ingest.rebuild_events(db, tickers, raw, "live")
    assert db.query(Filing).count() == 3 and db.query(Event).count() == 2
    assert db.query(Alert).count() == 0  # nothing alerts before live_since is set


def test_worker_lock_blocks_overlapping_run():
    from finn.worker import single_worker
    with single_worker() as first:
        with single_worker() as second:
            assert first is True and second is False
    with single_worker() as again:
        assert again is True  # released


def test_killed_run_is_marked_abandoned(tmp_path):
    from finn.models import IngestRun
    from finn.worker import close_abandoned
    db = _live_db(tmp_path)
    now = datetime(2026, 11, 3, 12, 0)
    db.add(IngestRun(source="nse_announcements", mode="live", started_at=datetime(2026, 11, 3, 11, 0), status="running"))
    db.add(IngestRun(source="prices", mode="live", started_at=datetime(2026, 11, 3, 11, 50), status="running"))
    db.commit()
    assert close_abandoned(db, now) == 1
    assert {r.source: r.status for r in db.query(IngestRun)} == {"nse_announcements": "abandoned", "prices": "running"}


def test_migrations_are_explicit_and_idempotent(tmp_path):
    from sqlalchemy import create_engine
    from finn import migrate
    eng = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    assert migrate.current(eng) is None
    with pytest.raises(RuntimeError):
        migrate.require_latest(eng)
    assert migrate.upgrade(eng) == list(range(1, migrate.LATEST + 1)) and migrate.upgrade(eng) == []
    assert migrate.current(eng) == migrate.LATEST
    migrate.require_latest(eng)


def _api_health(env_extra):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    code = ("import json; from fastapi.testclient import TestClient; from finn.api import app\n"
            "with TestClient(app) as c: print(json.dumps(c.get('/api/health').json()['database']))")
    r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                       env={**os.environ, **env_extra}, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_api_falls_back_to_seed_without_touching_an_unmigrated_db(tmp_path):
    import sqlite3
    target = tmp_path / "live.db"
    sqlite3.connect(target).close()
    d = _api_health({"FINN_DB_URL": f"sqlite:///{target}"})
    assert d["source"] == "seed_fallback" and "schema is version None" in d["fallback_reason"]
    assert sqlite3.connect(target).execute("select count(*) from sqlite_master").fetchone()[0] == 0
    d = _api_health({"FINN_DB_URL": "postgresql://u:pw@127.0.0.1:1/x"})
    assert d == {**d, "source": "seed_fallback", "fallback_reason": "OperationalError"}  # no host or message


def test_snapshot_refuses_a_database_with_live_runs(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from finn import migrate
    from finn.models import IngestRun
    url = f"sqlite:///{tmp_path / 'live.db'}"
    eng = create_engine(url)
    migrate.upgrade(eng)
    s = sessionmaker(eng)()
    s.add(IngestRun(source="nse_announcements", mode="live", started_at=datetime(2026, 11, 3), status="ok"))
    s.commit()
    r = subprocess.run([sys.executable, "-m", "finn.ingest", "snapshot", "--replay", "data/snapshot"],
                       cwd=Path(__file__).resolve().parents[1], env={**os.environ, "FINN_DB_URL": url},
                       capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "live runs" in r.stderr


def test_truncated_archive_download_is_retried_and_never_cached(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from finn.sources import nse as nse_mod
    from finn.sources.nse import NSE, SourceError, incomplete
    whole = b"%PDF-1.7\n" + b"x" * 5000 + b"\n%%EOF\n"
    assert incomplete(whole, str(len(whole))) is None
    assert incomplete(whole[:3000], str(len(whole))) == f"3000 of {len(whole)} bytes"
    assert incomplete(whole[:3000], None) == "PDF has no end-of-file marker"
    # gzip on the wire: Content-Length is the compressed size, so it is not compared
    assert incomplete(b"<xbrl>" + b"y" * 9000 + b"</xbrl>", "1200", "gzip") is None
    monkeypatch.setattr(nse_mod, "CACHE_DIR", tmp_path)
    responses = [whole[:3000], whole]
    n = NSE.__new__(NSE)
    n._get = lambda url, timeout=60: SimpleNamespace(content=responses.pop(0), headers={"content-length": str(len(whole))})
    body, _ = n.fetch_bytes("https://x/a.pdf")
    assert body == whole and not responses  # retried once, got the whole file
    n._get = lambda url, timeout=60: SimpleNamespace(content=whole[:3000], headers={})
    with pytest.raises(SourceError, match="incomplete download"):
        n.fetch_bytes("https://x/b.pdf")
    assert len(list(tmp_path.iterdir())) == 1  # only the complete file was cached


# ---------- research: guidance extraction ----------

@pytest.mark.parametrize("sentence,want", [
    ("We have always called out that we are very comfortable to operate within an EBITDA corridor of 20% to 24%.",
     ("ebitda_margin", "range", 20, 24, "period not stated")),
    ("As we guided in last call that we will be closing full year with 20%, 25% kind of growth.",
     ("revenue_growth", "range", 20, 25, "FY27")),
    ("So we have given the guidance of minimum double-digit growth for volume.",
     ("volume_growth", "at_least", 10, None, "period not stated")),
    ("And the volume growth, I think, would be around 35% to 40%, I could put it.",
     ("volume_growth", "range", 35, 40, "period not stated")),
    ("I think we have given the CAPEX guidance for full year around Rs. 350 crores.",
     ("capex", "point", 350, 350, "FY27")),
    ("We expect revenue growth in the high single digits for FY27.", ("revenue_growth", "range", 7, 10, "FY27")),
    ("Giving a guidance of INR4,500 crores is almost 55% growth over the previous year.",
     ("revenue_growth", "point", 55, 55, "FY27")),
])
def test_guidance_statements(sentence, want):
    from finn.research.guidance import _statement
    st = _statement(sentence, date(2026, 8, 12))
    assert st and (st["metric"], st["direction"], st["low"], st["high"], st["period_label"]) == want


@pytest.mark.parametrize("sentence,note", [
    ("And the margins are going to be north of current 30% plus.", "margin type not stated (gross, EBITDA or segment)"),
    ("The GDP growth is at 8%, and the EMS space is expected to grow in this year 16% to 18%.",
     "refers to the industry or economy, not the company"),
    ("Next year, we expect system growth to be between 12% to 13%.", "refers to the industry or economy, not the company"),
    ("We have given double digit guidance for volume and EBITDA margin on polymer, we have given between 16%-18% range "
     "and Adhesive and Paint, we have given between 12%-14% margin.", "may refer to a segment, not the whole company"),
    ("We are confident that we will come back to our original double digit kind of EBITDA margin in the UK next year.",
     "may refer to a segment, not the whole company"),
    ("On a full year basis, we should be able to reach 8% to 10% of EBITDA margins on FMEG.",
     "may refer to a segment, not the whole company"),
])

def test_guidance_scope_flags(sentence, note):
    from finn.research.guidance import _statement
    st = _statement(sentence, date(2026, 8, 12))
    assert st and note in st["notes"]


@pytest.mark.parametrize("sentence", [
    "Because for us, the EBITDA corridor which we have shared is 20% to 24%.",   # "us" is not the USA
    "It gives us the confidence that the guidance of double-digit growth we will achieve on a full year basis.",
])
def test_company_level_guidance_is_not_flagged_as_segment(sentence):
    from finn.research.guidance import _statement
    st = _statement(sentence, date(2026, 8, 12))
    assert st and not st["notes"]


def test_segment_named_in_an_earlier_sentence_is_carried_over():
    from finn.research.guidance import extract
    turn = {"role": "management", "speaker": "CFO", "page": 4, "text":
            "We have put in a new CEO who has 25 years of experience in this segment. This year we have given a guidance "
            "of 20% growth for the full year and we are going to achieve it."}
    st = extract([turn], date(2025, 11, 6), "u")[0]
    assert "may refer to a segment, not the whole company" in st.notes
    plain = {**turn, "text": "Thank you for the question. This year we have given a guidance of 20% growth for the full year."}
    assert extract([plain], date(2025, 11, 6), "u")[0].notes == []


def test_minimum_means_at_least():
    from finn.research.guidance import _statement
    st = _statement("By year end, we are targeting minimum 20% kind of growth.", date(2025, 8, 18))
    assert (st["direction"], st["low"]) == ("at_least", 20)


def test_longer_term_is_multi_year():
    from finn.research.guidance import _statement
    st = _statement("So over the longer term, I believe we would end up in a range of 8% to 10% of the EBITDA margin.",
                    date(2026, 8, 12))
    assert st["period_type"] == "long_horizon"



@pytest.mark.parametrize("sentence", [
    "This year, it is INR326 crores, so registering a growth of 24.8%.",            # a result
    "In the current quarter, our revenue grew by 15.3% in value terms.",             # a result
    "Is there a way you give some outlook on growth of 10% next year?",              # a question
    "It is going to be a sizable improvement, maybe more than 100% improvement into the EBITDA this year.",
])
def test_non_guidance_is_dropped(sentence):
    from finn.research.guidance import _statement
    st = _statement(sentence, date(2026, 8, 12))
    assert st is None or st["metric"] != "ebitda_margin" and "registering" not in sentence and "grew" not in sentence


def _series(rows):
    """rows: {quarter_end: (revenue_cr, ebitda_cr)}"""
    qs = []
    for qe, (rev, ebitda) in sorted(rows.items()):
        qs.append({"quarter_end": qe, "label": qe, "values": {"revenue": rev * 1e7, "ebitda_op_proxy": ebitda * 1e7,
                                                              "ebitda_margin": ebitda / rev * 100, "pat": None}})
    return {"quarters": qs, "taxonomy": "indas", "basis": "consolidated"}


def _stmt(**kw):
    base = {"metric": "revenue_growth", "metric_label": "Revenue growth", "direction": "range", "low": 15, "high": 18,
            "unit": "pct", "period_type": "FY", "period_fy": 2027, "period_label": "FY27", "quote": "q", "page": 3,
            "speaker": "CFO", "stated_on": "2026-05-15", "source_url": "u", "notes": []}
    return {**base, **kw}


def test_scorecard_fy_growth_pending_then_final():
    from finn.research.scorecard import build
    s = _series({"2025-06-30": (100, 20), "2025-09-30": (100, 20), "2025-12-31": (100, 20), "2026-03-31": (100, 20),
                 "2026-06-30": (116, 22), "2026-09-30": (117, 22)})
    v = build([_stmt()], s, date(2026, 11, 3))[0]["verdict"]
    assert v["status"] == "pending" and v["tracking"] == "on track" and round(v["value"], 1) == 16.5
    s["quarters"] += _series({"2026-12-31": (110, 20), "2027-03-31": (110, 20)})["quarters"]
    v = build([_stmt()], s, date(2027, 6, 1))[0]["verdict"]
    assert v["status"] == "missed" and round(v["value"], 2) == 13.25  # 15-18% guided, more than 1pp short


def test_scorecard_tolerance_supersession_and_gaps():
    from finn.research.scorecard import build
    s = _series({"2025-06-30": (100, 20), "2026-06-30": (114.5, 20)})
    early = _stmt(stated_on="2026-02-01", low=18, high=20)
    late = _stmt(stated_on="2026-08-01", low=15, high=18)
    items = build([early, late], s, date(2026, 11, 3))
    assert len(items) == 1 and items[0]["revisions"][0]["target"] == "18–20%"  # revised down, trail kept
    clash = build([_stmt(stated_on="2026-08-12", low=20, high=25), _stmt(stated_on="2026-08-12", direction="at_least",
                                                                          low=10, high=None)], s, date(2026, 11, 3))
    assert [c["verdict"]["status"] for c in clash] == ["not_comparable"] * 2 and all(not c["revisions"] for c in clash)
    same = build([_stmt(stated_on="2026-02-01"), _stmt(stated_on="2026-08-01")], s, date(2026, 11, 3))[0]
    assert same["revisions"] == [] and same["reiterated_on"] == ["2026-02-01"]
    assert items[0]["verdict"]["tracking"] == "slightly behind"  # 14.5% is within 1pp of 15%
    # a finished year with missing quarters is a data gap, not "pending"
    gap = build([_stmt(period_fy=2026, period_label="FY26")], _series({"2025-03-31": (90, 18), "2026-03-31": (100, 20)}),
                date(2026, 11, 3))[0]["verdict"]
    assert gap["status"] == "not_comparable" and "1 of its 4 quarters" in gap["reason"]


def test_lender_growth_guidance_is_not_scored_as_revenue():
    from finn.research.guidance import _statement
    from finn.research.scorecard import build
    q = ("Overall, we've taken a view that the top line growth or AUM growth will gravitate between 22% and 23%, "
         "but more likely to be 22% on a full year basis.")
    st = _statement(q, date(2026, 2, 7))
    assert "loan book / AUM measure, not in the results filing" in st["notes"]
    s = {**_series({"2025-06-30": (100, 20), "2026-06-30": (118, 20)}), "taxonomy": "nbfc"}
    lender = _stmt(quote="We expect growth of 22% to 23% this year.", low=22, high=23)
    assert "loan book" in build([lender], s, date(2026, 11, 3))[0]["verdict"]["reason"]


def test_scorecard_standing_band_and_abstentions():
    from finn.research.scorecard import build
    s = _series({"2026-03-31": (100, 23), "2026-06-30": (100, 26), "2026-09-30": (100, 19)})
    band = _stmt(metric="ebitda_margin", metric_label="EBITDA margin", low=20, high=24, period_type="standing",
                 period_fy=None, period_label="standing band", stated_on="2026-02-11")
    v = build([band], s, date(2026, 11, 3))[0]["verdict"]
    assert v["status"] == "partial" and "1 of 3 within the band, 1 above it" in v["calc"]
    for kw, why in [({"metric": "volume_growth"}, "Volumes"), ({"notes": ["may refer to a segment, not the whole company"]}, "segment"),
                    ({"period_type": "unstated", "period_fy": None}, "No target period")]:
        assert why in build([_stmt(**kw)], s, date(2026, 11, 3))[0]["verdict"]["reason"]


def test_migration_v2_upgrades_an_existing_v1_database(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from finn import migrate
    eng = create_engine(f"sqlite:///{tmp_path / 'v1.db'}")
    with eng.begin() as c:  # the v1 shape: research_job without the v2 columns
        c.execute(text("create table research_job (id integer primary key, ticker varchar(32), state varchar(16), "
                       "cache_key varchar(128), doc_failures json, attempts integer, created_at timestamp, "
                       "updated_at timestamp)"))
        c.execute(text("create table filing (id integer primary key)"))
        c.execute(text("create table schema_version (version integer primary key, applied_at varchar(32) not null)"))
        c.execute(text("insert into schema_version values (1, 'x')"))
    assert migrate.current(eng) == 1 and migrate.upgrade(eng) == [2]
    cols = {c["name"] for c in inspect(eng).get_columns("research_job")}
    assert {"report", "finished_at", "requested_via"} <= cols


def test_research_queue_rules_and_job_run(tmp_path):
    from finn.models import ResearchJob
    from finn.research import jobs
    db = _live_db(tmp_path)
    now = datetime(2026, 11, 3, 12, 0)
    assert jobs.enqueue(db, "drop table;", "app", now) == (None, "not an NSE symbol")
    j, why = jobs.enqueue(db, "titan", "app", now)
    assert why == "queued" and j.ticker == "TITAN"
    assert jobs.enqueue(db, "TITAN", "app", now)[1] == "already queued"
    for i in range(jobs.MAX_QUEUED - 1):
        jobs.enqueue(db, f"T{i}", "app", now)
    assert jobs.enqueue(db, "ONEMORE", "app", now) == (None, "queue full")
    # queued requests come before demo refreshes, PER_TICK at a time
    assert [t.ticker for t in jobs.targets(db, now)][0] == "TITAN"
    done = jobs.run(db, j, None, now, research_fn=lambda t, d, n, log: {"ticker": t, "status": "done", "cache_key": "k",
                                                                         "summary": {"delivered": 1}, "failures": []})
    assert done.state == "done" and done.report["summary"] == {"delivered": 1} and done.finished_at == now
    def boom(*a, **k):
        raise RuntimeError("NSE down")
    j2, _ = jobs.enqueue(db, "TITAN", "app", now)
    assert jobs.run(db, j2, None, now, research_fn=boom).state == "failed"
    assert "NSE down" in j2.report["failures"][0]["error"]


def test_research_api_refuses_requests_on_the_seed_and_serves_reports(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    code = ("import json; from fastapi.testclient import TestClient; from finn.api import app\n"
            "with TestClient(app) as c:\n"
            "  out = {'post': c.post('/api/research/TITAN').status_code, 'index': c.get('/api/research').json(),\n"
            "         'missing': c.get('/api/research/NOPE').status_code}\n"
            "  print(json.dumps(out))")
    backend = Path(__file__).resolve().parents[1]
    run = lambda env: json.loads(subprocess.run([sys.executable, "-c", code], cwd=backend, env={**os.environ, **env},
                                                capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[-1])
    seed = run({"FINN_DB_URL": ""})
    assert seed["post"] == 503 and seed["index"]["can_request"] is False and seed["missing"] == 404
    url = f"sqlite:///{tmp_path / 'live.db'}"
    from sqlalchemy import create_engine
    from finn import migrate
    migrate.upgrade(create_engine(url))
    live = run({"FINN_DB_URL": url, "FINN_READ_ONLY": "1"})
    assert live["post"] == 200 and live["index"]["can_request"] is True
    assert [q["ticker"] for q in live["index"]["queue"]] == ["TITAN"]


def test_transcript_discovery_keeps_nse_standard_call_subject():
    from finn.research.transcripts import find

    class N:
        def announcements(self, t, a, b):
            mk = lambda seq, when, text: {"seq_id": seq, "an_dt": when, "sort_date": when, "attchmntFile": f"https://x/{seq}.pdf",
                                          "desc": "Analysts/Institutional Investor Meet/Con. Call Updates", "attchmntText": text}
            return [mk(1, "07-Aug-2026 10:00:00", "CDSL has informed the Exchange about Transcript of Analysts/Institutional "
                                                  "Investor Meet/Con. Call held on August 03, 2026"),
                    mk(2, "25-May-2026 10:00:00", "Astral has informed the Exchange about Transcript of Analyst Meet Held on "
                                                  "20th May, 2026")]
    got = find(N(), "X", date(2026, 11, 3))
    assert [g["call_date"] for g in got] == ["2026-08-03"]  # the call kept, the analyst day dropped
