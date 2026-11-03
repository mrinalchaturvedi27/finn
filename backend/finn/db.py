import os
import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEED_URL = f"sqlite:///{DATA_DIR / 'finn.db'}"  # the historical snapshot built into the image
CONFIGURED_URL = os.environ.get("FINN_DB_URL") or SEED_URL


def _normalise(url: str) -> str:
    # hosted Postgres URLs come as postgres:// or postgresql://; use the psycopg 3 driver
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _engine(url: str):
    kw = {"pool_pre_ping": True}
    if _normalise(url).startswith("postgresql"):
        # small pool: free hosted plans allow ~15 connections shared by the API and the worker
        kw.update(connect_args={"connect_timeout": 10}, pool_size=3, max_overflow=2, pool_recycle=1800)
        # Leave room within Aiven's 15-connection limit for the API, worker,
        # migrations, and a short overlap during deployments.
        kw.update(pool_size=2, max_overflow=1, pool_timeout=10)
    return create_engine(_normalise(url), future=True, **kw)


SOURCE = "seed" if CONFIGURED_URL == SEED_URL else "configured"  # set by use_for_api()
FALLBACK_REASON: str | None = None
DB_URL = _normalise(CONFIGURED_URL)
try:
    engine = _engine(DB_URL)
except Exception as _e:  # e.g. database driver missing: serve the seed rather than crash
    print(f"[finn-db] cannot create engine: {type(_e).__name__}: {str(_e).splitlines()[0][:200]}", flush=True)
    FALLBACK_REASON = type(_e).__name__
    DB_URL, engine = _normalise(SEED_URL), _engine(SEED_URL)
Session = sessionmaker(engine, expire_on_commit=False)


def _public_reason(e: Exception) -> str:
    """For /api/health: never the host or driver message (those go to the logs only)."""
    from .migrate import SchemaBehind
    return str(e) if isinstance(e, SchemaBehind) else type(e).__name__


def redacted_url(url: str | None = None) -> str:
    """Safe to log: drops credentials and query parameters."""
    u = url or DB_URL
    u = re.sub(r"//[^@/]*@", "//***@", u)
    return u.split("?", 1)[0]


def use(url: str):
    global engine, DB_URL
    DB_URL = _normalise(url)
    engine = _engine(DB_URL)
    Session.configure(bind=engine)


def use_for_api():
    """API startup: use the configured database only if it is reachable and migrated; otherwise
    serve the bundled seed and say why. Never creates or alters tables in the live database."""
    global SOURCE, FALLBACK_REASON
    from .migrate import require_latest
    if CONFIGURED_URL == SEED_URL:
        SOURCE = "seed"
        init_db()
        return
    if FALLBACK_REASON:  # the engine itself could not be created at import
        print(f"[finn-db] configured database unusable ({FALLBACK_REASON}); serving the seed", flush=True)
        SOURCE = "seed_fallback"
        init_db()
        return
    try:
        require_latest(engine)
        SOURCE = "live"
    except Exception as e:  # unreachable, auth, or schema behind
        FALLBACK_REASON = _public_reason(e)
        detail = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        print(f"[finn-db] {redacted_url()} unusable ({detail}); falling back to the seed", flush=True)
        use(SEED_URL)
        SOURCE = "seed_fallback"
        init_db()


def init_db():
    """Local SQLite only (seed builds, tests, dev). Hosted databases use python -m finn.migrate."""
    from .migrate import upgrade
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_URL.startswith("sqlite"):
        upgrade(engine)
