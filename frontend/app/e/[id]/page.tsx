"use client";

import { use } from "react";
import { BackLink, LoadStatus, Pill, SectionLabel } from "@/components/ui";
import { ResultsView } from "@/components/results";
import { type EventDetail } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { CATEGORY_LABEL, istDate } from "@/lib/format";

export default function EventPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: e, state, err, retry } = useApi<EventDetail>(`/api/events/${id}`);

  return (
    <main className="mx-auto max-w-[560px] px-4 pb-24 pt-5">
      <BackLink />
      <LoadStatus state={state} err={err} onRetry={retry} what="this event" />
      {e && (
        <>
          <div className="mt-4 flex items-center gap-2 text-[12px] text-muted">
            <span className="font-semibold text-ink">{e.ticker}</span>
            <span>·</span>
            <span className="truncate">{e.company}</span>
          </div>
          <h1 className="mt-1 text-[21px] font-semibold leading-tight tracking-tight">{e.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Pill>{CATEGORY_LABEL[e.category] ?? e.category}</Pill>
            {e.read_state === "unread" && <Pill tone="warn">unread</Pill>}
            <span className="text-[12px] text-faint">{istDate(e.occurred_at, true)} IST</span>
          </div>

          {e.results && e.results.status !== "failed" ? (
            <ResultsView card={e.results} />
          ) : (
            <GenericBody e={e} />
          )}

          <SectionLabel right={e.duplicates_hidden ? `${e.duplicates_hidden} duplicate hidden` : undefined}>
            Source filings
          </SectionLabel>
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
            {e.filings.map((f) => (
              <li key={f.id} className="px-4 py-3">
                <div className="flex items-center gap-2 text-[11px] text-faint">
                  <span>{f.exchange}</span>
                  <span>·</span>
                  <span>{istDate(f.filed_at, true)}</span>
                  {f.is_primary && <Pill>primary</Pill>}
                </div>
                <div className="mt-0.5 text-[13.5px] font-medium">{f.subject}</div>
                {f.text && <p className="mt-0.5 line-clamp-3 text-[12.5px] leading-snug text-muted">{f.text}</p>}
                {f.url && (
                  <a href={f.url} target="_blank" rel="noreferrer" className="mt-1.5 inline-block text-[12.5px] font-medium text-accent">
                    Open filing ↗
                  </a>
                )}
              </li>
            ))}
          </ul>

          <p className="mt-5 px-1 text-[11.5px] leading-snug text-faint">
            Why this is ranked here: {e.reasons.join("; ")} · priority {e.materiality}/100.
          </p>
        </>
      )}
    </main>
  );
}

function GenericBody({ e }: { e: EventDetail }) {
  if (e.results?.status === "failed") {
    return (
      <div className="mt-5 rounded-2xl border border-warn/30 bg-warn-bg p-4 text-[13px] leading-snug text-warn">
        Results numbers unavailable: {e.results.problems.join("; ")}. The original filing is linked below.
      </div>
    );
  }
  return (
    <div className="mt-5 space-y-3">
      {e.summary && <p className="text-[14.5px] leading-relaxed">{e.summary}</p>}
      {e.read_state === "unread" && (
        <div className="rounded-2xl border border-warn/30 bg-warn-bg p-4 text-[13px] leading-snug text-warn">
          The exchange metadata doesn’t say what this filing is about, so FINN hasn’t judged it. It’s kept mid-priority until
          it’s read — open the filing below.
        </div>
      )}
    </div>
  );
}
