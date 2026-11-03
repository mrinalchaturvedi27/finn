"use client";

import { useEffect, useState } from "react";
import { BackLink, LoadStatus, SectionLabel } from "@/components/ui";
import { type Settings, withView } from "@/lib/api";
import { CATEGORY_LABEL } from "@/lib/format";
import { useMode } from "@/lib/mode";
import { type Prefs, usePrefs } from "@/lib/prefs";
import { useApi } from "@/lib/useApi";

const WATCHABLE = ["results", "M&A", "management_change", "fund_raise", "litigation", "credit_rating", "pledging",
  "insider_trading", "capex", "dividend", "bonus_split", "press_release"];

export default function PreferencesPage() {
  const { mode, href } = useMode();
  const { data: server, state, err, retry } = useApi<Settings>(withView("/api/settings", mode));
  const { prefs, defaults, custom, save, reset } = usePrefs(server);
  const [draft, setDraft] = useState<Prefs | null>(null);
  useEffect(() => {
    if (prefs && !draft) setDraft(prefs);
  }, [prefs, draft]);
  const [saved, setSaved] = useState(false);

  const commit = (next: Prefs) => {
    setDraft(next);
    save(next);
    setSaved(true);
  };

  return (
    <main className="mx-auto max-w-[640px] px-4 pb-24 pt-3 sm:px-6">
      <BackLink href={href("/")} label={mode === "demo" ? "Demo briefing" : "Briefing"} />
      <div className="kicker mt-3 text-accent">Preferences</div>
      <h1 className="serif mt-1 text-[30px] font-semibold leading-tight tracking-tight">What counts as unusual</h1>

      <details className="group mt-3 border-l-2 border-accent pl-3 text-[13px] leading-snug text-ink-2">
        <summary className="flex min-h-[40px] cursor-pointer items-center gap-2">
          <span><span className="font-semibold">Saved in this browser only</span> · server monitoring unchanged</span>
          <span className="text-faint group-open:rotate-90" aria-hidden>›</span>
        </summary>
        <p className="pb-1">
          These lines decide which price moves and filings the briefing flags as alerts for you, in the demo and live briefings.
          They don’t change what the server monitors, and nothing sends notifications.
        </p>
        {defaults && (
          <p className="pb-2 text-muted">
            Background monitoring keeps the server defaults: ±{defaults.price_pct}% price, {defaults.volume_multiple}× volume,{" "}
            {defaults.alert_categories.map((c) => CATEGORY_LABEL[c] ?? c).join(", ")}.
          </p>
        )}
      </details>

      {!server && <LoadStatus state={state} err={err} onRetry={retry} what="preferences" />}

      {draft && (
        <>
          <SectionLabel right={saved ? <span className="text-up">Saved in this browser</span> : custom ? "Custom" : "Defaults"}>
            Price move
          </SectionLabel>
          <Slider value={draft.price_pct} min={1} max={15} step={0.5} unit="%" prefix="±"
            label="Price move threshold" help="Close-to-close change in one session."
            onChange={(v) => setDraft({ ...draft, price_pct: v })} onCommit={(v) => commit({ ...draft, price_pct: v })} />

          <SectionLabel>Volume spike</SectionLabel>
          <Slider value={draft.volume_multiple} min={1.2} max={6} step={0.1} unit="×"
            label="Volume threshold" help="Session volume against the average of the previous 20 sessions (the session itself excluded)."
            onChange={(v) => setDraft({ ...draft, volume_multiple: v })} onCommit={(v) => commit({ ...draft, volume_multiple: v })} />

          <SectionLabel>Filing types that alert</SectionLabel>
          <p className="mb-2 text-[12.5px] text-muted">
            Major filings of these types are marked <span className="font-semibold text-accent">●</span> and counted as alerts in the briefing.
          </p>
          <div className="flex flex-wrap gap-2">
            {WATCHABLE.map((c) => {
              const on = draft.alert_categories.includes(c);
              return (
                <button key={c} aria-pressed={on}
                  onClick={() => commit({ ...draft, alert_categories: on ? draft.alert_categories.filter((x) => x !== c) : [...draft.alert_categories, c] })}
                  className={`min-h-[40px] rounded-sm border px-3 text-[13px] ${on ? "border-ink bg-ink text-bg" : "border-line text-muted hover:border-ink hover:text-ink"}`}>
                  {on ? "✓ " : ""}{CATEGORY_LABEL[c]}
                </button>
              );
            })}
          </div>

          <div className="mt-6 border-t border-line pt-2 text-[13px]">
            <button
              onClick={() => {
                reset();
                if (defaults) setDraft(defaults);
                setSaved(false);
              }}
              disabled={!custom}
              className="min-h-[44px] font-semibold text-accent underline-offset-4 hover:underline disabled:text-faint disabled:no-underline"
            >
              Reset to server defaults
            </button>
            <p className="text-[12px] text-faint">Prices are evaluated per stock once the session is published ({server?.eod_buffer_min} min after the 15:30 close).</p>
          </div>
        </>
      )}
    </main>
  );
}

function Slider({ value, min, max, step, unit, prefix = "", help, label, onChange, onCommit }: {
  value: number; min: number; max: number; step: number; unit: string; prefix?: string; help: string; label: string;
  onChange: (v: number) => void; onCommit: (v: number) => void;
}) {
  return (
    <div>
      <div className="num serif text-[30px] font-semibold leading-none">{prefix}{value}{unit}</div>
      <input type="range" min={min} max={max} step={step} value={value} aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        onPointerUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))}
        className="mt-3 h-6 w-full accent-[var(--accent)]" />
      <p className="mt-1 text-[12.5px] leading-snug text-muted">{help}</p>
    </div>
  );
}
