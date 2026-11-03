"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { BackLink, LoadStatus, SectionLabel } from "@/components/ui";
import { SummaryLine } from "@/components/research";
import { type ResearchIndex } from "@/lib/api";
import { istDate } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function ResearchPage() {
  const { data, state, err, retry } = useApi<ResearchIndex>("/api/research");
  const [sym, setSym] = useState("");
  const router = useRouter();
  const ready = new Set((data?.reports ?? []).map((r) => r.ticker));

  return (
    <main className="mx-auto max-w-[560px] px-4 pb-24 pt-5">
      <BackLink />
      <h1 className="mt-4 text-[21px] font-semibold tracking-tight">Promised vs delivered</h1>
      <p className="mt-1 text-[13px] leading-snug text-muted">
        What management guided on its last earnings calls, checked against the results it then filed. Only the company’s own
        filings are used: call transcripts and quarterly XBRL results.
      </p>

      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const t = sym.trim().toUpperCase();
          if (t) router.push(`/r/${encodeURIComponent(t)}`);
        }}
      >
        <input
          value={sym}
          onChange={(e) => setSym(e.target.value)}
          placeholder="Any NSE symbol, e.g. TITAN"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          aria-label="NSE symbol"
          className="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-[14px] uppercase placeholder:normal-case placeholder:text-faint"
        />
        <button className="rounded-xl bg-ink px-4 py-2 text-[14px] font-medium text-bg">Open</button>
      </form>

      <LoadStatus state={state} err={err} onRetry={retry} what="research" />

      {data && (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {data.demo.map((t) => (
              <Link key={t} href={`/r/${t}`} className="rounded-full border border-line bg-surface px-3 py-1 text-[12.5px] text-muted">
                {t}
                {!ready.has(t) && <span className="text-faint"> · not ready</span>}
              </Link>
            ))}
          </div>

          <SectionLabel right={data.reports.length ? `${data.reports.length}` : undefined}>Ready</SectionLabel>
          {data.reports.length === 0 ? (
            <p className="rounded-2xl border border-line bg-surface p-4 text-[13px] text-muted">
              {data.can_request
                ? "No reports yet. The worker researches the demo companies on its next run."
                : "This deployment is showing the historical snapshot, which has no research reports. Research runs against the live database."}
            </p>
          ) : (
            <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
              {data.reports.map((r) => (
                <li key={r.ticker}>
                  <Link href={`/r/${r.ticker}`} className="block px-4 py-3">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[14px] font-semibold">{r.ticker}</span>
                      <span className="text-[11.5px] text-faint">{istDate(r.finished_at)}</span>
                    </div>
                    <div className="truncate text-[12px] text-muted">{r.company}</div>
                    {r.summary && (
                      <div className="mt-1.5">
                        <SummaryLine s={r.summary} />
                      </div>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          )}

          {data.queue.length > 0 && (
            <>
              <SectionLabel>Queued</SectionLabel>
              <ul className="space-y-1 px-1 text-[13px] text-muted">
                {data.queue.map((q) => (
                  <li key={q.ticker}>
                    {q.ticker} · {q.state} · requested {istDate(q.requested_at, true)}
                  </li>
                ))}
              </ul>
              {data.schedule && <p className="mt-1 px-1 text-[11.5px] text-faint">Runs when the {data.schedule}.</p>}
            </>
          )}
        </>
      )}
    </main>
  );
}
