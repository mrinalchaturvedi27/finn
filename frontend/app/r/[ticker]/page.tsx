"use client";

import { use, useState } from "react";
import { BackLink, LoadStatus, SectionLabel } from "@/components/ui";
import { NotCheckable, PromiseCard, Sources, SummaryStrip, Trajectory } from "@/components/research";
import { ApiError, post, type ResearchResponse, withView } from "@/lib/api";
import { istDate, monthYear, shortName } from "@/lib/format";
import { useMode } from "@/lib/mode";
import { useApi } from "@/lib/useApi";

export default function ReportPage({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = use(params);
  const t = decodeURIComponent(ticker).toUpperCase();
  const { mode, href } = useMode();
  const { data, state, err, retry } = useApi<ResearchResponse>(withView(`/api/research/${encodeURIComponent(t)}`, mode));
  const notResearched = state === "not_found";
  const r = data?.report;
  const items = r?.guidance ?? [];
  const checkable = items.filter((g) => g.verdict.status !== "not_comparable");
  const other = items.filter((g) => g.verdict.status === "not_comparable");
  const calls = r?.sources.transcripts.filter((s) => s.status === "read") ?? [];

  return (
    <main className="mx-auto max-w-[760px] px-4 pb-24 pt-3 sm:px-6">
      <BackLink href={href("/research")} label="Research" />
      <div className="mt-3 flex items-center gap-2 text-[11px]">
        <span className="kicker text-accent">Promised vs delivered</span>
        <span className="kicker text-ink">{t}</span>
      </div>
      <h1 className="serif mt-1 text-[28px] font-semibold leading-tight tracking-tight sm:text-[32px]">{r?.company ? shortName(r.company) : t}</h1>

      {!data && state !== "not_found" && <LoadStatus state={state} err={err} onRetry={retry} what="this report" />}
      {(notResearched || (data && !r)) && <NotYet t={t} data={data} onQueued={retry} demo={mode === "demo"} />}

      {r && (
        <>
          <p className="mt-1 text-[12px] leading-snug text-faint">
            {calls.length} earnings call{calls.length === 1 ? "" : "s"}
            {calls.length > 0 && ` (${monthYear(calls[calls.length - 1].call_date)} – ${monthYear(calls[0].call_date)})`} and{" "}
            {r.sources.xbrl.length} quarterly results filings · {r.financials?.basis} · rules v{r.rules_version} · read{" "}
            {istDate(r.generated_at, true)}
          </p>
          {r.summary && (
            <div className="mt-3">
              <SummaryStrip s={r.summary} />
            </div>
          )}

          <SectionLabel id="guidance" right={`${checkable.length} checkable`}>What they said, what happened</SectionLabel>
          {checkable.length ? (
            <ul>
              {checkable.map((g, i) => (
                <PromiseCard key={i} g={g} />
              ))}
            </ul>
          ) : (
            <p className="text-[13.5px] leading-snug text-muted">
              {items.length
                ? "Management’s numeric statements on these calls can’t be checked against company-level results (see below)."
                : `No explicit numeric guidance on revenue, margins, profit, volumes or capex in ${calls.length} call${calls.length === 1 ? "" : "s"}: management spoke in qualitative terms.`}
            </p>
          )}
          <NotCheckable items={other} />
          <p className="mt-2 px-1 text-[11px] leading-snug text-faint">
            Guidance is extracted by rules from management’s answers only (not analysts’ questions); each item links to the page
            it came from. Verdicts allow 1 percentage point on growth and 0.5 on margins.
          </p>

          <Trajectory r={r} />
          <Sources r={r} />
        </>
      )}
    </main>
  );
}

function NotYet({ t, data, onQueued, demo }: { t: string; data: ResearchResponse | null; onQueued: () => void; demo: boolean }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (demo) {
    return (
      <p className="mt-4 border-l-2 border-line pl-3 text-[13.5px] leading-snug text-muted">
        {t} isn’t in the demo set. Switch to Live (top of the briefing) to queue research on any NSE company.
      </p>
    );
  }
  if (data?.pending) {
    return (
      <p className="mt-4 border-l-2 border-line pl-3 text-[13.5px] leading-snug text-muted">
        Queued {istDate(data.pending.requested_at, true)}. FINN reads {t}’s filings on the worker’s next run (hourly, best effort);
        this page fills in then.
      </p>
    );
  }
  return (
    <div className="mt-4 border-l-2 border-line pl-3 text-[13.5px] leading-snug text-muted">
      {data?.failed ? (
        <>
          <p className="text-down">The last attempt could not build a report:</p>
          <ul className="mt-1 list-disc pl-4 text-[12px]">
            {data.failed.failures.slice(0, 3).map((f, i) => (
              <li key={i}>{f.error}</li>
            ))}
          </ul>
        </>
      ) : (
        <p>{t} hasn’t been researched yet.</p>
      )}
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const r = await post<{ message: string }>(`/api/research/${encodeURIComponent(t)}`);
            setMsg(r.message === "already queued" ? "Already queued." : "Queued.");
            onQueued();
          } catch (e) {
            setMsg(e instanceof ApiError && e.status === 503 ? "Research needs the live database; this deployment is showing the snapshot." : `Couldn’t queue it (${e instanceof Error ? e.message : e}).`);
          } finally {
            setBusy(false);
          }
        }}
        className="mt-3 min-h-[44px] bg-ink px-4 text-[13.5px] font-semibold text-bg disabled:opacity-50"
      >
        Research {t}
      </button>
      {msg && <p className="mt-2 text-[12px]">{msg}</p>}
    </div>
  );
}
