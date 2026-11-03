import type { Change } from "./api";

/** INR absolute -> "₹49,244 cr" (Indian grouping, crores). */
export function crore(v: number | null | undefined, dp?: number): string {
  if (v == null) return "—";
  const cr = v / 1e7;
  const digits = dp ?? (Math.abs(cr) >= 1000 ? 0 : Math.abs(cr) >= 100 ? 1 : 2);
  return `₹${cr.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits })} cr`;
}

export function pct(c: Change | undefined, dp = 1): { text: string; tone: "up" | "down" | "flat" | "na"; title?: string } {
  if (!c || c.state === "missing") return { text: "—", tone: "na", title: "Comparable period not available" };
  if (c.state === "n/m") return { text: "n/m", tone: "na", title: c.why ?? "Not meaningful" };
  const v = c.value ?? 0;
  const unit = c.unit === "pp" ? "pp" : "%";
  const arrow = v > 0.05 ? "▲" : v < -0.05 ? "▼" : "";
  return {
    text: `${arrow}${Math.abs(v).toFixed(dp)}${unit}`,
    tone: v > 0.05 ? "up" : v < -0.05 ? "down" : "flat",
  };
}

export const toneClass = { up: "text-up", down: "text-down", flat: "text-muted", na: "text-faint" } as const;

const IST: Intl.DateTimeFormatOptions = { timeZone: "Asia/Kolkata" };

/** Backend timestamps are naive IST. */
function asIst(iso: string): Date {
  if (iso.length === 10) return new Date(`${iso}T00:00:00+05:30`);
  return new Date(/[zZ+]/.test(iso.slice(10)) ? iso : `${iso}+05:30`);
}

export function istTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return asIst(iso).toLocaleTimeString("en-IN", { ...IST, hour: "2-digit", minute: "2-digit", hour12: false });
}

export function istDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "—";
  const d = asIst(iso);
  const date = d.toLocaleDateString("en-IN", { ...IST, day: "numeric", month: "short" });
  return withTime ? `${date}, ${istTime(iso)}` : date;
}

export function ago(iso: string, now: string): string {
  const mins = Math.round((asIst(now).getTime() - asIst(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 1)}m`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

export const CATEGORY_LABEL: Record<string, string> = {
  results: "Results",
  "M&A": "M&A",
  fund_raise: "Fund raise",
  management_change: "Management",
  litigation: "Legal / regulatory",
  insider_trading: "Insider",
  earnings_call: "Earnings call",
  investor_meetings: "Investor meet",
  credit_rating: "Credit rating",
  dividend: "Dividend",
  bonus_split: "Bonus / split",
  capex: "Capex",
  press_release: "News",
  postal_ballot: "Postal ballot",
  agm_egm: "AGM / EGM",
  pledging: "Pledge",
  unclassified: "Other",
};
