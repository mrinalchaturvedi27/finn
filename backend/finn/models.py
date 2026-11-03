"""Frozen evidence model (milestone 1).

Every displayed number is a MetricObs. Verification (was it substantiated by a
primary document?) and calculation (reported vs derived by us) are separate
properties. Guidance / Comparison / ResearchJob are defined now so the schema
does not change shape in milestone 3.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "company"
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    isin: Mapped[str | None] = mapped_column(String(12))
    sector: Mapped[str | None] = mapped_column(String(64))
    # industrial | bank | nbfc — decides which metric set applies
    reporting_format: Mapped[str | None] = mapped_column(String(16))
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, default=3)
    in_portfolio: Mapped[bool] = mapped_column(default=False)


class Document(Base):
    """Any fetched primary artefact: filing PDF, results XBRL, AR, transcript."""
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("company.ticker"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # filing_pdf | results_xbrl | annual_report | transcript
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    basis: Mapped[str | None] = mapped_column(String(16))  # consolidated | standalone
    url: Mapped[str] = mapped_column(Text, unique=True)
    sha256: Mapped[str | None] = mapped_column(String(64))
    fetch_state: Mapped[str] = mapped_column(String(16), default="pending")  # pending|ok|failed
    parse_state: Mapped[str] = mapped_column(String(16), default="pending")  # pending|ok|partial|failed
    error: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(String(16))
    revision: Mapped[str | None] = mapped_column(String(32))  # exchange's Original / Revised marker
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)


class Event(Base):
    """A real-world happening; several filings can belong to one event."""
    __tablename__ = "event"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("company.ticker"), index=True)
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    materiality: Mapped[int] = mapped_column(Integer)  # 0-100, independent of category
    materiality_reasons: Mapped[list] = mapped_column(JSON, default=list)
    # read = we know what it says; unread = metadata too thin to judge
    read_state: Mapped[str] = mapped_column(String(16), default="read")
    summary: Mapped[str | None] = mapped_column(Text)
    primary_filing_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSON)  # e.g. results card payload
    group_key: Mapped[str] = mapped_column(String(200), unique=True)


class Filing(Base):
    __tablename__ = "filing"
    __table_args__ = (UniqueConstraint("exchange", "exch_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("company.ticker"), index=True)
    exchange: Mapped[str] = mapped_column(String(8))
    exch_id: Mapped[str] = mapped_column(String(64))
    filed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    subject: Mapped[str] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    attachment_url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    category_source: Mapped[str] = mapped_column(String(16))  # rule | rule_weak | llm | none
    event_id: Mapped[int | None] = mapped_column(ForeignKey("event.id"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(200), index=True)
    duplicate_of: Mapped[int | None] = mapped_column(Integer)  # NSE/BSE copy or re-post
    revision_of: Mapped[int | None] = mapped_column(Integer)  # corrigendum / revised filing
    document_id: Mapped[int | None] = mapped_column(ForeignKey("document.id"))


class MetricObs(Base):
    __tablename__ = "metric_obs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("company.ticker"), index=True)
    metric: Mapped[str] = mapped_column(String(48))
    metric_def_id: Mapped[str] = mapped_column(String(48))
    metric_def_version: Mapped[int] = mapped_column(Integer)
    value_kind: Mapped[str] = mapped_column(String(16))  # absolute | growth_pct | margin_pct | ratio
    scope: Mapped[str] = mapped_column(String(64), default="company")  # company | segment:<name> | geo:<name>
    basis: Mapped[str] = mapped_column(String(16))
    period_type: Mapped[str] = mapped_column(String(4))  # Q | H1 | 9M | FY
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, default=3)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(8), default="INR")
    verification_status: Mapped[str] = mapped_column(String(20))  # primary_verified | secondary_only | unavailable
    calculation_kind: Mapped[str] = mapped_column(String(12))  # reported | calculated
    formula: Mapped[str | None] = mapped_column(Text)
    input_obs_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_doc_id: Mapped[int | None] = mapped_column(ForeignKey("document.id"))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_locator: Mapped[str | None] = mapped_column(Text)  # e.g. XBRL tag + context
    # A located copy of the same number in another primary doc (only set if matched)
    corroboration_doc_id: Mapped[int | None] = mapped_column(ForeignKey("document.id"))
    corroboration_page: Mapped[int | None] = mapped_column(Integer)
    related_filing_id: Mapped[int | None] = mapped_column(ForeignKey("filing.id"))  # context only, not a check
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    cache_key: Mapped[str | None] = mapped_column(String(128))


class Guidance(Base):
    __tablename__ = "guidance"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("company.ticker"), index=True)
    stated_on: Mapped[date] = mapped_column(Date)
    source_doc_id: Mapped[int] = mapped_column(ForeignKey("document.id"))
    page: Mapped[int | None] = mapped_column(Integer)
    quote_norm: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(48))
    value_kind: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(64))
    basis: Mapped[str | None] = mapped_column(String(16))
    unit: Mapped[str] = mapped_column(String(8))
    direction: Mapped[str] = mapped_column(String(12))  # at_least | at_most | range | point
    target_low: Mapped[float | None] = mapped_column(Float)
    target_high: Mapped[float | None] = mapped_column(Float)
    qualifier: Mapped[str] = mapped_column(String(12), default="none")  # approx | none
    target_period_type: Mapped[str] = mapped_column(String(4))
    target_period_start: Mapped[date] = mapped_column(Date)
    target_period_end: Mapped[date] = mapped_column(Date)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("guidance.id"))
    cache_key: Mapped[str | None] = mapped_column(String(128))


class Comparison(Base):
    __tablename__ = "comparison"
    id: Mapped[int] = mapped_column(primary_key=True)
    guidance_id: Mapped[int] = mapped_column(ForeignKey("guidance.id"), index=True)
    actual_obs_ids: Mapped[list] = mapped_column(JSON, default=list)
    calc_shown: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # delivered | partial | missed | pending | not_comparable
    reason: Mapped[str | None] = mapped_column(Text)
    tolerance: Mapped[float | None] = mapped_column(Float)
    explanation_llm: Mapped[str | None] = mapped_column(Text)
    rules_version: Mapped[int] = mapped_column(Integer, default=1)


class PriceBar(Base):
    __tablename__ = "price_bar"
    ticker: Mapped[str] = mapped_column(ForeignKey("company.ticker"), primary_key=True)
    session: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (UniqueConstraint("ticker", "kind", "session", "event_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("company.ticker"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # volume | price | announcement
    session: Mapped[date | None] = mapped_column(Date)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("event.id"))
    observed: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class IngestRun(Base):
    """Freshness log: every scheduled or manual fetch, successful or not."""
    __tablename__ = "ingest_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # nse_announcements | prices | results_xbrl
    mode: Mapped[str] = mapped_column(String(12))  # snapshot | live
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12))  # ok | partial | failed
    data_through: Mapped[datetime | None] = mapped_column(DateTime)
    items: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    host: Mapped[str | None] = mapped_column(String(64))


class ResearchJob(Base):
    __tablename__ = "research_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(16))  # queued|fetching|parsing|extracting|comparing|done|partial|failed
    cache_key: Mapped[str | None] = mapped_column(String(128))
    doc_failures: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
