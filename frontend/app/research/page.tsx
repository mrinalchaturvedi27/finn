"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SummaryLine } from "@/components/research";
import { BackLink, LoadStatus, SectionLabel } from "@/components/ui";
import { type ResearchIndex, withView } from "@/lib/api";
import { istDate } from "@/lib/format";
import { useMode } from "@/lib/mode";
import { useApi } from "@/lib/useApi";

export default function ResearchPage() {
  const { mode, href } = useMode();
  const { data, state, err, retry } = useApi<ResearchIndex>(withView("/api/research", mode));
  const [sym, setSym] = useState("");
  const router = useRouter();
  const ready = new Set((data?.reports ?? []).map((r) => r.ticker));
  const checkable = (data?.reports ?? []).filter((r) => r.summary && r.summary.delivered + r.summary.partial + r.summary.missed + r.summary.pending > 0);
  const rest = (data?.reports ?? []).filter((r) => !checkable.includes(r));

  return (
    <main className="mx-auto max-w-[760px] px-4 pb-24 pt-3 sm:px-6">
      <BackLink href={href("/")} label={mode === "demo" ? "Demo briefing" : "Briefing"} />
      <div className="kicker mt-3 text-accent">Research{mode === "demo" ? " · demo" : ""}</div>
      <h1 className="serif mt-1 text-[30px] font-semibold leading-tight tracking-tight">Promised vs delivered</h1>
      <p className="mt-1.5 text-[13.5px] leading-snug text-ink-2">
        What management guided on its last five earnings calls, checked against the results it then filed. Only the company’s own
        filings are used. Guidance is extracted by rules, so a statement is scored only when it can be matched to company-level numbers
        for the same period; everything else is listed with the reason.
      </p>

      <form
        className="mt-5 flex items-center gap-2 rounded-xl border border-line bg-surface p-2 shadow-sm"
        onSubmit={(e) => {
          e.preventDefault();
          const t = sym.trim().toUpperCase();
          if (t) router.push(href(`/r/${encodeURIComponent(t)}`));
        }}
      >
        <label htmlFor="sym" className="sr-only">NSE symbol</label>
        <input id="sym" value={sym} onChange={(e) => setSym(e.target.value)} placeholder="Any NSE symbol, e.g. TITAN"
          autoCapitalize="characters" autoCorrect="off" spellCheck={false}
          className="min-h-[44px] min-w-0 flex-1 rounded-md bg-transparent px-3 text-[14px] uppercase placeholder:normal-case placeholder:text-faint" />
        <button className="min-h-[44px] rounded-lg bg-ink px-4 text-[13px] font-semibold text-bg transition-colors hover:bg-accent">Open →</button>
      </form>
      {mode === "demo" && (
        <p className="mt-2 text-[12px] text-muted">The demo has reports for the companies below, generated from real filings on 3 Nov 2026. Switch to Live to research others.</p>
      )}

      {!data && <LoadStatus state={state} err={err} onRetry={retry} what="research" />}

      {data && (
        <>
          {checkable.length > 0 && (
            <>
              <SectionLabel right={`${checkable.length}`}>With a checkable promise</SectionLabel>
              <ul>{checkable.map((r) => <Row key={r.ticker} r={r} href={href(`/r/${r.ticker}#guidance`)} />)}</ul>
            </>
          )}
          <SectionLabel right={rest.length ? `${rest.length}` : undefined}>{checkable.length ? "Other reports" : "Reports"}</SectionLabel>
          {data.reports.length === 0 ? (
            <p className="text-[13px] leading-snug text-muted">
              {data.can_request ? "No reports yet. Open any symbol above to queue one." : "No research reports in this briefing."}
            </p>
          ) : (
            <ul>{rest.map((r) => <Row key={r.ticker} r={r} href={href(`/r/${r.ticker}`)} />)}</ul>
          )}
          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
            <span className="text-faint">Demo set:</span>
            {data.demo.map((t) => (
              <Link key={t} href={href(`/r/${t}`)} className="min-h-[32px] font-semibold underline-offset-4 hover:underline">
                {t}{!ready.has(t) && <span className="font-normal text-faint"> (not ready)</span>}
              </Link>
            ))}
          </div>
          {data.queue.length > 0 && (
            <>
              <SectionLabel>Queued</SectionLabel>
              <ul className="space-y-1 text-[13px] text-muted">
                {data.queue.map((q) => <li key={q.ticker}>{q.ticker} · {q.state} · requested {istDate(q.requested_at, true)}</li>)}
              </ul>
              {data.schedule && <p className="mt-1 text-[11.5px] text-faint">Runs when the worker next runs ({data.schedule}).</p>}
            </>
          )}
        </>
      )}
    </main>
  );
}

function Row({ r, href }: { r: ResearchIndex["reports"][number]; href: string }) {
  return (
    <li>
      <Link href={href} className="group grid min-h-[72px] grid-cols-[1fr_auto] items-center gap-x-3 border-b border-line py-4 transition-colors hover:bg-surface-2">
        <span className="min-w-0">
          <span className="kicker text-ink">{r.ticker}</span> <span className="text-[12.5px] text-muted">{r.company}</span>
          {r.summary && <span className="mt-1 block"><SummaryLine s={r.summary} /></span>}
        </span>
        <span className="flex flex-col items-end gap-1"><span className="num text-[10.5px] text-faint">{istDate(r.finished_at)}</span><span className="text-lg text-accent transition-transform group-hover:translate-x-1" aria-hidden>↗</span></span>
      </Link>
    </li>
  );
}
