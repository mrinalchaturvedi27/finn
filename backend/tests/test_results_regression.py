"""Regression against manually confirmed filings (probe/results_confirmed.json). Needs network.

    FINN_NETWORK_TESTS=1 pytest tests/test_results_regression.py
"""
import json
import os
from datetime import date
from pathlib import Path

import pytest

FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "probe" / "results_confirmed.json").read_text())

pytestmark = pytest.mark.skipif(not os.environ.get("FINN_NETWORK_TESTS"), reason="network test")


@pytest.mark.parametrize("f", FIXTURE["filings"], ids=lambda f: f["ticker"])
def test_confirmed_filing(f):
    from finn.extract.results import build_results_card
    from finn.sources.nse import NSE

    nse = NSE()
    qe = date(2026, 9, 30)
    ann = nse.announcements(f["ticker"], qe, date(2026, 11, 3))
    name = next((a["sm_name"] for a in ann if a.get("sm_name")), None)
    card = build_results_card(nse, f["ticker"], name, qe, ann)
    assert card["taxonomy"] == f["taxonomy"]
    assert card["pdf"]["url"] == f["pdf"] and not card["pdf"].get("rejected")
    assert card["statement_page"] == f["statement_page"]
    rows = {m["id"]: m for m in card["metrics"]}
    for mid, (_label, printed) in f["rows"].items():
        assert rows[mid]["pdf_page"] == f["statement_page"], mid
        assert rows[mid]["pdf_match"] == printed, mid
        assert rows[mid]["corroboration"]["aligned"]["by"] == f["aligned_by"], mid
    for mid, want in f.get("known_mismatch", {}).items():
        r = rows[mid]
        assert r["pdf_page"] is None, f"{mid} should stay uncorroborated"
        assert r["corroboration"]["status"] == want["status"]
        assert r["corroboration"]["printed_value"] == want["printed_value"]
        assert r["definition"] == {**r["definition"], "status": "differs_from_print", "xbrl_concept": want["xbrl_concept"]}
