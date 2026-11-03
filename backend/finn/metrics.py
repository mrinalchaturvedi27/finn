"""Metric definitions — explicit, versioned, and shown to the user.

Values are in absolute INR as tagged in the XBRL filing. A metric missing an
input produces an `unavailable` reason instead of a silent zero.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDef:
    id: str
    version: int
    label: str
    value_kind: str  # absolute | margin_pct
    kind: str  # reported | calculated
    tags: tuple[str, ...] = ()  # reported: first tag found wins
    formula: str | None = None  # calculated: human-readable
    note: str | None = None


INDUSTRIAL = [
    MetricDef("revenue", 1, "Revenue", "absolute", "reported", ("RevenueFromOperations",)),
    MetricDef("ebitda_op_proxy", 1, "Operating EBITDA (calculated)", "absolute", "calculated",
              formula="Profit before exceptional items & tax + Finance costs + Depreciation & amortisation − Other income",
              note="Not company-reported. Excludes other income and exceptional items; definitions vary by company."),
    MetricDef("pbt", 1, "PBT", "absolute", "reported", ("ProfitBeforeTax",)),
    MetricDef("pat", 1, "PAT", "absolute", "reported", ("ProfitLossForPeriod",),
              note="Consolidated PAT includes non-controlling interests where applicable."),
    MetricDef("ebitda_margin", 1, "Operating EBITDA margin", "margin_pct", "calculated",
              formula="Operating EBITDA (calculated) ÷ Revenue"),
]

BANK = [
    MetricDef("nii", 1, "Net interest income (calculated)", "absolute", "calculated",
              formula="Interest earned − Interest expended"),
    MetricDef("ppop", 1, "Pre-provision operating profit", "absolute", "reported",
              ("OperatingProfitBeforeProvisionAndContingencies",)),
    MetricDef("provisions", 1, "Provisions (ex-tax)", "absolute", "reported",
              ("ProvisionsOtherThanTaxAndContingencies",)),
    MetricDef("pbt", 1, "PBT", "absolute", "reported", ("ProfitLossFromOrdinaryActivitiesBeforeTax",)),
    MetricDef("pat", 1, "PAT", "absolute", "reported",
              ("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates", "ProfitLossForThePeriod")),
]

NBFC = [
    MetricDef("revenue", 1, "Revenue from operations", "absolute", "reported", ("RevenueFromOperations",)),
    MetricDef("nii", 1, "Net interest income (calculated)", "absolute", "calculated",
              formula="Interest earned − Finance costs",
              note="Finance costs are the NBFC's core funding cost; EBITDA is not meaningful for lenders."),
    MetricDef("pbt", 1, "PBT", "absolute", "reported", ("ProfitBeforeTax",)),
    MetricDef("pat", 1, "PAT", "absolute", "reported", ("ProfitLossForPeriod",)),
]

SETS = {"indas": INDUSTRIAL, "banking": BANK, "nbfc": NBFC}


def compute(doc, ctx: str, taxonomy: str) -> dict[str, dict]:
    """Return {metric_id: {value, kind, formula, locator, inputs, reason}} for one period."""
    out: dict[str, dict] = {}
    n = lambda t: doc.num(t, ctx)  # noqa: E731

    for m in SETS[taxonomy]:
        rec = {"def": m, "value": None, "locator": None, "inputs": {}, "reason": None}
        if m.kind == "reported":
            for t in m.tags:
                v = n(t)
                if v is not None:
                    rec.update(value=v, locator=f"{t}@{ctx}")
                    break
            else:
                rec["reason"] = f"Tag {'/'.join(m.tags)} not present in filing"
        else:
            inputs, value = _calc(m.id, n, out)
            rec["inputs"] = inputs
            missing = [k for k, v in inputs.items() if v is None]
            if missing:
                rec["reason"] = "Missing input: " + ", ".join(missing)
            elif value is None:
                rec["reason"] = "Not meaningful (non-positive denominator)"
            else:
                rec["value"] = value
        out[m.id] = rec
    return out


def _calc(mid, n, done):
    if mid == "ebitda_op_proxy":
        i = {"ProfitBeforeExceptionalItemsAndTax": n("ProfitBeforeExceptionalItemsAndTax"),
             "FinanceCosts": n("FinanceCosts"),
             "DepreciationDepletionAndAmortisationExpense": n("DepreciationDepletionAndAmortisationExpense"),
             "OtherIncome": n("OtherIncome")}
        if None in i.values():
            return i, None
        return i, (i["ProfitBeforeExceptionalItemsAndTax"] + i["FinanceCosts"]
                   + i["DepreciationDepletionAndAmortisationExpense"] - i["OtherIncome"])
    if mid == "ebitda_margin":
        e, r = done.get("ebitda_op_proxy", {}).get("value"), done.get("revenue", {}).get("value")
        i = {"ebitda_op_proxy": e, "revenue": r}
        if e is None or r is None:
            return i, None
        return i, (e / r * 100) if r > 0 else None
    if mid == "nii":
        earned = n("InterestEarned")
        cost = n("InterestExpended") if n("InterestExpended") is not None else n("FinanceCosts")
        i = {"InterestEarned": earned, "InterestExpended/FinanceCosts": cost}
        if earned is None or cost is None:
            return i, None
        return i, earned - cost
    raise KeyError(mid)


def change(cur: float | None, base: float | None, value_kind: str = "absolute") -> dict:
    """QoQ / YoY change with explicit not-meaningful states."""
    if cur is None or base is None:
        return {"value": None, "state": "missing"}
    if value_kind == "margin_pct":
        return {"value": cur - base, "state": "ok", "unit": "pp"}
    if base <= 0:
        return {"value": None, "state": "n/m", "why": "base period is zero or negative"}
    if cur < 0:
        return {"value": None, "state": "n/m", "why": "turned to a loss"}
    return {"value": (cur - base) / base * 100, "state": "ok", "unit": "%"}
