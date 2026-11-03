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
    _filing(db, 1, datetime(2026, 11, 2, 18, 0), "Press Release")
    assert live.announcement_windows(db, ["PERSISTENT"], now)["PERSISTENT"] == (date(2026, 10, 31), date(2026, 11, 3), False)


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
    assert set(due(db, tue_10)) == {"announcements", "prices", "xbrl_recheck"}

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
