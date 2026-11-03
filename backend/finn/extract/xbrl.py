"""Parse NSE integrated-filing results XBRL into typed facts.

Each filing self-declares company symbol, reporting period, basis and rounding;
we validate those against what we expected before using any value.
"""
from dataclasses import dataclass, field
from datetime import date

from lxml import etree

XBRLI = "http://www.xbrl.org/2003/instance"


@dataclass
class Context:
    id: str
    start: date | None
    end: date | None
    instant: date | None
    dimensional: bool


@dataclass
class XbrlDoc:
    meta: dict
    contexts: dict[str, Context]
    facts: dict[tuple[str, str], str] = field(default_factory=dict)  # (localname, ctx) -> raw text
    taxonomy: str = "indas"  # indas | banking | nbfc

    def duration_ctx(self, start: date, end: date) -> str | None:
        for c in self.contexts.values():
            if not c.dimensional and c.start == start and c.end == end:
                if any(k[1] == c.id for k in self.facts):
                    return c.id
        return None

    def num(self, tag: str, ctx: str) -> float | None:
        raw = self.facts.get((tag, ctx))
        if raw is None or raw.strip() == "":
            return None
        try:
            return float(raw)
        except ValueError:
            return None


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s.strip()[:10]) if s else None


def parse(body: bytes, url: str = "") -> XbrlDoc:
    root = etree.fromstring(body)
    contexts = {}
    for c in root.iter(f"{{{XBRLI}}}context"):
        period = c.find(f"{{{XBRLI}}}period")
        contexts[c.get("id")] = Context(
            id=c.get("id"),
            start=_d(period.findtext(f"{{{XBRLI}}}startDate")),
            end=_d(period.findtext(f"{{{XBRLI}}}endDate")),
            instant=_d(period.findtext(f"{{{XBRLI}}}instant")),
            dimensional=c.find(f".//{{{XBRLI}}}segment") is not None
            or c.find(f".//{{{XBRLI}}}scenario") is not None,
        )
    facts = {}
    for el in root:
        if not isinstance(el.tag, str) or el.get("contextRef") is None:
            continue
        local = etree.QName(el).localname
        facts[(local, el.get("contextRef"))] = (el.text or "").strip()

    def meta_val(tag):
        for (t, _), v in facts.items():
            if t == tag:
                return v
        return None

    meta = {
        "symbol": meta_val("Symbol"),
        "company": meta_val("NameOfTheCompany"),
        "nature": meta_val("NatureOfReportStandaloneConsolidated"),
        "rounding": meta_val("LevelOfRounding") or meta_val("LevelOfRoundingUsedInFinancialStatements"),
        "currency": meta_val("DescriptionOfPresentationCurrency"),
        "reporting_quarter": meta_val("ReportingQuarter"),
        "period_type": meta_val("TypeOfReportingPeriod"),
        "audited": meta_val("WhetherResultsAreAuditedOrUnaudited"),
    }
    tags = {t for t, _ in facts}
    if "InterestExpended" in tags or "BANKING" in url.upper():
        taxonomy = "banking"
    elif "NBFC" in url.upper():
        taxonomy = "nbfc"
    else:
        taxonomy = "indas"
    return XbrlDoc(meta=meta, contexts=contexts, facts=facts, taxonomy=taxonomy)
