"""Rule-based classification (category) and materiality (priority) — kept separate.

Category answers "what kind of filing is this"; materiality answers "how much
should the investor care". An unclassified or opaque filing is never
automatically low priority: if the metadata is too thin to judge, it is marked
`unread` and given a middle score so it surfaces until something reads it.

Rule coverage is a hypothesis; measure it with probe/label_sample.py.
"""
import re
from dataclasses import dataclass, field

BOILERPLATE = re.compile(
    r"^.*?\b(has (informed|submitted to|intimated) the exchange|has submitted the exchange)\s*"
    r"(about|regarding|that|,)?\s*(a |the )?", re.I)

SUBJECT_MAP = {
    "financial result updates": "results", "integrated filing- financial": "results",
    "credit rating": "credit_rating", "credit rating- new": "credit_rating", "credit rating- revision": "credit_rating",
    "credit rating- others": "credit_rating",
    "change in management": "management_change", "resignation of director/kmp/smp": "management_change",
    "appointment": "management_change", "resignation": "management_change", "cessation": "management_change",
    "change in director(s)": "management_change", "retirement": "management_change", "demise": "management_change",
    "acquisition": "M&A", "scheme of arrangement": "M&A", "sale or disposal": "M&A", "other restructuring": "M&A",
    "amalgamation / merger": "M&A", "agreements": "M&A",
    "corporate insolvency resolution process": "litigation", "action(s) taken or orders passed": "litigation",
    "disclosure of material issue": "litigation", "litigation": "litigation",
    "qualified institutional placement": "fund_raise", "preferential issue": "fund_raise",
    "issue of securities": "fund_raise", "rights issue": "fund_raise", "buyback": "fund_raise",
    "dividend": "dividend", "record date": "dividend",
    "bonus": "bonus_split", "split": "bonus_split",
    "trading plan under pit": "insider_trading", "insider trading": "insider_trading",
    "commencement of commercial production/operations": "capex", "capacity addition": "capex",
    "bagging/receiving of orders/contracts": "press_release", "news verification": "press_release",
    "rumour verification - regulation 30(11)": "press_release", "clarification": "press_release",
    "esop/esos/esps": "unclassified", "allotment of securities": "unclassified", "trading window": "unclassified",
    "certificate under sebi (depositories and participants) regulations, 2018": "unclassified",
    "address change": "unclassified", "monitoring agency report": "unclassified",
    "statement of deviation(s) or variation(s) under reg. 32": "unclassified",
    "committee meeting updates": "unclassified", "amendment to aoa/moa": "unclassified",
    "change in auditors": "unclassified", "options to purchase securities": "unclassified",
    "giving guarantees/indemnity/ becoming a surety for third party": "unclassified",
    "pledge": "pledging", "creation of pledge": "pledging", "release of pledge": "pledging",
}

RESULTS_TXT = re.compile(r"financial results?|unaudited.*results|audited.*results", re.I)
RESULTS_INTIMATION = re.compile(r"to consider|to announce|will be held|is scheduled|intimation of board meeting|"
                                r"results on|prior intimation", re.I)
CALL_TXT = re.compile(r"transcript|recording|audio|earnings call|conference call|con\.? ?call|webcast", re.I)
TRANSCRIPT = re.compile(r"transcript", re.I)

TEXT_RULES = [  # applied to opaque subjects ("General Updates", "Updates", board outcomes)
    (re.compile(r"transcript|earnings call|conference call", re.I), "earnings_call"),
    (re.compile(r"investor (conference|meet)|analyst", re.I), "investor_meetings"),
    (re.compile(r"\bfines?\b|penalt|show cause|demand order|\bgst\b|income tax|nclt|nclat|\bcourt\b|"
                r"tribunal|adjudication|sebi order|regulatory action|search|investigation", re.I), "litigation"),
    (re.compile(r"acqui|merger|amalgamat|demerger|joint venture|\bstake\b|takeover|divest|incorporat\w* .{0,30}subsidiary", re.I), "M&A"),
    (re.compile(r"\bqip\b|preferential|rights issue|buy-?back|non-convertible|debentures|commercial paper|"
                r"raising of funds|fund rais", re.I), "fund_raise"),
    (re.compile(r"dividend", re.I), "dividend"),
    (re.compile(r"bonus|sub-?division|stock split", re.I), "bonus_split"),
    (re.compile(r"appoint|resign|cessation|re-?designat|retire", re.I), "management_change"),
    (re.compile(r"credit rating", re.I), "credit_rating"),
    (re.compile(r"capex|capacity|new plant|facility|expansion|commenc", re.I), "capex"),
    (re.compile(r"pledge", re.I), "pledging"),
    (re.compile(r"order|contract|launch|approv|partnership|collaborat|announces", re.I), "press_release"),
    (re.compile(r"esop|stock option|restricted stock|\brsu\b|newspaper|dematerial|physical shares|auditor|"
                r"annual securities report|kanto|loss of share certificate|duplicate share", re.I), "unclassified"),
]

OPAQUE = re.compile(r"^(general updates|updates|disclosure under regulation 30.*|intimation under .*regulations,? 2015"
                    r"|credit rating|corporate insolvency resolution process|action\(s\) taken or orders passed)\.?$",
                    re.I)

CXO = re.compile(r"\b(ceo|cfo|coo|cto|md\b|managing director|chief executive|chief financial|whole[- ]time director|"
                 r"(?<!non-)(?<!non- )(?<!non )executive director|chairman|chairperson|company secretary)", re.I)


@dataclass
class Classification:
    category: str
    source: str  # rule | rule_weak | none
    materiality: int
    read_state: str  # read | unread
    reasons: list = field(default_factory=list)
    subkind: str | None = None  # e.g. results_outcome, results_intimation, transcript
    summary: str = ""


def clean_text(text: str | None) -> str:
    t = BOILERPLATE.sub("", (text or "").strip()).strip(" .'\"")
    return t[:1].upper() + t[1:] if t else ""


def classify(subject: str, text: str | None) -> Classification:
    subj = (subject or "").strip().lower()
    body = text or ""
    summary = clean_text(body)
    cat, src, sub = None, "rule", None

    if subj in ("outcome of board meeting", "copy of newspaper publication", "investor presentation", "press release"):
        if RESULTS_TXT.search(body) or subj == "investor presentation":
            cat = "results"
            sub = {"outcome of board meeting": "results_outcome", "copy of newspaper publication": "results_newspaper",
                   "investor presentation": "results_deck", "press release": "results_press"}[subj]
        elif subj == "press release":
            cat = "press_release"
        elif subj == "copy of newspaper publication":
            cat, sub = "unclassified", "newspaper"
    if cat is None and subj == "analysts/institutional investor meet/con. call updates":
        if CALL_TXT.search(body):
            cat = "earnings_call"
            sub = "transcript" if TRANSCRIPT.search(body) else "call_logistics"
        else:
            cat = "investor_meetings"
    if cat is None and subj == "shareholders meeting":
        cat = "postal_ballot" if "postal ballot" in body.lower() else "agm_egm"
    if cat is None and subj in SUBJECT_MAP:
        cat = SUBJECT_MAP[subj]
    if cat == "management_change" and re.search(r"auditor", body, re.I):
        cat, sub = "unclassified", "auditor"  # auditor appointments are routine per the reference taxonomy
    if cat == "results" and sub is None:
        sub = "results_outcome"
    if cat is None or subj in ("general updates", "updates", "outcome of board meeting"):
        if RESULTS_TXT.search(body) and RESULTS_INTIMATION.search(body):
            cat, sub = "results", "results_intimation"
        elif cat is None or cat == "unclassified":
            for rx, c in TEXT_RULES:
                if rx.search(body):
                    cat, src = c, "rule_weak"
                    break
    if cat is None:
        cat, src = "unclassified", "none"
    if cat == "earnings_call" and sub is None:
        sub = "transcript" if TRANSCRIPT.search(body) else "call_logistics"

    opaque = bool(OPAQUE.match(summary or subj)) or len(summary) < 12
    if cat in ("results", "earnings_call", "investor_meetings", "agm_egm", "postal_ballot", "dividend"):
        opaque = False  # the subject alone tells us what it is
    m, reasons = materiality(cat, sub, subj, body, opaque)
    return Classification(cat, src, m, "unread" if opaque else "read", reasons, sub, summary or subject)


def materiality(cat, sub, subj, body, opaque) -> tuple[int, list[str]]:
    low = body.lower()
    if cat == "results":
        score = {"results_outcome": 85, "results_press": 60, "results_deck": 45,
                 "results_newspaper": 10, "results_intimation": 25}.get(sub, 60)
        return score, [f"results:{sub}"]
    if cat == "management_change":
        if CXO.search(body) or CXO.search(subj):
            return (80 if re.search(r"resign|cessation|demise|retire", low + subj) else 70), ["top-management role"]
        if re.search(r"independent director", low):
            return 40, ["independent director"]
        return (55 if opaque else 40), ["management change" + (" (role not stated)" if opaque else "")]
    if cat == "credit_rating":
        if re.search(r"downgrad|negative|watch with negative", low):
            return 80, ["rating downgrade/negative outlook"]
        if re.search(r"upgrad|positive", low):
            return 55, ["rating upgrade"]
        if re.search(r"reaffirm", low):
            return 20, ["rating reaffirmed"]
        return 40, ["rating action, direction not in metadata"]
    if cat == "litigation":
        return (60 if not opaque else 55), ["legal/regulatory matter"]
    if cat == "M&A":
        if re.search(r"incorporat", low) and not re.search(r"acqui|merger|takeover|demerger", low):
            return 35, ["new subsidiary incorporated"]
        return (70 if re.search(r"acqui|merger|scheme|takeover|\bstake\b|demerger", low + subj) else 55), ["corporate action"]
    if cat == "fund_raise":
        return (70 if re.search(r"qip|qualified institutional|preferential|rights|buy-?back", low + subj) else 40), ["capital raise"]
    if cat == "pledging":
        return 65, ["promoter pledge change"]
    if cat == "insider_trading":
        return 45, ["insider dealing"]
    if cat == "bonus_split":
        return 55, ["share count change"]
    if cat == "capex":
        return 55, ["capacity / capex"]
    if cat == "dividend":
        return 35, ["dividend"]
    if cat == "press_release":
        if re.search(r"order|contract", low + subj):
            return 50, ["order win"]
        if re.search(r"approv|usfda|launch", low):
            return 45, ["approval / launch"]
        return 25, ["general news"]
    if cat == "earnings_call":
        return (35 if sub == "transcript" else 12), [sub or "call"]
    if cat in ("investor_meetings", "postal_ballot", "agm_egm"):
        return 12, [cat]
    # unclassified: routine if we recognised it, otherwise unread-middle
    if opaque:
        return 40, ["unread: metadata too thin to judge"]
    return 10, ["routine paperwork"]


def tier(score: int) -> str:
    return "top" if score >= 65 else "look" if score >= 35 else "routine"
