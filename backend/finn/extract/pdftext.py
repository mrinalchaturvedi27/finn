"""PDF text with page provenance and normalised matching.

Raw extracted text is kept (cached and snapshotted); normalisation — including the
OCR repairs — is re-applied on read, so repaired text can always be traced to raw.
"""
import io
import json
import re
import unicodedata
from pathlib import Path

import pdfplumber

from .. import snapshot
from ..sources.nse import CACHE_DIR
from ..versions import PDF_RAW_VERSION

LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "’": "'", "‘": "'", "–": "-", "—": "-"}
NUM_TOKEN = re.compile(r"(?<![a-z])[\d.,()o]*\d[\d.,()o]*(?![a-z])")


def _doubled(t: str) -> bool:
    return len(t) % 2 == 0 and t[0::2] == t[1::2]


def _is_doubled_page(text: str) -> bool:
    long_toks = [t for t in text.split() if len(t) >= 4]
    return bool(long_toks) and sum(map(_doubled, long_toks)) / len(long_toks) >= 0.6


def _undouble(text: str) -> str:
    """Some OCR layers emit every glyph twice ("DDIIXXOONN 1100"). Collapse only when most tokens are doubled."""
    if not _is_doubled_page(text):
        return text
    return " ".join(t[0::2] if _doubled(t) else t for t in text.split())


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _undouble(text)
    for a, b in LIGATURES.items():
        text = text.replace(a, b)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # re-join hyphenated line breaks
    text = re.sub(r"\s+", " ", text).strip().lower()
    return NUM_TOKEN.sub(_ocr_digits, text)


def normalise_keep_case(text: str) -> str:
    """Like normalise() but keeps case and line breaks (speaker labels in transcripts start lines)."""
    text = unicodedata.normalize("NFKC", text)
    text = _undouble(text)
    for a, b in LIGATURES.items():
        text = text.replace(a, b)
    text = re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _ocr_digits(m: re.Match) -> str:
    """OCR'd filings read zeros as the letter o ("9o575.33"); fix only inside numeric tokens."""
    return m.group(0).replace("o", "0")


def repairs(raw: str) -> list[str]:
    """Which repairs normalisation applied to this raw page."""
    out = []
    t = unicodedata.normalize("NFKC", raw)
    if _is_doubled_page(t):
        out.append("collapsed doubled OCR glyphs")
    low = re.sub(r"\s+", " ", _undouble(t)).lower()
    n = sum(1 for m in NUM_TOKEN.finditer(low) if "o" in m.group(0))
    if n:
        out.append(f"OCR letter 'o' read as zero in {n} numeric tokens")
    return out


def raw_pages(body: bytes | None, sha: str) -> list[str]:
    """Raw per-page text as extracted (dedupe_chars only). Cached; recorded/replayed via snapshot."""
    if snapshot.MODE == "replay":
        got = snapshot.pdftext_get(sha)
        if got is None:
            raise snapshot.Missing(f"pdf text {sha} not in snapshot")
        return got
    path = Path(CACHE_DIR) / f"{sha}.{PDF_RAW_VERSION}.raw.json"
    if path.exists():
        out = json.loads(path.read_text())
    else:
        with pdfplumber.open(io.BytesIO(body)) as pdf:
            # dedupe_chars: some filings overprint glyphs for fake bold
            out = [p.dedupe_chars().extract_text() or "" for p in pdf.pages]
        path.write_text(json.dumps(out))
    if snapshot.MODE == "record":
        snapshot.pdftext_put(sha, out)
    return out


def pages(body: bytes | None, sha: str) -> list[str]:
    """Normalised text per page (index + 1 = page number)."""
    return [normalise(t) for t in raw_pages(body, sha)]


def number_variants(value_inr: float, scale: float) -> list[str]:
    """How a rupee value is likely printed at the filing's rounding level."""
    v = value_inr / scale
    neg = v < 0
    out = []
    for dp in (2, 0, 1):
        r = round(abs(v), dp)
        s = f"{r:.{dp}f}"
        whole, _, frac = s.partition(".")
        for grouped in (_indian(whole), f"{int(whole):,}", whole):
            txt = grouped + (f".{frac}" if frac else "")
            out.append(f"({txt})" if neg else txt)
            if neg:
                out.append(f"-{txt}")
    return list(dict.fromkeys(out))


def _indian(whole: str) -> str:
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return f"{head},{tail}"


def matches(text: str, value_inr: float, scale: float, label: str | None = None, window: int = 160):
    """All standalone occurrences of the value on one page, optionally preceded by its row label.
    Yields (variant, start, end)."""
    for v in number_variants(value_inr, scale):
        if len(v.replace(",", "").replace(".", "").strip("()-")) < 3:
            continue  # too short to be evidence
        for m in re.finditer(rf"(?<![\d.,]){re.escape(v)}(?![\d]|[.,]\d)", text):
            if label is None or re.search(label, text[max(0, m.start() - window):m.start()]):
                yield v, m.start(), m.end()


def following_numbers(text: str, pos: int, n: int = 4) -> list[str]:
    """Numeric tokens that follow `pos` in the same row (stops at the next worded label)."""
    out = []
    for tok in text[pos:pos + 240].split():
        if re.fullmatch(r"\(?-?[\d,]*\.?\d+\)?", tok) or tok in ("-", "—"):
            out.append(tok)
            if len(out) >= n:
                break
        elif re.search(r"[a-z]{3,}", tok):
            break
    return out


def first_number_after(text: str, label: str) -> tuple[str, str] | None:
    """(printed label snippet, first numeric token) for the first row matching `label`."""
    m = re.search(label, text)
    if not m:
        return None
    nums = following_numbers(text, m.end(), 1)
    # a label may run on after its keyword ("before tax and minority interest 28662.54")
    if not nums:
        tail = re.search(r"\(?-?[\d,]*\.\d+\)?|\(?-?\d{1,3}(?:,\d{2,3})+\)?", text[m.end():m.end() + 120])
        if not tail:
            return None
        nums = [tail.group(0)]
    start = max(0, m.start() - 40)
    prev_row_end = list(re.finditer(r"[\d)]\s", text[start:m.start()]))
    if prev_row_end:  # start after the previous row's last figure / serial number
        start += prev_row_end[-1].end()
    label_text = text[start:text.find(nums[0], m.end())].strip()
    return label_text, nums[0]


def raw_token(raw_page: str, norm_token: str) -> str | None:
    """The raw-text token that normalises to `norm_token` (shows what the OCR actually said)."""
    page_doubled = _is_doubled_page(unicodedata.normalize("NFKC", raw_page))
    for tok in raw_page.split():
        t = tok[0::2] if page_doubled and _doubled(tok) else tok
        if NUM_TOKEN.sub(_ocr_digits, t.lower()) == norm_token:
            return tok
    return None


def find_number(page_texts: list[str], value_inr: float, scale: float,
                must_contain: list[str] | None = None, label: str | None = None, window: int = 160):
    """Pages where the value appears (first label-satisfying occurrence per page). [(page_no, text)]."""
    hits = []
    for i, t in enumerate(page_texts):
        if must_contain and not all(re.search(p, t) for p in must_contain):
            continue
        m = next(matches(t, value_inr, scale, label, window), None)
        if m:
            hits.append((i + 1, m[0]))
    return hits
