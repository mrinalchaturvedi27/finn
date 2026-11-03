"""Quarterly results card: XBRL values (primary) + page-level PDF corroboration.

Pipeline:
  1. results index -> pick filing for quarter Q, Q-1, Q-4 on one basis (latest revision wins)
  2. parse each XBRL; validate symbol/company, basis, and that a 3-month context exists
  3. compute metric set for the company's reporting format; QoQ / YoY with n/m states
  4. find the board-outcome PDF (subject only nominates candidates), confirm inside it:
     company, period end, basis, results-table header; then locate each number on a page
"""
import re
from datetime import date, datetime, timedelta

from .. import metrics
from ..sources.nse import NSE, SourceError, parse_nse_dt
from . import pdftext, xbrl

SCALE = {"crores": 1e7, "lakhs": 1e5, "lakh": 1e5, "millions": 1e6, "million": 1e6,
         "thousands": 1e3, "rupees": 1.0}

CANDIDATE_SUBJECTS = {"outcome of board meeting", "financial result updates", "financial results"}
RESULT_TEXT = re.compile(r"financial results?", re.I)
NOT_RESULTS = re.compile(r"newspaper|intimation|prior|schedule of|conference call|recording|transcript|"
                         r"media|press meet|auditors?'? report|to consider", re.I)


# ---------- period arithmetic ----------

def quarter_start(qe: date) -> date:
    m = qe.month - 2
    y = qe.year
    if m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def prev_quarter_end(qe: date) -> date:
    return quarter_start(qe) - timedelta(days=1)


def yoy_quarter_end(qe: date) -> date:
    return date(qe.year - 1, qe.month, qe.day)


def fiscal_label(qe: date, fy_end_month: int = 3) -> str:
    fy = qe.year + (1 if qe.month > fy_end_month else 0)
    q = ((qe.month - fy_end_month - 1) % 12) // 3 + 1
    return f"Q{q} FY{str(fy)[-2:]}"


# ---------- filing selection ----------

def pick_filings(index: list[dict], qe: date, prefer=("Consolidated", "Standalone")):
    """For quarter-end qe pick one basis available for Q, Q-1 and Q-4; latest revision per period."""
    targets = {"current": qe, "prev_q": prev_quarter_end(qe), "yoy_q": yoy_quarter_end(qe)}

    def rows_for(d, basis):
        rs = [r for r in index if parse_nse_dt(r.get("qe_Date")) and parse_nse_dt(r["qe_Date"]).date() == d
              and r.get("consolidated") == basis]
        rs.sort(key=lambda r: parse_nse_dt(r.get("revised_Date") or r.get("broadcast_Date")
                                           or r.get("creation_Date")) or datetime.min)
        return rs

    for basis in prefer:
        if not rows_for(qe, basis):
            continue
        picked = {}
        for k, d in targets.items():
            rs = rows_for(d, basis)
            if rs:
                picked[k] = {"row": rs[-1], "revisions": len(rs) - 1}
        return basis, picked
    return None, {}


# ---------- validation ----------

def validate(doc: xbrl.XbrlDoc, ticker: str, company_name: str | None, basis: str, qe: date) -> list[dict]:
    checks = []
    sym = (doc.meta.get("symbol") or "").upper()
    name_ok = bool(company_name and doc.meta.get("company")
                   and _name_key(company_name) == _name_key(doc.meta["company"]))
    checks.append({"check": "company", "ok": sym == ticker.upper() or name_ok,
                   "detail": f"filing symbol={sym or '?'}"})
    nature = (doc.meta.get("nature") or "").lower()
    want = "consolidated" if basis == "Consolidated" else "standalone"
    checks.append({"check": "basis", "ok": nature.startswith(want), "detail": f"filing says {nature or '?'}"})
    ctx = doc.duration_ctx(quarter_start(qe), qe)
    checks.append({"check": "period", "ok": ctx is not None,
                   "detail": f"3-month context {quarter_start(qe)}..{qe} {'found' if ctx else 'missing'}"})
    return checks


def _name_key(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower().replace("limited", "").replace("ltd", ""))


# ---------- PDF corroboration ----------

def date_patterns(d: date) -> list[str]:
    mon, mo3 = d.strftime("%B").lower(), d.strftime("%b").lower()
    day = d.day
    sfx = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return [rf"{day}(?:{sfx})?\s*{mon},?\s*{d.year}", rf"{mon}\s*{day}(?:{sfx})?,?\s*{d.year}",
            rf"{day:02d}[./-]{d.month:02d}[./-]{d.year}", rf"{day}[./-]{d.month}[./-]{d.year}",
            rf"{mo3}\.?\s*{day},?\s*{d.year}", rf"{day}[- ]{mo3}[- ,]*{d.year}",
            rf"{day:02d}[./-]{d.month:02d}[./-]{str(d.year)[-2:]}\b"]


def results_pdf_candidates(announcements: list[dict], around: datetime | None) -> list[dict]:
    out = []
    for a in announcements:
        subj, txt = (a.get("desc") or "").lower(), a.get("attchmntText") or ""
        if not (a.get("attchmntFile") or "").lower().endswith(".pdf"):
            continue
        if subj not in CANDIDATE_SUBJECTS and not RESULT_TEXT.search(txt):
            continue
        if "press release" in subj:
            continue  # a press release discusses results; it is not the results statement
        if NOT_RESULTS.search(subj) or (subj not in CANDIDATE_SUBJECTS and NOT_RESULTS.search(txt)):
            continue
        dt = parse_nse_dt(a.get("an_dt"))
        if around and dt and abs((dt - around).total_seconds()) > 3 * 86400:
            continue
        score = (2 if subj == "outcome of board meeting" else 1) + (1 if RESULT_TEXT.search(txt) else 0)
        out.append({**a, "_score": score, "_dt": dt})
    out.sort(key=lambda a: (-a["_score"], abs((a["_dt"] - around).total_seconds()) if around and a["_dt"] else 0))
    return out


def confirm_pdf(page_texts: list[str], company: str, qe: date, basis: str) -> list[dict]:
    full = " ".join(page_texts)
    name_tokens = [t for t in re.findall(r"[a-z]{4,}", company.lower()) if t not in ("limited", "india")][:2]
    return [
        {"check": "company", "ok": all(t in full for t in name_tokens), "detail": f"tokens {name_tokens}"},
        {"check": "period_end", "ok": any(re.search(p, full) for p in date_patterns(qe)), "detail": str(qe)},
        {"check": "basis", "ok": basis.lower() in full, "detail": basis.lower()},
        {"check": "table_header", "ok": bool(re.search(r"quarter\s+ended|three\s+months\s+ended|quarter\s+ending", full)),
         "detail": "quarter/three months ended"},
    ]


# ---------- main entry ----------

def build_results_card(nse: NSE, ticker: str, company_name: str | None, qe: date,
                       announcements: list[dict] | None = None, fy_end_month: int = 3) -> dict:
    card = {"ticker": ticker, "quarter_end": qe.isoformat(), "label": fiscal_label(qe, fy_end_month),
            "status": "ok", "problems": [], "periods": {}, "metrics": [], "pdf": None}
    try:
        index = nse.results_index(ticker)
    except SourceError as e:
        return {**card, "status": "failed", "problems": [f"results index unavailable: {e}"]}

    basis, picked = pick_filings(index, qe)
    if "current" not in picked:
        return {**card, "status": "failed", "problems": [f"no results XBRL filed for quarter ending {qe}"]}
    card["basis"] = basis

    docs, computed = {}, {}
    for k, p in picked.items():
        d = parse_nse_dt(p["row"]["qe_Date"]).date()
        url = p["row"].get("xbrl")
        entry = {"quarter_end": d.isoformat(), "label": fiscal_label(d, fy_end_month), "xbrl_url": url,
                 "filed": p["row"].get("broadcast_Date"), "revisions_superseded": p["revisions"],
                 "audited": p["row"].get("audited")}
        try:
            body, sha = nse.fetch_bytes(url)
            doc = xbrl.parse(body, url)
            checks = validate(doc, ticker, company_name, basis, d)
            entry.update(sha256=sha, checks=checks, rounding=doc.meta.get("rounding"), taxonomy=doc.taxonomy)
            if all(c["ok"] for c in checks):
                docs[k] = doc
                computed[k] = metrics.compute(doc, doc.duration_ctx(quarter_start(d), d), doc.taxonomy)
            else:
                card["problems"].append(f"{k}: validation failed " +
                                        ", ".join(c["check"] for c in checks if not c["ok"]))
        except (SourceError, Exception) as e:  # one bad period must not sink the card
            entry["error"] = repr(e)
            card["problems"].append(f"{k}: {e!r}")
        card["periods"][k] = entry

    if "current" not in computed:
        return {**card, "status": "failed"}
    cur_doc = docs["current"]
    card["taxonomy"] = cur_doc.taxonomy
    scale = SCALE.get((cur_doc.meta.get("rounding") or "").lower(), 1e7)
    card["rounding"] = cur_doc.meta.get("rounding")

    # PDF corroboration for the current quarter
    pdf_pages, pdf_raw, pdf_info = None, None, None
    if announcements:
        filed = parse_nse_dt(picked["current"]["row"].get("broadcast_Date"))
        for cand in results_pdf_candidates(announcements, filed)[:3]:
            try:
                body, sha = nse.fetch_bytes(cand["attchmntFile"])
                if body is not None and not body.startswith(b"%PDF"):
                    continue
                raw = pdftext.raw_pages(body, sha)
                pg = [pdftext.normalise(t) for t in raw]
                checks = confirm_pdf(pg, company_name or ticker, qe, basis)
                info = {"url": cand["attchmntFile"], "subject": cand.get("desc"), "filed": cand.get("an_dt"),
                        "seq_id": cand.get("seq_id"), "sha256": sha, "n_pages": len(pg), "checks": checks,
                        "text_pages": sum(1 for t in pg if len(t) > 200)}
                if all(c["ok"] for c in checks):
                    pdf_pages, pdf_raw, pdf_info = pg, raw, info
                    break
                pdf_info = pdf_info or {**info, "rejected": True}
            except SourceError as e:
                pdf_info = pdf_info or {"url": cand["attchmntFile"], "error": str(e), "rejected": True}
    card["pdf"] = pdf_info

    basis_word = basis.lower()
    for mid, rec in computed["current"].items():
        m = rec["def"]
        row = {"id": m.id, "label": m.label, "value_kind": m.value_kind, "calculation_kind": m.kind,
               "formula": m.formula, "note": m.note, "def_version": m.version,
               "current": rec["value"], "locator": rec["locator"], "inputs": rec["inputs"],
               "unavailable_reason": rec["reason"]}
        others = {}
        for k in ("prev_q", "yoy_q"):
            base = computed.get(k, {}).get(mid, {}).get("value")
            row[k] = base
            row[f"{k}_change"] = metrics.change(rec["value"], base, m.value_kind)
            others[k] = base
        if m.id == "pbt" and cur_doc.taxonomy != "banking":
            share = cur_doc.num("ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
                                cur_doc.duration_ctx(quarter_start(qe), qe))
            if share:
                row["note"] = (f"As tagged in the filing: before share of associates/JVs "
                               f"(₹{share / 1e7:,.2f} cr this quarter). The printed 'profit before tax' "
                               "line may include it.")
        # Verification: XBRL is the company's own primary filing.
        row["verification_status"] = "primary_verified" if rec["value"] is not None else "unavailable"
        concept = (rec["locator"] or "").split("@")[0] or None
        row["definition"] = {"xbrl_concept": concept, "status": "unchecked",
                             "comparable_with": f"xbrl:{concept}" if concept else f"finn:{m.id}@v{m.version}"}
        row["pdf_page"] = None
        if pdf_pages and m.kind == "reported" and rec["value"] is not None:
            row["_cands"] = _candidates(pdf_pages, rec["value"], others, scale, basis_word, ROW_LABELS.get(m.id))
        if pdf_pages and m.kind == "calculated" and rec["value"] is not None:
            row["_input_cands"] = {}
            for tag, v in rec["inputs"].items():
                if v is None or tag not in _TAGS_PRINTED:
                    continue
                o = {k: computed.get(k, {}).get(mid, {}).get("inputs", {}).get(tag) for k in ("prev_q", "yoy_q")}
                row["_input_cands"][tag] = _candidates(pdf_pages, v, o, scale, basis_word, ROW_LABELS.get(tag))
        card["metrics"].append(row)

    # The statement page is where most column-aligned numbers land.
    aligned_pages = [c["page"] for r in card["metrics"] for c in r.get("_cands", []) if c["aligned"]]
    aligned_pages += [c["page"] for r in card["metrics"] for cs in r.get("_input_cands", {}).values()
                      for c in cs if c["aligned"]]
    stmt_page = max(set(aligned_pages), key=aligned_pages.count) if aligned_pages else None
    card["statement_page"] = stmt_page
    if pdf_info and pdf_raw and stmt_page:
        pdf_info["statement_page_repairs"] = pdftext.repairs(pdf_raw[stmt_page - 1])

    def choose(cands):
        aligned = [c for c in cands if c["aligned"]]
        return (next((c for c in aligned if c["page"] == stmt_page), None) or (aligned[0] if aligned else None),
                cands[0] if cands else None)

    for row in card["metrics"]:
        if "_cands" in row:
            best, any_hit = choose(row.pop("_cands"))
            if best:
                row["pdf_page"], row["pdf_match"] = best["page"], best["match"]
                row["corroboration"] = {"status": "aligned", **best,
                                        "raw": pdftext.raw_token(pdf_raw[best["page"] - 1], best["match"])}
                row["definition"]["status"] = "matches_print"
            else:
                row["corroboration"] = _unlocated(row, any_hit, pdf_pages, stmt_page, scale)
        elif row["calculation_kind"] == "reported" and row["current"] is not None:
            row["corroboration"] = {"status": "no_pdf"}
        if "_input_cands" in row:
            picked_inputs = {t: choose(cs)[0] for t, cs in row.pop("_input_cands").items()}
            row["input_pages"] = {t: (c["page"] if c else None) for t, c in picked_inputs.items()}
            row["input_alignment"] = {t: (c["aligned"] if c else None) for t, c in picked_inputs.items()}

    if card["problems"]:
        card["status"] = "partial"
    return card


def _candidates(pages, value, others, scale, basis_word, label) -> list[dict]:
    """Occurrences of `value` after its row label, with column alignment evidence.

    Aligned = the next column(s) in the same row hold the comparison periods' values taken from
    their own XBRL filings (SEBI layout: current, previous quarter, year-ago quarter; some
    companies print current, year-ago). A number that merely recurs elsewhere in a row cannot
    satisfy this."""
    out = []
    variants = {k: set(pdftext.number_variants(v, scale)) for k, v in others.items() if v is not None}
    for i, t in enumerate(pages):
        if basis_word not in t:
            continue
        for v, _s, e in pdftext.matches(t, value, scale, label):
            nxt = pdftext.following_numbers(t, e, 3)
            aligned = None
            if nxt and any(nxt[0] in vs for vs in variants.values()):
                aligned = {"by": next(k for k, vs in variants.items() if nxt[0] in vs), "column_offset": 1}
            elif len(nxt) > 1 and nxt[1] in variants.get("yoy_q", set()):
                aligned = {"by": "yoy_q", "column_offset": 2}
            out.append({"page": i + 1, "match": v, "next_tokens": nxt, "aligned": aligned})
    return out


def _unlocated(row, any_hit, pages, stmt_page, scale) -> dict:
    if any_hit:
        return {"status": "column_unconfirmed", "page": any_hit["page"], "match": any_hit["match"],
                "next_tokens": any_hit["next_tokens"]}
    lbl = DEFINITION_LABELS.get(row["id"])
    if lbl and stmt_page:
        found = pdftext.first_number_after(pages[stmt_page - 1], lbl)
        if found:
            printed_label, printed = found
            try:
                printed_v = float(printed.strip("()").replace(",", "")) * scale
            except ValueError:
                printed_v = None
            dp = len(printed.strip("()").partition(".")[2])
            rounding_tol = 0.5 * 10 ** -dp * scale * 1.01  # anything beyond print rounding is a real difference
            if printed_v and abs(printed_v - row["current"]) > rounding_tol:
                row["definition"]["status"] = "differs_from_print"
                row["definition"]["excluded_from"] = "comparisons that need the printed / company-defined figure"
                return {"status": "definition_differs", "page": stmt_page, "printed_label": printed_label,
                        "printed_value": printed, "printed_value_inr": printed_v}
    return {"status": "not_located"}


# Printed rows whose definition commonly differs from the XBRL concept we report.
DEFINITION_LABELS = {"pbt": r"[bh]efore tax\b"}

# Row labels a located number must sit after (association check, not just a string match).
ROW_LABELS = {  # tolerant of OCR noise ("hefore", "proflt") and wording variants
    "revenue": r"revenue\s+fr\w{1,3}\s+operations|income from operations",
    "pbt": r"[bh]efore (tax|exceptional|share)",
    "pat": r"pro\w{1,3}t\W{0,4}(\(?l[oa]ss\W{0,3})?\W{0,3}(after tax|for the)|net pro\w{1,3}t",
    "ppop": r"operating profit before provisions?",
    "provisions": r"provisions",
    "ProfitBeforeExceptionalItemsAndTax": r"[bh]efore (tax|exceptional|share)",
    "FinanceCosts": r"finance costs?",
    "DepreciationDepletionAndAmortisationExpense": r"depreciation",
    "OtherIncome": r"other [il]ncome",
    "InterestEarned": r"rest (earned|income)",
}

_TAGS_PRINTED = {"ProfitBeforeExceptionalItemsAndTax", "FinanceCosts",
                 "DepreciationDepletionAndAmortisationExpense", "OtherIncome", "InterestEarned"}
