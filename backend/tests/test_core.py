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
    ("General Updates", "KPIT AGM - response to stakeholders' queries", "unclassified"),
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
