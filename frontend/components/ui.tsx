import Link from "next/link";
import type { Change, Freshness } from "@/lib/api";
import { istDate, istTime, pct, toneClass } from "@/lib/format";
import type { Mode } from "@/lib/mode";

export function Delta({ c, className = "", invert = false }: { c: Change | undefined; className?: string; invert?: boolean }) {
  const p = pct(c);
  const tone = invert && (p.tone === "up" || p.tone === "down") ? (p.tone === "up" ? "down" : "up") : p.tone;
  return (
    <span title={p.title} className={`num ${toneClass[tone]} ${className}`}>
      {p.text}
    </span>
  );
}

/** Section head: serif label over a hairline, optional right-hand note. */
export function SectionLabel({ children, right, id }: { children: React.ReactNode; right?: React.ReactNode; id?: string }) {
  return (
    <div id={id} className="mb-2 mt-8 flex scroll-mt-4 items-baseline justify-between gap-3 border-b border-rule pb-1.5">
      <h2 className="serif text-[17px] font-semibold leading-none tracking-tight">{children}</h2>
      {right && <div className="text-right text-[11.5px] text-faint">{right}</div>}
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "warn" | "accent" }) {
  const cls = { neutral: "bg-surface-2 text-muted", warn: "bg-warn-bg text-warn", accent: "bg-accent-bg text-accent" }[tone];
  return <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>;
}

export function Masthead({ dateline, href, right }: { dateline: string; href: (p: string) => string; right?: React.ReactNode }) {
  return (
    <header className="border-b-2 border-rule pb-2">
      <div className="flex items-end justify-between gap-3">
        <Link href={href("/")} className="serif text-[34px] font-bold leading-none tracking-tight">
          FINN
        </Link>
        <nav className="flex items-center gap-4 text-[13px] font-medium" aria-label="Sections">
          <Link href={href("/research")} className="py-2 underline-offset-4 hover:underline">
            Research
          </Link>
          <Link href={href("/settings")} className="py-2 underline-offset-4 hover:underline">
            Preferences
          </Link>
        </nav>
      </div>
      <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-3 text-[12px] text-muted">
        <span className="serif text-[13.5px] italic">{dateline}</span>
        {right}
      </div>
    </header>
  );
}

export function ModeSwitch({ mode, setMode }: { mode: Mode; setMode: (m: Mode) => void }) {
  const opt = (m: Mode, label: string) => (
    <button
      role="tab"
      aria-selected={mode === m}
      onClick={() => setMode(m)}
      className={`min-h-[40px] flex-1 px-3 text-[13px] font-medium transition-colors ${
        mode === m ? "bg-ink text-bg" : "text-muted hover:text-ink"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div role="tablist" aria-label="Briefing" className="mt-3 flex overflow-hidden rounded-md border border-rule sm:inline-flex sm:w-[340px]">
      {opt("demo", "Demo briefing")}
      {opt("live", "Live")}
    </div>
  );
}

type Health = "ok" | "stale" | "fail" | "historical";

/** One-line status (data age, failures, stale prices) that opens into the details. */
export function StatusBar({ f, stale, mode, source, scheduleNote, asOf }: {
  f: Freshness; stale: string[]; mode: string; source?: string; scheduleNote?: string; asOf: string;
}) {
  const ann = f.nse_announcements;
  const pr = f.prices;
  const failures = Object.values(f).flatMap((s) => (s.errors ?? []).filter((e) => e.error)).length;
  const historical = mode === "demo" || mode === "snapshot";
  const health: Health = failures ? "fail" : ann?.overdue || pr?.overdue ? "stale" : historical ? "historical" : "ok";
  const dot = { ok: "bg-up", stale: "bg-warn", fail: "bg-down", historical: "bg-faint" }[health];
  const lead = {
    ok: "Data current",
    stale: "Data is stale",
    fail: `${failures} source failure${failures > 1 ? "s" : ""}`,
    historical: mode === "demo" ? "Recorded data" : "Snapshot, not live",
  }[health];
  return (
    <details className="group mt-3 border-y border-line text-[12.5px]">
      <summary className="flex min-h-[40px] cursor-pointer items-center gap-2 py-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden />
        <span className="font-medium">{lead}</span>
        <span className="min-w-0 flex-1 truncate text-muted">
          {mode === "demo"
            ? ` · recorded ${istDate(ann?.last_success)} · shown as of ${istDate(asOf, true)}`
            : ` · filings ${ann?.last_success ? istDate(ann.last_success, true) : "never"} · prices to ${istDate(pr?.data_through)}`}
          {stale.length ? ` · ${stale.length} stale` : ""}
        </span>
        <span className="text-faint group-open:rotate-90" aria-hidden>›</span>
      </summary>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 pb-3 pl-4 text-[12px] text-muted">
        {mode === "demo" && (
          <>
            <dt className="text-faint">Shown as of</dt>
            <dd>{istDate(asOf, true)} IST. Times on this page are relative to it; nothing filed later is shown.</dd>
            <dt className="text-faint">Recorded</dt>
            <dd>filings captured {istDate(ann?.last_success, true)}, prices through {istDate(pr?.data_through)} (later dates are hidden)</dd>
          </>
        )}
        {mode !== "demo" && <dt className="text-faint">Filings</dt>}
        {mode !== "demo" && (
        <dd>
          last successful check {istDate(ann?.last_success, true)}
          {ann?.last_status && !["ok", "running"].includes(ann.last_status) && (
            <span className="text-warn"> · last attempt {ann.last_status} {istTime(ann.last_checked)}</span>
          )}
          {ann?.overdue && <span className="text-warn"> · overdue</span>}
        </dd>
        )}
        {mode !== "demo" && <dt className="text-faint">Prices</dt>}
        {mode !== "demo" && (
          <dd>
            through the {istDate(pr?.data_through)} close
            {pr?.overdue && <span className="text-warn"> · overdue</span>}
          </dd>
        )}
        {stale.length > 0 && (
          <>
            <dt className="text-faint">Not evaluated</dt>
            <dd className="text-warn">{stale.join(", ")} (no bar for the session)</dd>
          </>
        )}
        <dt className="text-faint">Updates</dt>
        <dd>{mode === "live" ? scheduleNote || ann?.cadence : "none: this is recorded data"}</dd>
        {source === "seed_fallback" && (
          <>
            <dt className="text-faint">Database</dt>
            <dd className="text-warn">live database unavailable, showing the recorded snapshot</dd>
          </>
        )}
        {failures > 0 && (
          <>
            <dt className="text-faint">Failures</dt>
            <dd className="text-down">
              {Object.values(f)
                .flatMap((s) => s.errors ?? [])
                .filter((e) => e.error)
                .slice(0, 4)
                .map((e, i) => (
                  <div key={i}>
                    {e.ticker ? `${e.ticker}: ` : ""}
                    {e.error}
                  </div>
                ))}
            </dd>
          </>
        )}
      </dl>
    </details>
  );
}

export function WindowTabs({ value, onChange }: { value: string; onChange: (w: string) => void }) {
  const opts = [["24h", "24 hours"], ["3d", "3 days"], ["7d", "7 days"], ["30d", "30 days"]] as const;
  return (
    <div role="tablist" aria-label="Time window" className="mt-2 flex gap-5 text-[13px]">
      {opts.map(([k, label]) => (
        <button
          key={k}
          role="tab"
          aria-selected={value === k}
          onClick={() => onChange(k)}
          className={`min-h-[40px] border-b-2 ${value === k ? "border-accent font-semibold text-ink" : "border-transparent text-muted hover:text-ink"}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function Spark({ data, w = 64, h = 20, neutral = false }: { data?: number[]; w?: number; h?: number; neutral?: boolean }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * (h - 2) - 1}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden className={neutral ? "text-ink-2" : up ? "text-up" : "text-down"}>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function BackLink({ href = "/", label = "Briefing" }: { href?: string; label?: string }) {
  return (
    <Link href={href} className="inline-flex min-h-[40px] items-center gap-1 text-[13px] font-medium text-muted hover:text-ink">
      ← {label}
    </Link>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-hidden className="mt-6 animate-pulse space-y-3 motion-reduce:animate-none">
      <div className="h-3 w-24 rounded bg-surface-2" />
      <div className="h-6 w-4/5 rounded bg-surface-2" />
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-3 rounded bg-surface-2" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function LoadStatus({ state, err, onRetry, what }: {
  state: "loading" | "waking" | "ready" | "error" | "not_found"; err: string | null; onRetry: () => void; what: string;
}) {
  if (state === "loading") return <Skeleton />;
  if (state === "not_found")
    return (
      <p role="alert" className="mt-6 border-l-2 border-line pl-3 text-[13px] text-muted">
        Couldn’t find {what}. It may not be in this briefing.
      </p>
    );
  if (state === "waking")
    return (
      <div role="status" className="mt-6 border-l-2 border-warn pl-3 text-[13px] text-muted">
        <p className="font-medium text-ink">Backend waking up…</p>
        <p>The demo server sleeps when idle and takes about a minute to start. Retrying.</p>
      </div>
    );
  if (state === "error")
    return (
      <div role="alert" className="mt-6 border-l-2 border-down pl-3 text-[13px] text-down">
        Couldn’t load {what} ({err}).{" "}
        <button onClick={onRetry} className="min-h-[40px] font-medium underline underline-offset-2">
          Try again
        </button>
      </div>
    );
  return null;
}
