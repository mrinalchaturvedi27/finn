"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FreshnessLine, LoadStatus, Pill, SectionLabel, SnapshotBanner, Spark, Delta } from "@/components/ui";
import { Alerts } from "@/components/alerts";
import { type Brief, type BriefEvent, type Mover } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { CATEGORY_LABEL, ago, istDate } from "@/lib/format";

const WINDOWS = [
  ["24h", "24h"],
  ["3d", "3 days"],
  ["7d", "7 days"],
  ["30d", "30 days"],
] as const;

export default function BriefPage() {
  const [win, setWin] = useState<string>("24h");
  const [showRoutine, setShowRoutine] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("finn.window");
      if (saved) setWin(saved);
    } catch {}
  }, []);

  const { data, state, err, retry } = useApi<Brief>(`/api/brief?window=${win}`);

  useEffect(() => {
    try {
      localStorage.setItem("finn.window", win);
    } catch {}
  }, [win]);

  const moverByTicker = new Map((data?.movers.triggered ?? []).map((m) => [m.ticker, m]));

  return (
    <main className="mx-auto max-w-[560px] px-4 pb-24 pt-5">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">FINN</h1>
          <p className="text-[12.5px] text-muted">
            {data ? `${istDate(data.as_of)} · ${data.totals.filings} filings, ${data.totals.events} events` : "Loading brief…"}
          </p>
        </div>
        <Link href="/settings" className="rounded-full border border-line bg-surface px-3 py-1.5 text-[12px] text-muted">
          Thresholds
        </Link>
      </header>

      {data?.data_source === "seed_fallback" && (
        <p role="alert" className="mt-4 rounded-xl border border-warn/40 bg-warn-bg px-3 py-2 text-[12.5px] text-warn">
          Live data is unavailable right now, so this is the historical snapshot instead.
        </p>
      )}
      {data?.mode === "snapshot" && <SnapshotBanner asOf={data.as_of} />}

      <nav className="mt-4 flex gap-1.5" aria-label="Time window">
        {WINDOWS.map(([k, label]) => (
          <button
            key={k}
            onClick={() => setWin(k)}
            className={`rounded-full px-3 py-1.5 text-[13px] transition ${
              win === k ? "bg-ink text-bg" : "border border-line bg-surface text-muted"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      <LoadStatus state={state} err={err} onRetry={retry} what="the brief" />

      {data && (
        <>
          <FreshnessLine f={data.freshness} stale={data.movers.stale.length} />
          <Alerts alerts={data.alerts ?? []} asOf={data.as_of} session={data.movers.session} />
          <Movers data={data} />

          <SectionLabel right={data.tiers.top.length ? `${data.tiers.top.length}` : undefined}>What matters</SectionLabel>
          {data.tiers.top.length === 0 ? (
            <QuietState win={win} brief={data} onWiden={() => setWin(win === "24h" ? "7d" : "30d")} />
          ) : (
            <div className="space-y-2.5">
              {data.tiers.top.map((e) => (
                <TopCard key={e.id} e={e} asOf={data.as_of} mover={moverByTicker.get(e.ticker)} />
              ))}
            </div>
          )}

          {data.tiers.look.length > 0 && (
            <>
              <SectionLabel right={`${data.tiers.look.length}`}>Worth a look</SectionLabel>
              <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
                {data.tiers.look.map((e) => (
                  <Row key={e.id} e={e} asOf={data.as_of} />
                ))}
              </ul>
            </>
          )}

          {data.tiers.routine.length > 0 && (
            <>
              <button
                onClick={() => setShowRoutine((v) => !v)}
                className="mt-6 flex w-full items-center justify-between rounded-2xl border border-dashed border-line px-4 py-3 text-[13px] text-muted"
              >
                <span>
                  {data.tiers.routine.length} routine filing{data.tiers.routine.length > 1 ? "s" : ""} — meetings, compliance,
                  call logistics
                </span>
                <span aria-hidden>{showRoutine ? "▾" : "▸"}</span>
              </button>
              {showRoutine && (
                <ul className="mt-2 divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
                  {data.tiers.routine.map((e) => (
                    <Row key={e.id} e={e} asOf={data.as_of} dim />
                  ))}
                </ul>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}

function Movers({ data }: { data: Brief }) {
  const { triggered, stale, session } = data.movers;
  const s = data.settings;
  return (
    <>
      <SectionLabel right={`±${s.price_pct}% · ${s.volume_multiple}× vol`}>
        Crossed your thresholds{session ? ` · ${istDate(session)}` : ""}
      </SectionLabel>
      <div className="rounded-2xl border border-line bg-surface">
        {triggered.length === 0 ? (
          <p className="px-4 py-3 text-[13px] text-muted">No portfolio stock crossed your price or volume thresholds.</p>
        ) : (
          <ul className="divide-y divide-line">
            {triggered.map((m) => (
              <MoverRow key={m.ticker} m={m} />
            ))}
          </ul>
        )}
        {stale.length > 0 && (
          <p className="border-t border-line px-4 py-2 text-[11.5px] leading-snug text-warn">
            Not evaluated (no {istDate(session)} bar): {stale.map((m) => m.ticker).join(", ")}
          </p>
        )}
      </div>
    </>
  );
}

function MoverRow({ m }: { m: Mover }) {
  const price = m.alerts.find((a) => a.kind === "price");
  const vol = m.alerts.find((a) => a.kind === "volume");
  const chg = m.change_pct ?? 0;
  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      <span className="w-[92px] shrink-0 text-[13.5px] font-medium">{m.ticker}</span>
      <span className={`num w-[64px] text-[13.5px] ${price ? "font-semibold" : ""} ${chg >= 0 ? "text-up" : "text-down"}`}>
        {chg >= 0 ? "▲" : "▼"}
        {Math.abs(chg).toFixed(1)}%
      </span>
      <span className={`num flex-1 text-[12.5px] ${vol ? "font-semibold text-ink" : "text-faint"}`}>
        {m.volume_ratio != null ? `${m.volume_ratio.toFixed(1)}× vol` : "vol n/a"}
      </span>
      <Spark data={m.spark} />
    </li>
  );
}

function TopCard({ e, asOf, mover }: { e: BriefEvent; asOf: string; mover?: Mover }) {
  const body = (
    <article className="rounded-2xl border border-line bg-surface p-4 active:bg-surface-2">
      <div className="flex items-center gap-2 text-[11.5px] text-muted">
        <span className="font-semibold text-ink">{e.ticker}</span>
        <span>·</span>
        <span>{CATEGORY_LABEL[e.category] ?? e.category}</span>
        <span className="ml-auto num text-faint">{ago(e.occurred_at, asOf)}</span>
      </div>
      <h3 className="mt-1 line-clamp-3 text-[15.5px] font-medium leading-snug">{e.title}</h3>
      {e.results_headline ? (
        <div className="mt-3 grid grid-cols-3 gap-2">
          {e.results_headline.map((h) => (
            <div key={h.id}>
              <div className="text-[11px] text-faint">{h.label}</div>
              <Delta c={h.yoy} className="text-[16px] font-semibold" />
              <div className="text-[10.5px] text-faint">YoY</div>
            </div>
          ))}
        </div>
      ) : (
        e.summary && <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-muted">{e.summary}</p>
      )}
      {mover && (
        <div className="mt-3 flex flex-wrap gap-1.5" title="Shown alongside the filing; FINN does not claim one caused the other.">
          <Pill tone="accent">
            Also flagged {istDate(mover.session)}: {(mover.change_pct ?? 0) >= 0 ? "▲" : "▼"}
            {Math.abs(mover.change_pct ?? 0).toFixed(1)}%
            {mover.volume_ratio ? `, ${mover.volume_ratio.toFixed(1)}× volume` : ""}
          </Pill>
        </div>
      )}
    </article>
  );
  return <Link href={`/e/${e.id}`}>{body}</Link>;
}

function Row({ e, asOf, dim }: { e: BriefEvent; asOf: string; dim?: boolean }) {
  return (
    <li>
      <Link href={`/e/${e.id}`} className="flex items-start gap-3 px-4 py-3 active:bg-surface-2">
        <span className={`w-[84px] shrink-0 pt-px text-[12.5px] font-medium ${dim ? "text-muted" : ""}`}>{e.ticker}</span>
        <span className="min-w-0 flex-1">
          <span className={`line-clamp-2 text-[13.5px] leading-snug ${dim ? "text-muted" : ""}`}>{e.title}</span>
          <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-faint">
            {CATEGORY_LABEL[e.category] ?? e.category}
            {e.read_state === "unread" && <Pill tone="warn">unread</Pill>}
            {e.filings > 1 && <span>· {e.filings} filings</span>}
          </span>
        </span>
        <span className="num shrink-0 pt-px text-[11px] text-faint">{ago(e.occurred_at, asOf)}</span>
      </Link>
    </li>
  );
}

function QuietState({ win, brief, onWiden }: { win: string; brief: Brief; onWiden: () => void }) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-4 py-4 text-[13.5px] leading-snug text-muted">
      Nothing top-tier in the last {win === "24h" ? "24 hours" : win}. {brief.totals.filings} filing
      {brief.totals.filings === 1 ? "" : "s"} came in; none cleared the top-tier bar (results, M&amp;A, top-management
      changes, rating downgrades).
      {win !== "30d" && (
        <button onClick={onWiden} className="mt-2 block font-medium text-accent">
          Widen to {win === "24h" ? "7 days" : "30 days"} →
        </button>
      )}
    </div>
  );
}
