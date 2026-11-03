import Link from "next/link";
import type { Change, Freshness } from "@/lib/api";
import { istDate, istTime, pct, toneClass } from "@/lib/format";

export function Delta({ c, className = "", invert = false }: { c: Change | undefined; className?: string; invert?: boolean }) {
  const p = pct(c);
  const tone = invert && (p.tone === "up" || p.tone === "down") ? (p.tone === "up" ? "down" : "up") : p.tone;
  return (
    <span title={p.title} className={`num ${toneClass[tone]} ${className}`}>
      {p.text}
    </span>
  );
}

export function SectionLabel({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mt-7 mb-2 flex items-baseline justify-between px-1">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{children}</h2>
      {right && <div className="text-[11px] text-faint">{right}</div>}
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "warn" | "accent" }) {
  const cls = {
    neutral: "bg-surface-2 text-muted",
    warn: "bg-warn-bg text-warn",
    accent: "bg-surface-2 text-accent",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>;
}

export function SnapshotBanner({ asOf }: { asOf: string }) {
  return (
    <div className="mt-3 rounded-xl border border-warn/30 bg-warn-bg px-3 py-2 text-[12.5px] leading-snug text-warn">
      <span className="font-semibold">Historical snapshot.</span> Filings and prices as captured {istDate(asOf, true)} IST —
      not live.
    </div>
  );
}

export function FreshnessLine({ f, stale }: { f: Freshness; stale?: number }) {
  const ann = f.nse_announcements;
  const pr = f.prices;
  return (
    <div className="mt-2 space-y-0.5 px-1 text-[11.5px] leading-snug text-faint">
      <div>
        Filings: last checked {istDate(ann?.last_checked, true)}
        {ann?.last_status && ann.last_status !== "ok" && <span className="text-warn"> ({ann.last_status})</span>}
        {ann?.overdue && <span className="text-warn"> · overdue</span>} · checks {ann?.cadence}
      </div>
      <div>
        Prices: through {istDate(pr?.data_through)} close · checked {istTime(pr?.last_checked)}
        {pr?.overdue && <span className="text-warn"> · overdue</span>}
        {stale ? <span className="text-warn"> · {stale} stale</span> : null}
      </div>
    </div>
  );
}

export function Spark({ data, w = 64, h = 20 }: { data?: number[]; w?: number; h?: number }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * (h - 2) - 1}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden className={up ? "text-up" : "text-down"}>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function BackLink() {
  return (
    <Link href="/" className="inline-flex items-center gap-1 text-[13px] text-muted active:opacity-60">
      <span aria-hidden>←</span> Brief
    </Link>
  );
}

export function LoadStatus({ state, err, onRetry, what }: {
  state: "loading" | "waking" | "ready" | "error" | "not_found"; err: string | null; onRetry: () => void; what: string;
}) {
  if (state === "not_found")
    return (
      <p role="alert" className="mt-6 rounded-xl border border-line bg-surface p-3 text-[13px] text-muted">
        Couldn’t find {what}. It may not be in this snapshot.
      </p>
    );
  if (state === "waking")
    return (
      <p role="status" className="mt-6 rounded-xl border border-line bg-surface p-3 text-[13px] text-muted">
        Backend waking up… The demo server sleeps when idle and takes about a minute to start. Retrying.
      </p>
    );
  if (state === "error")
    return (
      <div role="alert" className="mt-6 rounded-xl border border-down/30 bg-surface p-3 text-[13px] text-down">
        Couldn’t load {what} ({err}).{" "}
        <button onClick={onRetry} className="underline underline-offset-2">Try again</button>
      </div>
    );
  return null;
}
