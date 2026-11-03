"use client";

import Link from "next/link";
import { useState } from "react";
import type { BriefEvent, Change, Mover, Spotlight } from "@/lib/api";
import { CATEGORY_LABEL, ago, crore, croreNum, fullDate, istDate, shortName } from "@/lib/format";
import type { Prefs } from "@/lib/prefs";
import { VERDICT } from "./research";
import { Delta, SectionLabel, Spark } from "./ui";

/* ---------- evaluation with this browser's preferences ---------- */

export type Move = Mover & { price: boolean; volume: boolean };

/** Re-evaluate every evaluated stock against this browser's thresholds (the server's own
 * flags use the server defaults). Stale stocks are never evaluated. */
export function evaluateMoves(rows: Mover[], p: Prefs): { flagged: Move[]; quiet: Move[] } {
  const all = rows
    .filter((m) => m.state === "ok")
    .map((m) => ({
      ...m,
      price: m.change_pct != null && Math.abs(m.change_pct) >= p.price_pct,
      volume: m.volume_ratio != null && m.volume_ratio >= p.volume_multiple,
    }));
  const flagged = all.filter((m) => m.price || m.volume).sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0));
  return { flagged, quiet: all.filter((m) => !m.price && !m.volume) };
}

/** A filing in a category this browser follows. Counted as an alert only in the top tier (the
 * stories); worth-a-look lines get a quiet mark so routine-ish litigation notes don't shout. */
export const followed = (e: BriefEvent, p: Prefs) => e.tier !== "routine" && p.alert_categories.includes(e.category);
export const alerting = (e: BriefEvent, p: Prefs) => e.tier === "top" && followed(e, p);

/* ---------- reading the numbers (facts only, no invented commentary) ---------- */

function yoyOf(e: BriefEvent, id: string): Change | undefined {
  return e.results_headline?.find((h) => h.id === id)?.yoy;
}

/** "Revenue +28.6%; PAT +33.8% YoY": the figures, not an interpretation of them. */
function pattern(e: BriefEvent): string | null {
  const fmt = (label: string, c: Change | undefined) =>
    c?.state === "ok" && c.value != null ? `${label} ${c.value >= 0 ? "+" : "−"}${Math.abs(c.value).toFixed(1)}%` : null;
  const parts = [fmt(yoyOf(e, "nii") ? "NII" : "Revenue", yoyOf(e, "revenue") ?? yoyOf(e, "nii")), fmt("PAT", yoyOf(e, "pat"))].filter(Boolean);
  return parts.length ? `${parts.join("; ")} YoY.` : null;
}

const BUNDLE: Record<string, string> = {
  "results:results_press": "press release",
  "results:results_deck": "investor deck",
  "results:results_newspaper": "newspaper notice",
};

function why(e: BriefEvent): string {
  if (e.category === "results") {
    const extra = e.reasons.map((r) => BUNDLE[r]).filter(Boolean);
    return `Quarterly results filed${extra.length ? `, with ${extra.join(", ")}` : ""}.`;
  }
  const r = e.reasons.filter((x) => !x.startsWith("results:"));
  return r.length ? r[0].charAt(0).toUpperCase() + r[0].slice(1) + "." : "";
}

function MoveNote({ m }: { m: Move }) {
  const chg = m.change_pct ?? 0;
  return (
    <p className="mt-2 text-[12px] leading-snug text-muted" title="Shown alongside the filing; FINN does not claim one caused the other.">
      <span className="font-medium text-ink">Also on {istDate(m.session)}:</span> the stock{" "}
      <span className={`num font-medium ${chg >= 0 ? "text-up" : "text-down"}`}>
        {chg >= 0 ? "▲" : "▼"}
        {Math.abs(chg).toFixed(1)}%
      </span>
      {m.volume_ratio != null && <span className="num">, {m.volume_ratio.toFixed(1)}× usual volume</span>}. Shown alongside, not attributed.
    </p>
  );
}

function Kicker({ e, asOf, alert }: { e: BriefEvent; asOf: string; alert?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      {alert && (
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" title="Alert: a type you follow">
          <span className="sr-only">Alert:</span>
        </span>
      )}
      <span className="kicker text-accent">{CATEGORY_LABEL[e.category] ?? e.category}</span>
      <span className="kicker text-ink">{e.ticker}</span>
      <span className="num ml-auto text-faint">{ago(e.occurred_at, asOf)} ago</span>
    </div>
  );
}

/* ---------- lead story ---------- */

export function LeadStory({ e, asOf, move, alert, href }: { e: BriefEvent; asOf: string; move?: Move; alert?: boolean; href: string }) {
  const nums = e.results_headline ?? [];
  const pat = pattern(e);
  return (
    <article className="mt-5">
      <Kicker e={e} asOf={asOf} alert={alert} />
      <Link href={href} className="group block">
        <h2 className="serif mt-1.5 text-[28px] font-semibold leading-[1.1] tracking-tight group-hover:underline group-hover:decoration-1 group-hover:underline-offset-4 sm:text-[36px]">
          {e.category === "results" ? `${shortName(e.company, e.ticker)}: ${e.title}` : e.title}
        </h2>
      </Link>
      {nums.length > 0 ? (
        <dl className="mt-4 grid grid-cols-3 border-y border-line">
          {nums.map((h, i) => (
            <div key={h.id} className={`min-w-0 py-3 ${i ? "border-l border-line pl-2.5 sm:pl-4" : "pr-2.5"}`}>
              <dt className="truncate text-[11px] text-faint">{h.label.replace("Operating ", "")} <span className="sm:hidden">₹cr</span><span className="hidden sm:inline">₹ crore</span></dt>
              <dd className="num serif mt-0.5 text-[18px] font-semibold leading-tight sm:text-[26px]">{croreNum(h.value)}</dd>
              <dd className="num mt-1 text-[11.5px] text-faint">
                <Delta c={h.yoy} className="font-semibold" /> YoY
              </dd>
              <dd className="num text-[11.5px] text-faint">
                <Delta c={h.qoq} /> QoQ
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        e.summary && <p className="serif mt-3 text-[17px] leading-snug text-ink-2">{e.summary}</p>
      )}
      <p className="mt-3 text-[13.5px] leading-snug text-ink-2">
        <span className="font-semibold">Why it’s here:</span> {why(e)} {pat}
      </p>
      {move && <MoveNote m={move} />}
      <Link href={href} className="mt-3 inline-flex min-h-[40px] items-center text-[13.5px] font-semibold text-accent underline-offset-4 hover:underline">
        {e.has_detail ? "Read the results and evidence →" : "Open the filing →"}
      </Link>
    </article>
  );
}

/* ---------- secondary stories: denser, still with the key number ---------- */

export function StoryRow({ e, asOf, move, alert, href }: { e: BriefEvent; asOf: string; move?: Move; alert?: boolean; href: string }) {
  const rev = e.results_headline?.find((h) => h.id === "revenue" || h.id === "nii");
  const pat = e.results_headline?.find((h) => h.id === "pat");
  return (
    <li className="border-b border-line py-3.5 last:border-b-0">
      <Kicker e={e} asOf={asOf} alert={alert} />
      <Link href={href} className="group mt-1 block">
        <h3 className="serif line-clamp-2 text-[18px] font-semibold leading-snug group-hover:underline group-hover:underline-offset-2">
          {e.category === "results" ? `${shortName(e.company, e.ticker)}: ${e.title}` : e.title}
        </h3>
        {rev || pat ? (
          <p className="num mt-1 text-[13px] text-muted">
            {rev && (
              <>
                {rev.label} {crore(rev.value)} <Delta c={rev.yoy} className="font-semibold" />
              </>
            )}
            {rev && pat && <span className="text-faint"> · </span>}
            {pat && (
              <>
                PAT {crore(pat.value)} <Delta c={pat.yoy} className="font-semibold" />
              </>
            )}
            <span className="text-faint"> YoY</span>
          </p>
        ) : (
          e.summary && e.summary !== e.title && <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-muted">{e.summary}</p>
        )}
      </Link>
      {move && <MoveNote m={move} />}
    </li>
  );
}

/* ---------- worth a look: one line each ---------- */

export function BriefLine({ e, asOf, href }: { e: BriefEvent; asOf: string; href: string }) {
  return (
    <li>
      <Link href={href} className="grid min-h-[44px] grid-cols-[88px_1fr_auto] items-baseline gap-x-3 border-b border-line py-2.5 hover:bg-surface-2">
        <span className="kicker break-all text-[10.5px] text-ink">{e.ticker}</span>
        <span className="min-w-0">
          <span className="line-clamp-2 text-[13.5px] leading-snug">{e.title}</span>
          <span className="text-[11.5px] text-faint">
            {CATEGORY_LABEL[e.category] ?? e.category}
            {e.read_state === "unread" && <span className="text-warn"> · not described in the filing</span>}
          </span>
        </span>
        <span className="num text-[11.5px] text-faint">{ago(e.occurred_at, asOf)}</span>
      </Link>
    </li>
  );
}

export function Routine({ items, asOf, hrefFor }: { items: BriefEvent[]; asOf: string; hrefFor: (e: BriefEvent) => string }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  const kinds = [...new Set(items.map((e) => CATEGORY_LABEL[e.category] ?? e.category))].slice(0, 3).join(", ").toLowerCase();
  return (
    <section className="mt-6">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex min-h-[44px] w-full items-center justify-between border-y border-dashed border-line text-left text-[13px] text-muted hover:text-ink"
      >
        <span>
          <span className="font-semibold text-ink">{items.length}</span> routine filing{items.length > 1 ? "s" : ""} ({kinds})
        </span>
        <span>{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <ul className="opacity-80">
          {items.map((e) => (
            <BriefLine key={e.id} e={e} asOf={asOf} href={hrefFor(e)} />
          ))}
        </ul>
      )}
    </section>
  );
}

/* ---------- unusual moves (this browser's thresholds) ---------- */

export function Moves({ flagged, stale, session, prefs, custom, prefsHref }: {
  flagged: Move[]; stale: Mover[]; session: string | null; prefs: Prefs; custom: boolean; prefsHref: string;
}) {
  return (
    <section>
      <SectionLabel right={session ? `${istDate(session)} session` : undefined}>Unusual moves</SectionLabel>
      {flagged.length === 0 ? (
        <p className="text-[13px] text-muted">No portfolio stock moved past ±{prefs.price_pct}% or {prefs.volume_multiple}× usual volume.</p>
      ) : (
        <table className="num w-full text-[13px] sm:max-w-[460px] lg:max-w-none">
          <caption className="sr-only">Stocks past your price or volume lines</caption>
          <thead>
            <tr className="text-[11px] text-faint">
              <th scope="col" className="pb-1 text-left font-medium">Stock</th>
              <th scope="col" className="pb-1 text-right font-medium">Price</th>
              <th scope="col" className="pb-1 pl-3 text-right font-medium">Volume</th>
              <th scope="col" className="pb-1 pl-3 text-right font-medium">20 sessions</th>
            </tr>
          </thead>
          <tbody>
            {flagged.map((m) => {
              const chg = m.change_pct ?? 0;
              return (
                <tr key={m.ticker} className="border-b border-line">
                  <th scope="row" className="kicker py-2 pr-2 text-left text-ink">{m.ticker}</th>
                  <td className={`py-2 text-right ${m.price ? "font-semibold" : ""} ${chg >= 0 ? "text-up" : "text-down"}`}>
                    {chg >= 0 ? "▲" : "▼"}
                    {Math.abs(chg).toFixed(1)}%
                  </td>
                  <td className={`py-2 pl-3 text-right ${m.volume ? "font-semibold text-ink" : "text-faint"}`}>
                    {m.volume_ratio != null ? `${m.volume_ratio.toFixed(1)}×` : "—"}
                  </td>
                  <td className="py-2 pl-3 text-right">
                    <Spark data={m.spark} w={56} h={18} neutral />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-[11.5px] leading-snug text-faint">
        Close-to-close change and volume vs the previous 20 sessions. Your lines: ±{prefs.price_pct}%, {prefs.volume_multiple}×
        {custom ? " (set in this browser)" : " (defaults)"} ·{" "}
        <Link href={prefsHref} className="underline underline-offset-2">change</Link>
        {stale.length > 0 && <span className="text-warn"> · not evaluated (no bar): {stale.map((m) => m.ticker).join(", ")}</span>}
      </p>
    </section>
  );
}

/* ---------- promised vs delivered, inside the brief ---------- */

export function SpotlightBlock({ s, href, indexHref }: { s: Spotlight | null | undefined; href: string; indexHref: string }) {
  if (!s) {
    return (
      <section>
        <SectionLabel>Promised vs delivered</SectionLabel>
        <p className="text-[13px] leading-snug text-muted">
          No checkable guidance in this briefing’s research yet.{" "}
          <Link href={indexHref} className="font-semibold text-accent underline-offset-2 hover:underline">Research a company →</Link>
        </p>
      </section>
    );
  }
  const v = s.item.verdict;
  return (
    <section>
      <SectionLabel right={s.generated_at ? `report of ${fullDate(s.generated_at)}` : undefined}>Promised vs delivered</SectionLabel>
      <div className="kicker text-ink">{s.ticker} <span className="font-normal normal-case tracking-normal text-faint">· {s.company}</span></div>
      <p className="serif mt-1 text-[17px] leading-snug">
        Guided {s.item.metric_label.toLowerCase()} of <span className="num font-semibold">{s.item.target}</span>{" "}
        <span className="text-muted">({s.item.period_label})</span>
      </p>
      <p className="mt-1 text-[13px]">
        <span className={`rounded-sm px-1.5 py-0.5 text-[11.5px] font-semibold ${VERDICT[v.status].cls}`}>{VERDICT[v.status].label}</span>{" "}
        <span className="text-muted">{v.calc ?? v.reason}</span>
      </p>
      <blockquote className="serif mt-2 border-l-2 border-accent pl-3 text-[14px] italic leading-snug text-ink-2">
        “{s.item.quote.length > 160 ? s.item.quote.slice(0, 160) + "…" : s.item.quote}”
        <footer className="mt-0.5 font-sans text-[11.5px] not-italic text-faint">{s.item.speaker}, earnings call {fullDate(s.item.stated_on)}</footer>
      </blockquote>
      <Link href={href} className="mt-2 inline-flex min-h-[40px] items-center text-[13.5px] font-semibold text-accent underline-offset-4 hover:underline">
        Dig in: quote, calculation, source page →
      </Link>
    </section>
  );
}
