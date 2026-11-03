"""Explicit, versioned schema migrations.

    python -m finn.migrate            # upgrade to the latest version
    python -m finn.migrate --status   # print the current and latest versions; exit 1 if behind

The live database is only changed by running this; the API and the worker check the version
and refuse a database that is behind (the API then falls back to the bundled seed).
"""
import argparse
import sys
from datetime import datetime

from sqlalchemy import inspect, text

from .models import Base


def _v1_baseline(conn):
    """All tables as of milestone 2 (models.py)."""
    Base.metadata.create_all(conn)


def _add_columns(conn, table: str, cols: dict):
    have = {c["name"] for c in inspect(conn).get_columns(table)}
    for name, ddl in cols.items():
        if name not in have:  # a fresh database already has it from the baseline
            conn.execute(text(f"alter table {table} add column {name} {ddl}"))


def _v2_research_reports(conn):
    """Research results are stored with their job."""
    _add_columns(conn, "research_job", {"finished_at": "timestamp", "requested_via": "varchar(16)",
                                        "report": "json"})


MIGRATIONS = {1: _v1_baseline, 2: _v2_research_reports}
LATEST = max(MIGRATIONS)


def current(engine) -> int | None:
    """Applied version, 0 for a database with FINN tables but no version table, None if empty."""
    names = set(inspect(engine).get_table_names())
    if "schema_version" in names:
        with engine.connect() as c:
            return c.execute(text("select max(version) from schema_version")).scalar() or 0
    return 0 if "filing" in names else None


def upgrade(engine) -> list[int]:
    applied = []
    with engine.begin() as conn:
        conn.execute(text("create table if not exists schema_version "
                          "(version integer primary key, applied_at varchar(32) not null)"))
        have = conn.execute(text("select max(version) from schema_version")).scalar() or 0
        for v in range(have + 1, LATEST + 1):
            MIGRATIONS[v](conn)
            conn.execute(text("insert into schema_version (version, applied_at) values (:v, :t)"),
                         {"v": v, "t": datetime.utcnow().isoformat(timespec="seconds") + "Z"})
            applied.append(v)
    return applied


class SchemaBehind(RuntimeError):
    pass


def require_latest(engine):
    v = current(engine)
    if v != LATEST:
        raise SchemaBehind(f"database schema is version {v}, expected {LATEST}: run python -m finn.migrate")


def main():
    from .db import engine, redacted_url
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        v = current(engine)
        print(f"database {redacted_url()}: schema version {v}, latest {LATEST}")
        sys.exit(0 if v == LATEST else 1)
    applied = upgrade(engine)
    print(f"database {redacted_url()}: applied {applied or 'nothing'}; now version {current(engine)}")


if __name__ == "__main__":
    main()
