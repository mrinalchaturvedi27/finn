"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { BriefLine, LeadStory, Moves, Routine, SpotlightBlock, StoryRow, alerting, evaluateMoves } from "@/components/brief";
import { LoadStatus, Masthead, ModeSwitch, SectionLabel, StatusBar, WindowTabs } from "@/components/ui";
import { type Brief, type BriefEvent, withView } from "@/lib/api";
import { istDate, istTime } from "@/lib/format";
import { useMode } from "@/lib/mode";
import { usePrefs } from "@/lib/prefs";
import { useApi } from "@/lib/useApi";

const WINDOW_WORDS: Record<string, string> = { "24h": "24 hours", "3d": "3 days", "7d": "7 days", "30d": "30 days" };

function longDate(iso: string) {
  const d = new Date(iso.length === 10 || /[zZ+]/.test(iso.slice(10)) ? iso : `${iso}+05:30`);
  return d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Kolkata" });
}

export default function BriefPage() {
  const { mode, setMode, href } = useMode();
  const [win, setWin] = useState<string>("3d");
  useEffect(() => {
    try {
      const saved = localStorage.getItem(`finn.window.${mode}`);
      setWin(saved ?? (mode === "demo" ? "3d" : "24h"));
    } catch {}
  }, [mode]);
  const changeWin = (w: string) => {
    setWin(w);
    try {
      localStorage.setItem(`finn.window.${mode}`, w);
    } catch {}
  };

  const { data, state, err, retry } = useApi<Brief>(withView(`/api/brief?window=${win}`, mode));
  const fresh = data && data.view === mode ? data : null; // never show the other briefing's data while switching
  const { prefs, custom } = usePrefs(fresh?.settings);

  const view = useMemo(() => {
    if (!fresh || !prefs) return null;
    const rows = [...fresh.movers.triggered, ...fresh.movers.quiet];
    const { flagged } = evaluateMoves(rows, prefs);
    const moveBy = new Map(flagged.map((m) => [m.ticker, m]));
    const top = fresh.tiers.top;
    const alerts = top.filter((e) => alerting(e, prefs));
    return { flagged, moveBy, lead: top[0], rest: top.slice(1), alerts };
  }, [fresh, prefs]);

  const ev = (e: BriefEvent) => href(`/e/${e.id}`);
  const dateline = fresh
    ? mode === "demo"
      ? `${longDate(fresh.as_of)} · ${istTime(fresh.as_of)} IST · demo`
      : `${longDate(fresh.as_of)} · ${istTime(fresh.as_of)} IST`
    : "Portfolio briefing";

  return (
    <main className="mx-auto max-w-[1120px] px-4 pb-24 pt-4 sm:px-6">
      <Masthead dateline={dateline} href={href} right={fresh && <span>{fresh.totals.filings} filings · {fresh.totals.events} events in {WINDOW_WORDS[win]}</span>} />
      <ModeSwitch mode={mode} setMode={setMode} />

      {mode === "demo" && (
        <p className="mt-2 text-[12px] leading-snug text-muted">
          Real NSE filings and prices recorded by FINN, replayed as of <span className="font-medium text-ink">30 Oct 2026, 20:00 IST</span>{" "}
          (a heavy results day). Not live.
        </p>
      )}
      {mode === "live" && fresh?.data_source !== "live" && fresh && (
        <p className="mt-2 border-l-2 border-warn pl-2 text-[12px] leading-snug text-warn">
          {fresh.data_source === "seed_fallback" ? "The live database is unavailable right now, so this" : "The live database isn’t connected, so this"} is the
          recorded snapshot from {istDate(fresh.reference?.captured_at ?? fresh.as_of, true)}, not live data.
        </p>
      )}

      {fresh && (
        <StatusBar
          f={fresh.freshness}
          stale={fresh.movers.stale.map((m) => m.ticker)}
          mode={fresh.mode}
          source={fresh.data_source}
          asOf={fresh.as_of}
          scheduleNote={fresh.freshness.nse_announcements?.cadence}
        />
      )}
      <WindowTabs value={win} onChange={changeWin} />

      {!fresh && <LoadStatus state={state === "ready" ? "loading" : state} err={err} onRetry={retry} what="the briefing" />}

      {fresh && view && prefs && (
        <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-12">
          <div className="min-w-0">
            <AlertSummary filings={view.alerts.length} moves={view.flagged.length} className="mt-4 lg:hidden" />

            {view.lead ? (
              <LeadStory e={view.lead} asOf={fresh.as_of} move={view.moveBy.get(view.lead.ticker)} alert={alerting(view.lead, prefs)} href={ev(view.lead)} />
            ) : (
              <Quiet win={win} brief={fresh} onWiden={() => changeWin(win === "24h" ? "7d" : "30d")} mode={mode} setDemo={() => setMode("demo")} />
            )}

            <div className="lg:hidden">
              <Moves flagged={view.flagged} stale={fresh.movers.stale} session={fresh.movers.session} prefs={prefs} custom={custom} prefsHref={href("/settings")} />
            </div>

            {view.rest.length > 0 && (
              <section>
                <SectionLabel right={`${view.rest.length}`}>Also important</SectionLabel>
                <ul>
                  {view.rest.map((e) => (
                    <StoryRow key={e.id} e={e} asOf={fresh.as_of} move={view.moveBy.get(e.ticker)} alert={alerting(e, prefs)} href={ev(e)} />
                  ))}
                </ul>
              </section>
            )}

            <div className="lg:hidden">
              <SpotlightBlock s={fresh.spotlight} href={fresh.spotlight ? href(`/r/${fresh.spotlight.ticker}#guidance`) : ""} indexHref={href("/research")} />
            </div>

            {fresh.tiers.look.length > 0 && (
              <section>
                <SectionLabel right={`${fresh.tiers.look.length}`}>Worth a look</SectionLabel>
                <ul>
                  {fresh.tiers.look.map((e) => (
                    <BriefLine key={e.id} e={e} asOf={fresh.as_of} href={ev(e)} />
                  ))}
                </ul>
              </section>
            )}

            <Routine items={fresh.tiers.routine} asOf={fresh.as_of} hrefFor={ev} />
          </div>

          <aside className="hidden lg:block" aria-label="Moves and research">
            <AlertSummary filings={view.alerts.length} moves={view.flagged.length} className="mt-8" />
            <Moves flagged={view.flagged} stale={fresh.movers.stale} session={fresh.movers.session} prefs={prefs} custom={custom} prefsHref={href("/settings")} />
            <SpotlightBlock s={fresh.spotlight} href={fresh.spotlight ? href(`/r/${fresh.spotlight.ticker}#guidance`) : ""} indexHref={href("/research")} />
          </aside>
        </div>
      )}
    </main>
  );
}

function AlertSummary({ filings, moves, className }: { filings: number; moves: number; className: string }) {
  if (!filings && !moves) return null;
  const parts = [
    filings ? `${filings} major filing${filings > 1 ? "s" : ""} of types you follow (marked ●)` : null,
    moves ? `${moves} unusual move${moves > 1 ? "s" : ""}` : null,
  ].filter(Boolean);
  return (
    <p className={`bg-accent-bg px-3 py-2 text-[12.5px] leading-snug text-accent ${className}`}>
      <span className="font-semibold">{filings + moves} alert{filings + moves > 1 ? "s" : ""} for you:</span> {parts.join(", ")}.
    </p>
  );
}

function Quiet({ win, brief, onWiden, mode, setDemo }: { win: string; brief: Brief; onWiden: () => void; mode: string; setDemo: () => void }) {
  return (
    <div className="mt-6 border-l-2 border-line pl-3 text-[13.5px] leading-snug text-muted">
      <p>
        Nothing top-tier in the last {WINDOW_WORDS[win]}: {brief.totals.filings} filing{brief.totals.filings === 1 ? "" : "s"}, none of them results,
        M&amp;A, a top-management change or a rating downgrade.
      </p>
      <div className="mt-1 flex flex-wrap gap-x-4">
        {win !== "30d" && (
          <button onClick={onWiden} className="min-h-[40px] font-semibold text-accent underline-offset-4 hover:underline">
            Widen to {win === "24h" ? "7 days" : "30 days"} →
          </button>
        )}
        {mode === "live" && (
          <button onClick={setDemo} className="min-h-[40px] font-semibold text-accent underline-offset-4 hover:underline">
            See the demo briefing →
          </button>
        )}
        <Link href="/research" className="min-h-[40px] py-2.5 font-semibold text-accent underline-offset-4 hover:underline">
          Research a company →
        </Link>
      </div>
    </div>
  );
}
