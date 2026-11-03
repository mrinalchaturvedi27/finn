"""Earnings-call transcripts from the company's own exchange filings.

Discovery: the company's NSE announcements classified as transcripts. Some companies file only a
cover letter linking to the transcript on their investor-relations site; the link embedded in that
letter is followed (still the company's own document). Anything that cannot be read is recorded as
a failure, never silently skipped.
"""
import io
import re
from datetime import date, datetime, timedelta

import pdfplumber
import requests

from ..classify import classify
from ..extract import pdftext
from ..sources.nse import NSE, SourceError, parse_nse_dt

UA = "Mozilla/5.0 (compatible; FINN research prototype)"
LINK_LETTER = re.compile(r"uploaded on the (investor|website)|web-?\s?link|available (at|on) the|can be (accessed|availed)",
                         re.I)
CALL_DATE = re.compile(r"(?:held on|call on|dated)\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*,?\s+(\d{4})", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                      "nov", "dec"], 1)}
_NAME = r"(?:[A-Z][a-z'\-]+|[A-Z]{2,}|[A-Z]\.)"  # Title-case word, ALL-CAPS word, or an initial
SPEAKER = re.compile(rf"^[ \t]*((?:Mr|Ms|Mrs|Dr)?\.?[ \t]*{_NAME}(?:[ \t]+{_NAME}){{0,3}})[ \t]*:[ \t]*", re.M)
TITLE_WORDS = re.compile(r"\b(limited|ltd|director|officer|chairman|chairperson|president|head|manager|secretary|"
                         r"accounts|taxation|finance|investor|relations|management|participants|road|floor|"
                         r"andheri|mumbai|india)\b", re.I)
NOT_SPEAKERS = {"sub", "subject", "encl", "note", "ref", "date", "scrip code", "symbol", "website", "cin",
                "management", "participants", "disclaimer", "page", "registered office", "tel", "fax", "email"}


def find(nse: NSE, ticker: str, today: date, months: int = 15) -> list[dict]:
    """Transcript filings in the window, newest first, one per call (re-posts dropped)."""
    rows = nse.announcements(ticker, today - timedelta(days=months * 31), today)
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: r.get("sort_date") or "", reverse=True):
        c = classify(r.get("desc") or "", r.get("attchmntText"))
        if c.subkind != "transcript" or not r.get("attchmntFile"):
            continue
        text = r.get("attchmntText") or ""
        if re.search(r"analyst meet|investor meet|investor day|analyst day", text, re.I):
            continue  # earnings calls only: guidance is checked against the quarter's numbers
        filed = parse_nse_dt(r.get("an_dt")) or parse_nse_dt(r.get("sort_date"))
        call = _call_date(text) or (filed.date() if filed else None)
        if call in seen:
            continue
        seen.add(call)
        out.append({"filed_at": filed.isoformat() if filed else None, "call_date": call.isoformat() if call else None,
                    "nse_url": r["attchmntFile"], "subject": text[:200]})
    return out


def _call_date(text: str) -> date | None:
    m = CALL_DATE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    except (KeyError, ValueError):
        return None


def load(nse: NSE, t: dict) -> dict:
    """Fetch the transcript text: the filed PDF, or the company document its cover letter links to."""
    body, sha = nse.fetch_bytes(t["nse_url"])
    pages = pdftext.raw_pages(body, sha)
    t = {**t, "url": t["nse_url"], "source": "nse_filing", "sha256": sha}
    if len(pages) <= 2 and LINK_LETTER.search(" ".join(pages)):
        link = _transcript_link(body)
        if not link:
            raise SourceError("filed only a cover letter, and it has no transcript link")
        r = requests.get(link, timeout=60, headers={"User-Agent": UA})
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            raise SourceError(f"cover letter links to {link}, which returned HTTP {r.status_code} / not a PDF")
        import hashlib
        sha = hashlib.sha256(r.content).hexdigest()
        pages = pdftext.raw_pages(r.content, sha)
        t.update(url=link, source="company_site_via_filing", sha256=sha)
    if sum(len(p) for p in pages) < 2000:
        raise SourceError("transcript has almost no extractable text (scanned?)")
    t["pages"] = pages
    return t


def _transcript_link(pdf_body: bytes) -> str | None:
    with pdfplumber.open(io.BytesIO(pdf_body)) as pdf:
        links = [h.get("uri") for p in pdf.pages for h in p.hyperlinks if h.get("uri")]
    pdfs = [u for u in links if u.lower().split("?")[0].endswith(".pdf")]
    return pdfs[0] if pdfs else None


def turns(pages: list[str]) -> list[dict]:
    """Speaker turns with page numbers and roles: management / analyst / host / moderator."""
    out = []
    for pno, page in enumerate(pages, 1):
        page = pdftext.normalise_keep_case(page)
        marks = [m for m in SPEAKER.finditer(page) if m.group(1).strip().lower() not in NOT_SPEAKERS
                 and not TITLE_WORDS.search(m.group(1))]
        if not marks and out:
            out[-1]["text"] += " " + page
            continue
        if marks and marks[0].start() > 0 and out:
            out[-1]["text"] += " " + page[:marks[0].start()]
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(page)
            out.append({"speaker": _clean(m.group(1)), "page": pno, "text": page[m.end():end].strip()})
    analysts, host = set(), None
    for t in out:
        if t["speaker"].lower() == "moderator":
            for m in re.finditer(r"(?:question|questions)\s+(?:is\s+|comes\s+)?(?:from|by)\s+(?:the\s+line\s+of\s+)?"
                                 r"((?:Mr\.?|Ms\.?|Mrs\.?)?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", t["text"]):
                analysts.add(_key(m.group(1)))
            m = re.search(r"hand (?:the )?(?:conference|call|floor) over to\s+((?:Mr\.?|Ms\.?|Mrs\.?)?\s*[A-Z][a-z]+"
                          r"(?:\s+[A-Z][a-z]+){0,2})\s+(?:from|of)\s+[A-Z]", t["text"])
            if m and host is None:
                host = _key(m.group(1))
    # a speaker the moderator never introduced, but who mostly asks questions, is an analyst too
    asks = {}
    for t in out:
        a = asks.setdefault(_key(t["speaker"]), [0, 0])
        a[0] += t["text"].rstrip().endswith("?") or t["text"].count("?") >= 2
        a[1] += 1
    analysts |= {k for k, (q, n) in asks.items() if q * 2 > n}
    for t in out:
        k = _key(t["speaker"])
        t["role"] = ("moderator" if k == "moderator" else "host" if k == host
                     else "analyst" if k in analysts else "management")
    return out


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _key(s: str) -> str:
    return re.sub(r"^(mr|ms|mrs|dr)\.?\s+", "", _clean(s).lower())
