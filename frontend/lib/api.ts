export const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

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
  alerts_since?: string | null;
  totals: { events: number; filings: number };
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
  reporting_format: string | null;
  filings: { id: number; subject: string; text: string | null; filed_at: string; url: string | null; exchange: string; category: string; category_source: string; is_primary: boolean }[];
  duplicates_hidden: number;
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
