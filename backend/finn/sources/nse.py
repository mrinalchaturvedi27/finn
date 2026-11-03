"""NSE access: announcements feed, integrated-filing results index, archives.

The homepage cookie step is attempted but not required — the JSON APIs have
answered without it (homepage returned 403 during the local probe).
"""
import hashlib
import time
from datetime import date, datetime
from pathlib import Path

import requests

from .. import snapshot

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
BASE = "https://www.nseindia.com"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"


class SourceError(Exception):
    pass


def incomplete(body: bytes, content_length: str | None, content_encoding: str | None = None) -> str | None:
    """Why a downloaded body is not the whole file, or None. Truncated files are never cached.
    Content-Length counts the bytes on the wire, so it is only comparable when the body was not
    compressed (requests decompresses gzip/deflate transparently)."""
    if (content_length and content_length.isdigit() and not content_encoding
            and len(body) != int(content_length)):
        return f"{len(body)} of {content_length} bytes"
    if body.startswith(b"%PDF") and b"%%EOF" not in body[-2048:]:
        return "PDF has no end-of-file marker"
    return None


class NSE:
    def __init__(self, min_interval: float = 0.6):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "*/*",
                               "Accept-Language": "en-US,en;q=0.9", "Referer": BASE + "/"})
        self.min_interval = min_interval
        self._last = 0.0
        if snapshot.MODE == "replay":
            return
        try:
            self.s.get(BASE, timeout=10)
        except requests.RequestException:
            pass

    def _get(self, url: str, *, retries: int = 3, timeout: int = 30) -> requests.Response:
        err = None
        for attempt in range(retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.s.get(url, timeout=timeout)
                self._last = time.monotonic()
                if r.status_code == 200:
                    return r
                err = f"HTTP {r.status_code}"
                if r.status_code in (401, 403) and attempt == 0:
                    self.s.get(BASE, timeout=10)  # refresh cookies once
            except requests.RequestException as e:
                err = repr(e)
            time.sleep(1.5 * (2 ** attempt))
        raise SourceError(f"{url}: {err}")

    def _json(self, url: str):
        if snapshot.MODE == "replay":
            try:
                return snapshot.api_get(url)
            except snapshot.Missing as e:
                raise SourceError(str(e)) from e
        r = self._get(url)
        try:
            data = r.json()
        except ValueError as e:
            raise SourceError(f"{url}: non-JSON body ({r.text[:80]!r})") from e
        if snapshot.MODE == "record":
            snapshot.api_put(url, data)
        return data

    def announcements(self, symbol: str, start: date, end: date) -> list[dict]:
        url = (f"{BASE}/api/corporate-announcements?index=equities&symbol={symbol}"
               f"&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}")
        data = self._json(url)
        rows = data if isinstance(data, list) else data.get("data", [])
        if not isinstance(rows, list):
            raise SourceError(f"unexpected announcements shape for {symbol}")
        return rows

    def results_index(self, symbol: str) -> list[dict]:
        """Integrated-filing financial results (one row per quarter x basis x revision)."""
        url = (f"{BASE}/api/integrated-filing-results?index=equities&symbol={symbol}"
               "&type=Integrated%20Filing-%20Financials")
        data = self._json(url)
        return data.get("data", []) if isinstance(data, dict) else data

    def fetch_bytes(self, url: str) -> tuple[bytes | None, str]:
        """Archive fetch with a content-addressed disk cache. Returns (bytes, sha256).
        In replay, PDFs come back as (None, sha) — only their extracted text is snapshotted."""
        if snapshot.MODE == "replay":
            try:
                return snapshot.blob_get(url)
            except snapshot.Missing as e:
                raise SourceError(str(e)) from e
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(url.encode()).hexdigest()
        path = CACHE_DIR / key
        body = path.read_bytes() if path.exists() else None
        if body is not None and incomplete(body, None):
            body = None  # a truncated file cached by an older version
        if body is None:
            why = None
            for _ in range(3):  # archives occasionally end a 200 response early
                r = self._get(url, timeout=60)
                why = incomplete(r.content, r.headers.get("content-length"), r.headers.get("content-encoding"))
                if not why:
                    body = r.content
                    break
            if body is None:
                raise SourceError(f"{url}: incomplete download ({why})")
            path.write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        if snapshot.MODE == "record":
            snapshot.blob_put(url, body, sha)
        return body, sha


def parse_nse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(s.strip().title() if "-" in s[:6] else s.strip(), fmt)
        except ValueError:
            continue
    return None
