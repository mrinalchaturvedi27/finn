"use client";

import { useEffect, useState } from "react";
import { BackLink, SectionLabel } from "@/components/ui";
import { get, put, type Settings } from "@/lib/api";
import { CATEGORY_LABEL } from "@/lib/format";

const WATCHABLE = ["results", "M&A", "management_change", "fund_raise", "litigation", "credit_rating", "pledging",
  "insider_trading", "capex", "dividend", "bonus_split", "press_release"];

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [saved, setSaved] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    get<Settings>("/api/settings").then(setS);
  }, []);

  async function save(next: Settings) {
    setS(next);
    setSaved("saving");
    try {
      await put("/api/settings", {
        volume_multiple: next.volume_multiple, price_pct: next.price_pct, alert_categories: next.alert_categories,
      });
      setSaved("saved");
    } catch {
      setSaved("error");
    }
  }

  return (
    <main className="mx-auto max-w-[560px] px-4 pb-24 pt-5">
      <BackLink />
      <h1 className="mt-4 text-[21px] font-semibold tracking-tight">What counts as unusual</h1>
      <p className="mt-1 text-[13px] text-muted">
        FINN watches every portfolio stock after each close and flags it here when it crosses your lines.
        {saved === "saved" && <span className="text-up"> Saved.</span>}
        {saved === "error" && <span className="text-down"> Couldn’t save.</span>}
      </p>
      {s && (
        <>
          <SectionLabel>Price move</SectionLabel>
          <Slider value={s.price_pct} min={1} max={15} step={0.5} unit="%" prefix="±"
            onChange={(v) => setS({ ...s, price_pct: v })} onCommit={(v) => save({ ...s, price_pct: v })}
            help="Close-to-close change in one session." />
          <SectionLabel>Volume spike</SectionLabel>
          <Slider value={s.volume_multiple} min={1.2} max={6} step={0.1} unit="×"
            onChange={(v) => setS({ ...s, volume_multiple: v })} onCommit={(v) => save({ ...s, volume_multiple: v })}
            help="Session volume vs the average of the previous 20 completed sessions (the session itself excluded)." />
          <SectionLabel>Announcement types that alert</SectionLabel>
          <div className="flex flex-wrap gap-2">
            {WATCHABLE.map((c) => {
              const on = s.alert_categories.includes(c);
              return (
                <button key={c} onClick={() => save({ ...s, alert_categories: on ? s.alert_categories.filter((x) => x !== c) : [...s.alert_categories, c] })}
                  className={`rounded-full px-3 py-1.5 text-[13px] ${on ? "bg-ink text-bg" : "border border-line bg-surface text-muted"}`}>
                  {CATEGORY_LABEL[c]}
                </button>
              );
            })}
          </div>
          <p className="mt-6 px-1 text-[11.5px] leading-snug text-faint">
            Prices are evaluated per stock once the session is published ({s.eod_buffer_min} min after the 15:30 close). A
            stock without that session’s bar is shown as not evaluated rather than holding up the rest.
          </p>
        </>
      )}
    </main>
  );
}

function Slider({ value, min, max, step, unit, prefix = "", help, onChange, onCommit }: {
  value: number; min: number; max: number; step: number; unit: string; prefix?: string; help: string;
  onChange: (v: number) => void; onCommit: (v: number) => void;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-4 py-3">
      <div className="num text-[26px] font-semibold tracking-tight">{prefix}{value}{unit}</div>
      <input type="range" min={min} max={max} step={step} value={value} aria-label={help}
        onChange={(e) => onChange(Number(e.target.value))}
        onPointerUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))}
        className="mt-2 w-full accent-[var(--ink)]" />
      <p className="mt-1 text-[12px] leading-snug text-muted">{help}</p>
    </div>
  );
}
