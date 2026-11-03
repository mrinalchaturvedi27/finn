"use client";

import { useCallback, useEffect, useState } from "react";
import type { Settings } from "./api";

/** Alert preferences for this browser only (no account). They re-rank what the brief shows;
 * they do not change server-side monitoring, which uses the server's defaults. */
export type Prefs = { price_pct: number; volume_multiple: number; alert_categories: string[] };
const KEY = "finn.prefs.v1";

function read(): Partial<Prefs> | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Partial<Prefs>) : null;
  } catch {
    return null;
  }
}

export function usePrefs(server: Settings | null | undefined) {
  const [local, setLocal] = useState<Partial<Prefs> | null>(null);
  useEffect(() => setLocal(read()), []);

  const defaults: Prefs | null = server
    ? { price_pct: server.price_pct, volume_multiple: server.volume_multiple, alert_categories: server.alert_categories }
    : null;
  const prefs: Prefs | null = defaults ? { ...defaults, ...(local ?? {}) } : null;

  const save = useCallback((next: Prefs) => {
    setLocal(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {}
  }, []);
  const reset = useCallback(() => {
    setLocal(null);
    try {
      localStorage.removeItem(KEY);
    } catch {}
  }, []);

  return { prefs, defaults, custom: !!local, save, reset };
}
