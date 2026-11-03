"""Record / replay of source responses so a seeded database is reproducible offline.

record: live fetches are also written to the snapshot directory.
replay: every fetch is served from the snapshot directory; nothing touches the network.

Stored: JSON API responses, XBRL files, raw extracted PDF text (not the PDFs — the
text is what the pipeline consumes, and keeping it raw lets normalisation re-run),
price bars, and the capture clock.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

MODE: str | None = None  # None | "record" | "replay"
DIR: Path | None = None
CAPTURED_AT: datetime | None = None


def configure(mode: str | None, directory: str | Path | None):
    global MODE, DIR, CAPTURED_AT
    MODE, DIR = mode, Path(directory) if directory else None
    if MODE == "record":
        for sub in ("api", "blobs", "pdftext"):
            (DIR / sub).mkdir(parents=True, exist_ok=True)
        CAPTURED_AT = None
    elif MODE == "replay":
        meta = json.loads((DIR / "manifest.json").read_text())
        CAPTURED_AT = datetime.fromisoformat(meta["captured_at"])


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def _manifest() -> dict:
    p = DIR / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {"captured_at": None, "urls": {}}


def _save_manifest(m: dict):
    (DIR / "manifest.json").write_text(json.dumps(m, indent=1, sort_keys=True))


def set_captured_at(t: datetime):
    m = _manifest()
    m["captured_at"] = t.isoformat(timespec="seconds")
    _save_manifest(m)


class Missing(Exception):
    pass


def api_get(url: str):
    p = DIR / "api" / f"{_key(url)}.json"
    if not p.exists():
        raise Missing(f"not in snapshot: {url}")
    return json.loads(p.read_text())


def api_put(url: str, data):
    (DIR / "api" / f"{_key(url)}.json").write_text(json.dumps(data))
    m = _manifest()
    m["urls"][url] = {"kind": "api", "key": _key(url)}
    _save_manifest(m)


def blob_get(url: str) -> tuple[bytes | None, str]:
    """Returns (bytes or None for text-only PDFs, sha256)."""
    ent = _manifest()["urls"].get(url)
    if not ent:
        raise Missing(f"not in snapshot: {url}")
    if ent["kind"] == "pdf":
        return None, ent["sha256"]
    return (DIR / "blobs" / ent["sha256"]).read_bytes(), ent["sha256"]


def blob_put(url: str, body: bytes, sha: str):
    is_pdf = body.startswith(b"%PDF")
    if not is_pdf:
        (DIR / "blobs" / sha).write_bytes(body)
    m = _manifest()
    m["urls"][url] = {"kind": "pdf" if is_pdf else "blob", "sha256": sha}
    _save_manifest(m)


def pdftext_get(sha: str) -> list[str] | None:
    p = DIR / "pdftext" / f"{sha}.json"
    return json.loads(p.read_text()) if p.exists() else None


def pdftext_put(sha: str, raw_pages: list[str]):
    (DIR / "pdftext" / f"{sha}.json").write_text(json.dumps(raw_pages))


def json_get(name: str):
    return json.loads((DIR / name).read_text())


def json_put(name: str, data):
    (DIR / name).write_text(json.dumps(data, default=str))
