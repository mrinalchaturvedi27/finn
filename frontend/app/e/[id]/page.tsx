"use client";

import Link from "next/link";
import { use } from "react";
import { SummaryLine } from "@/components/research";
import { ResultsView } from "@/components/results";
import { BackLink, LoadStatus, SectionLabel } from "@/components/ui";
import { type EventDetail, withView } from "@/lib/api";
import { CATEGORY_LABEL, fullDate, istDate, shortName } from "@/lib/format";
import { useMode } from "@/lib/mode";
import { useApi } from "@/lib/useApi";

export default function EventPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { mode, href } = useMode();
  const { data: e, state, err, retry } = useApi<EventDetail>(withView(`/api/events/${id}`, mode));

  return (
    <main className="mx-auto max-w-[760px] px-4 pb-24 pt-3 sm:px-6">
      <BackLink href={href("/")} label={mode === "demo" ? "Demo briefing" : "Briefing"} />
      {!e && <LoadStatus state={state} err={err} onRetry={retry} what="this event" />}
      {e && (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-x-2 text-[11px]">
            <span className="kicker text-accent">{CATEGORY_LABEL[e.category] ?? e.category}</span>
            <span className="kicker text-ink">{e.ticker}</span>
            <span className="text-faint">· {e.company}</span>
          </div>
          <h1 className="serif mt-1.5 text-[28px] font-semibold leading-[1.12] tracking-tight sm:text-[34px]">
            {e.category === "results" ? `${shortName(e.company, e.ticker)}: ${e.title}` : e.title}
          </h1>
          <p className="mt-2 text-[12.5px] text-muted">
            Filed {istDate(e.occurred_at, true)} IST · {e.filings.length} filing{e.filings.length === 1 ? "" : "s"}
            {e.read_state === "unread" && <span className="text-warn"> · not described in the exchange metadata</span>}
          </p>

          {e.results && e.results.status !== "failed" ? <ResultsView card={e.results} /> : <GenericBody e={e} />}

          <DigIn e={e} href={href} />

          <SectionLabel right={e.duplicates_hidden ? `${e.duplicates_hidden} duplicate hidden` : undefined}>Source filings</SectionLabel>
          {(e.later_filings_hidden ?? 0) > 0 && (
            <p className="mb-1 text-[12px] text-faint">
              {e.later_filings_hidden} later filing{e.later_filings_hidden === 1 ? "" : "s"} hidden: filed after the demo’s reference date.
            </p>
          )}
          <ul>
            {e.filings.map((f) => (
              <li key={f.id} className="border-b border-line py-3 last:border-b-0">
                <div className="flex items-center gap-2 text-[11px] text-faint">
                  <span className="kicker">{f.exchange}</span>
                  <span className="num">{istDate(f.filed_at, true)}</span>
                  {f.is_primary && <span className="font-semibold text-ink">· primary</span>}
                </div>
                <div className="mt-0.5 text-[14px] font-semibold">{f.subject}</div>
                {f.text && <p className="mt-0.5 line-clamp-3 text-[13px] leading-snug text-muted">{f.text}</p>}
                {f.url && (
                  <a href={f.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex min-h-[40px] items-center text-[13px] font-semibold text-accent underline-offset-4 hover:underline">
                    Open the filing (PDF) ↗
                  </a>
                )}
              </li>
            ))}
          </ul>

          <p className="mt-5 text-[12px] leading-snug text-faint">
            Why it ranks here: {e.reasons.map(reasonText).join("; ")} · priority {e.materiality} of 100.
          </p>
        </>
      )}
    </main>
  );
}

function DigIn({ e, href }: { e: EventDetail; href: (p: string) => string }) {
  const r = e.research;
  return (
    <section className="mt-6 border-l-2 border-accent bg-surface px-4 py-3">
      <div className="kicker text-accent">Dig in</div>
      {r ? (
        <>
          <p className="serif mt-1 text-[17px] font-semibold leading-snug">What {shortName(e.company, e.ticker)} promised, and what it delivered</p>
          {r.summary && (
            <div className="mt-1.5">
              <SummaryLine s={r.summary} />
            </div>
          )}
          <Link href={href(`/r/${e.ticker}#guidance`)} className="mt-1 inline-flex min-h-[40px] items-center text-[13.5px] font-semibold text-accent underline-offset-4 hover:underline">
            Guidance, actuals and source quotes →
          </Link>
          {r.generated_at && <span className="ml-2 text-[11.5px] text-faint">report of {fullDate(r.generated_at)}</span>}
        </>
      ) : (
        <>
          <p className="mt-1 text-[13.5px] leading-snug text-muted">
            No promised-vs-delivered report for {e.ticker} in this briefing yet.
          </p>
          <Link href={href(`/r/${e.ticker}`)} className="inline-flex min-h-[40px] items-center text-[13.5px] font-semibold text-accent underline-offset-4 hover:underline">
            Research {e.ticker} →
          </Link>
        </>
      )}
    </section>
  );
}

const REASON: Record<string, string> = {
  "results:results_outcome": "results outcome filed",
  "results:results_outcome (same-day board outcome)": "board outcome on results day",
  "results:results_press": "results press release",
  "results:results_deck": "investor deck",
  "results:results_newspaper": "newspaper notice of results",
  "results:results_intimation": "results date announced",
};

function reasonText(r: string) {
  return REASON[r] ?? r;
}

function GenericBody({ e }: { e: EventDetail }) {
  if (e.results?.status === "failed") {
    return (
      <p className="mt-5 border-l-2 border-warn pl-3 text-[13.5px] leading-snug text-warn">
        Results numbers unavailable: {e.results.problems.join("; ")}. The original filing is linked below.
      </p>
    );
  }
  return (
    <div className="mt-5 space-y-3">
      {e.summary && <p className="serif text-[18px] leading-relaxed text-ink-2">{e.summary}</p>}
      {e.read_state === "unread" && (
        <p className="border-l-2 border-warn pl-3 text-[13px] leading-snug text-warn">
          The exchange metadata doesn’t say what this filing is about, so FINN hasn’t judged it. It stays mid-priority until it’s
          read: open the filing below.
        </p>
      )}
    </div>
  );
}
