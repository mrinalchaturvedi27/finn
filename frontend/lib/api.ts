export const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** Every read carries the briefing it belongs to (the demo reads the bundled snapshot). */
export function withView(path: string, view: string) {
  return `${path}${path.includes("?") ? "&" : "?"}view=${view}`;
}

export type Change = { value: number | null; state: "ok" | "n/m" | "missing"; unit?: string; why?: string };

export type Freshness = Record<
  string,
  {
    cadence: string;
    last_checked: string | null;
    last_status: string | null;
    last_success: string | null;
    data_through: string | null;
    mode: string | null;
    errors: { ticker?: string; error?: string }[];
    overdue?: boolean;
  }
>;

export type BriefEvent = {
  id: number;
  ticker: string;
  company: string;
  sector: string | null;
  category: string;
  title: string;
  summary: string | null;
  occurred_at: string;
  materiality: number;
  tier: "top" | "look" | "routine";
  reasons: string[];
  read_state: "read" | "unread";
  filings: number;
  has_detail: boolean;
  results_headline: { id: string; label: string; value: number; yoy: Change; qoq: Change }[] | null;
};

export type Mover = {
  ticker: string;
  session: string | null;
  state: "ok" | "stale";
  close?: number;
  change_pct?: number;
  volume_ratio?: number | null;
  alerts: { kind: "price" | "volume"; observed: number; threshold: number }[];
  last_session?: string | null;
  why?: string;
  spark?: number[];
};

export type Brief = {
  as_of: string;
  mode: "snapshot" | "live";
  window: string;
  since: string;
  freshness: Freshness;
  tiers: { top: BriefEvent[]; look: BriefEvent[]; routine: BriefEvent[] };
  movers: { session: string | null; triggered: Mover[]; quiet: Mover[]; stale: Mover[] };
  settings: Settings;
  alerts?: AlertItem[];
  data_source?: "live" | "seed" | "seed_fallback";
  view?: "demo" | "live";
  reference?: { as_of: string; label: string; captured_at: string | null } | null;
  spotlight?: Spotlight | null;
  alerts_since?: string | null;
  totals: { events: number; filings: number };
};

export type Spotlight = {
  ticker: string;
  company: string | null;
  generated_at: string | null;
  summary: ResearchSummary | null;
  item: Pick<GuidanceItem, "metric_label" | "period_label" | "target" | "quote" | "page" | "speaker" | "stated_on" | "source_url" | "verdict">;
};

export type AlertItem = {
  id: number;
  ticker: string;
  kind: "announcement" | "price" | "volume";
  event_id: number | null;
  session: string | null;
  observed: number | null;
  threshold: number | null;
  title: string | null;
  category: string | null;
  change_pct: number | null;
  created_at: string | null;
};

export type Settings = {
  volume_multiple: number;
  price_pct: number;
  eod_buffer_min: number;
  alert_categories: string[];
  read_only?: boolean;
};

export type Check = { check: string; ok: boolean; detail: string };

export type MetricRow = {
  id: string;
  label: string;
  value_kind: "absolute" | "margin_pct";
  calculation_kind: "reported" | "calculated";
  formula: string | null;
  note: string | null;
  current: number | null;
  prev_q: number | null;
  yoy_q: number | null;
  prev_q_change: Change;
  yoy_q_change: Change;
  verification_status: "primary_verified" | "secondary_only" | "unavailable";
  unavailable_reason: string | null;
  locator: string | null;
  pdf_page: number | null;
  pdf_match?: string | null;
  inputs: Record<string, number | null>;
  input_pages?: Record<string, number | null>;
  input_alignment?: Record<string, { by: string; column_offset: number } | null>;
  definition?: { xbrl_concept: string | null; status: "unchecked" | "matches_print" | "differs_from_print"; comparable_with: string; excluded_from?: string };
  corroboration?: {
    status: "aligned" | "column_unconfirmed" | "definition_differs" | "not_located" | "no_pdf";
    page?: number;
    match?: string;
    raw?: string | null;
    aligned?: { by: "prev_q" | "yoy_q"; column_offset: number } | null;
    next_tokens?: string[];
    printed_label?: string;
    printed_value?: string;
  };
};

export type ResultsCard = {
  ticker: string;
  quarter_end: string;
  label: string;
  status: "ok" | "partial" | "failed";
  problems: string[];
  basis?: string;
  taxonomy?: "indas" | "banking" | "nbfc";
  rounding?: string;
  statement_page?: number | null;
  periods: Record<string, { quarter_end: string; label: string; xbrl_url: string; filed: string; revisions_superseded: number; audited?: string; checks?: Check[] }>;
  metrics: MetricRow[];
  pdf: null | { url: string; subject: string; filed: string; n_pages: number; text_pages: number; checks: Check[]; rejected?: boolean; statement_page_repairs?: string[] };
};

export type EventDetail = BriefEvent & {
  research?: { ticker: string; summary: ResearchSummary | null; generated_at: string | null } | null;
  reporting_format: string | null;
  filings: { id: number; subject: string; text: string | null; filed_at: string; url: string | null; exchange: string; category: string; category_source: string; is_primary: boolean }[];
  duplicates_hidden: number;
  later_filings_hidden?: number;
  results: ResultsCard | null;
};

export class ApiError extends Error {
  constructor(public status: number | null, message: string) {
    super(message);
  }
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${API}${path}`, { cache: "no-store", signal });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ApiError(null, "network error"); // also what a CORS rejection looks like
  }
  if (!r.ok) throw new ApiError(r.status, `${r.status} ${path}`);
  return r.json();
}

// The free backend sleeps when idle and takes about a minute to start. Retry for a bounded
// time and report "waking"; only give up (error state) once the budget is spent.
const WAKE_BUDGET_MS = 100_000;
const ATTEMPT_TIMEOUT_MS = 30_000;
const SLOW_MS = 3_000;
const RETRYABLE = new Set([502, 503, 504]);

export async function getWaking<T>(path: string, onWaking: () => void, signal: AbortSignal): Promise<T> {
  const t0 = Date.now();
  const slow = setTimeout(onWaking, SLOW_MS);
  try {
    for (let attempt = 0; ; attempt++) {
      const ctl = new AbortController();
      const abort = () => ctl.abort();
      signal.addEventListener("abort", abort);
      const timer = setTimeout(abort, ATTEMPT_TIMEOUT_MS);
      try {
        return await get<T>(path, ctl.signal);
      } catch (e) {
        if (signal.aborted) throw e;
        const retryable = !(e instanceof ApiError) || e.status === null || RETRYABLE.has(e.status);
        if (!retryable || Date.now() - t0 > WAKE_BUDGET_MS) {
          throw e instanceof ApiError ? e : new ApiError(null, "timed out");
        }
        onWaking();
        await new Promise((ok) => setTimeout(ok, Math.min(2000 * 2 ** attempt, 8000)));
      } finally {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
      }
    }
  } finally {
    clearTimeout(slow);
  }
}

export async function put<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export async function post<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { method: "POST" });
  if (!r.ok) {
    let detail = `${r.status}`;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {}
    throw new ApiError(r.status, detail);
  }
  return r.json();
}

// ---------- research (pull) ----------

export type Verdict = {
  status: "delivered" | "partial" | "missed" | "pending" | "not_comparable";
  value?: number | null;
  calc?: string;
  reason?: string | null;
  tracking?: string | null;
  run_rate?: boolean;
  tolerance_pp?: number;
  quarters?: string[];
};

export type GuidanceItem = {
  metric: string;
  metric_label: string;
  direction: "range" | "at_least" | "at_most" | "point";
  low: number | null;
  high: number | null;
  unit: "pct" | "crore";
  period_type: string;
  period_label: string;
  target: string;
  quote: string;
  page: number;
  speaker: string;
  stated_on: string;
  source_url: string;
  notes: string[];
  revisions: { stated_on: string; target: string; quote: string; page: number; source_url: string }[];
  reiterated_on?: string[];
  verdict: Verdict;
};

export type ResearchSummary = {
  delivered: number;
  partial: number;
  missed: number;
  pending: number;
  not_comparable: number;
  statements: number;
  calls_read: number;
  calls_found: number;
};

export type ResearchReport = {
  ticker: string;
  company: string | null;
  generated_at: string;
  status: "done" | "partial" | "failed";
  rules_version: number;
  financials?: {
    basis: string;
    taxonomy: "indas" | "banking" | "nbfc" | null;
    quarters: { quarter_end: string; label: string; xbrl_url: string; values: Record<string, number | null> }[];
  };
  sources: {
    transcripts: { call_date: string; url?: string; nse_url: string; source?: string; pages?: number; status: string; statements?: number }[];
    xbrl: { quarter: string; url: string }[];
  };
  guidance?: GuidanceItem[];
  summary?: ResearchSummary;
  failures: { stage: string; error?: string; call_date?: string; quarter_end?: string }[];
};

export type ResearchRow = {
  ticker: string;
  company: string | null;
  state: string;
  finished_at: string | null;
  requested_at: string | null;
  summary: ResearchSummary | null;
  requested_via: string | null;
};

export type ResearchIndex = { reports: ResearchRow[]; queue: ResearchRow[]; demo: string[]; can_request: boolean; schedule: string | null };

export type ResearchResponse = {
  ticker: string;
  report: ResearchReport | null;
  pending: ResearchRow | null;
  failed: (ResearchRow & { failures: { stage: string; error?: string }[] }) | null;
  can_request: boolean;
};
