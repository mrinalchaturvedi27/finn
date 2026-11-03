"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { AlertItem } from "@/lib/api";
import { CATEGORY_LABEL, ago, istDate } from "@/lib/format";
import { SectionLabel } from "./ui";

const SEEN_KEY = "finn.alerts.seen";

function readSeen(): number {
  try {
    return Number(localStorage.getItem(SEEN_KEY) ?? 0);
  } catch {
    return 0;
  }
}

/** In-app alerts. "New" is per viewer: alerts after the newest one this browser has seen.
 * Price/volume alerts for the session already shown under "Crossed your thresholds" are left out. */
export function Alerts({ alerts: all, asOf, session }: { alerts: AlertItem[]; asOf: string; session: string | null }) {
  const [seen, setSeen] = useState<number | null>(null);
  useEffect(() => setSeen(readSeen()), []);
  const alerts = all.filter((a) => a.kind === "announcement" || a.session !== session);
  if (!alerts.length) return null;
  const newest = alerts[0].id;
  const fresh = seen === null ? 0 : alerts.filter((a) => a.id > seen).length;

  function markSeen() {
    try {
      localStorage.setItem(SEEN_KEY, String(newest));
    } catch {}
    setSeen(newest);
  }

  return (
    <>
      <SectionLabel
        right={
          fresh ? (
            <button onClick={markSeen} className="underline underline-offset-2">
              Mark {fresh} seen
            </button>
          ) : undefined
        }
      >
        Alerts{fresh ? ` · ${fresh} new` : ""}
      </SectionLabel>
      <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
        {alerts.slice(0, 8).map((a) => (
          <li key={a.id} className={`px-4 py-3 text-[13.5px] ${seen !== null && a.id > seen ? "" : "opacity-70"}`}>
            <AlertLine a={a} asOf={asOf} isNew={seen !== null && a.id > seen} />
          </li>
        ))}
      </ul>
    </>
  );
}

function AlertLine({ a, asOf, isNew }: { a: AlertItem; asOf: string; isNew: boolean }) {
  const dot = isNew ? <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" /> : null;
  if (a.kind === "announcement") {
    const body = (
      <>
        {dot}
        <span className="font-semibold">{a.ticker}</span> · {a.title}
        <span className="block text-[11.5px] text-faint">
          {CATEGORY_LABEL[a.category ?? ""] ?? a.category} · {a.created_at ? ago(a.created_at, asOf) : ""}
        </span>
      </>
    );
    return a.event_id ? <Link href={`/e/${a.event_id}`}>{body}</Link> : body;
  }
  const obs = a.observed ?? 0;
  const what =
    a.kind === "price"
      ? `${obs >= 0 ? "▲" : "▼"}${Math.abs(obs).toFixed(1)}% (line ±${a.threshold}%)`
      : `${obs.toFixed(1)}× usual volume (line ${a.threshold}×)`;
  return (
    <>
      {dot}
      <span className="font-semibold">{a.ticker}</span> · <span className="num">{what}</span>
      <span className="block text-[11.5px] text-faint">Session {istDate(a.session)} · evaluated after the close</span>
    </>
  );
}
