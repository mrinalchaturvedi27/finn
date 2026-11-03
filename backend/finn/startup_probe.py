"""Temporary cloud source probe, run inside the deployed container at startup.

Enabled only by FINN_STARTUP_PROBE=1 (disable it again once the report is captured).
It runs probe/source_probe.py in a background subprocess with a hard timeout, so the API
and its health check come up normally. The JSON report goes to the logs between
markers and is held in memory for GET /api/probe-report while the flag is on.
"""
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

MARKER = "=== FINN_PROBE_REPORT_JSON ==="
SCRIPT = Path(__file__).resolve().parents[2] / "probe" / "source_probe.py"

STATE: dict = {"status": "disabled"}


def enabled() -> bool:
    return os.environ.get("FINN_STARTUP_PROBE") == "1"


def _log(msg: str):
    print(f"[finn-probe] {msg}", flush=True)


def _run(timeout: int):
    STATE.update(status="running", started_at=datetime.now().isoformat(timespec="seconds"), timeout_s=timeout)
    _log(f"start timeout={timeout}s script={SCRIPT}")
    try:
        p = subprocess.run([sys.executable, str(SCRIPT), "--out", "-"], capture_output=True, text=True,
                           timeout=timeout, cwd=SCRIPT.parents[1])
    except subprocess.TimeoutExpired as e:
        STATE.update(status="timeout", finished_at=datetime.now().isoformat(timespec="seconds"))
        _log(f"timeout after {timeout}s; partial stdout follows")
        print((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), flush=True)
        return
    out = p.stdout
    report = None
    if MARKER in out:
        report = out.split(MARKER, 1)[1].strip().splitlines()[0]
    STATE.update(status="ok" if p.returncode == 0 and report else "failed", returncode=p.returncode,
                 finished_at=datetime.now().isoformat(timespec="seconds"), report_json=report,
                 stderr_tail=p.stderr[-2000:] if p.returncode else None)
    # report on one line between markers, then the human summary
    print(out, flush=True)
    if p.returncode:
        print(p.stderr[-2000:], flush=True)
    _log(f"done status={STATE['status']} returncode={p.returncode}")


def start():
    if not enabled():
        return
    timeout = int(os.environ.get("FINN_PROBE_TIMEOUT", "600"))
    threading.Thread(target=_run, args=(timeout,), daemon=True, name="finn-startup-probe").start()
