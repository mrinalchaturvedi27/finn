"""Version stamps that make up cache keys. Bump the one you change."""
import hashlib

PARSER_VERSION = "xbrl-1"
PDF_RAW_VERSION = "raw-1"  # pdfplumber extract_text after dedupe_chars
PDF_PARSER_VERSION = "norm-3"  # normaliser: OCR digit repair, doubled-OCR collapse
CORROBORATION_VERSION = 2  # page + row label + value + column alignment
EXTRACTION_SCHEMA_VERSION = 1
PROMPT_VERSION = 0  # no LLM in milestone 1
CALC_VERSION = 1
CLASSIFIER_VERSION = 3  # 1: initial rules; 2: fixes from holdout 1; 3: fixes from holdout 2


def cache_key(doc_sha256: str, *, parser: str = PARSER_VERSION) -> str:
    raw = f"{doc_sha256}|{parser}|s{EXTRACTION_SCHEMA_VERSION}|p{PROMPT_VERSION}|c{CALC_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
