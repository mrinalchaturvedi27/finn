"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";

export type Mode = "demo" | "live";
const KEY = "finn.mode";

/** Which briefing is open. The URL is the source of truth (links carry ?mode=), so a shared
 * link opens the same view; the last choice is remembered for bare visits. */
export function useMode() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const fromUrl = params.get("mode");
  const mode: Mode = fromUrl === "live" || fromUrl === "demo" ? fromUrl : "demo";

  useEffect(() => {
    if (fromUrl) {
      try {
        localStorage.setItem(KEY, fromUrl);
      } catch {}
      return;
    }
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(KEY);
    } catch {}
    if (saved === "live") router.replace(`${path}?mode=live`, { scroll: false });
  }, [fromUrl, path, router]);

  const setMode = useCallback(
    (m: Mode) => {
      const q = new URLSearchParams(params.toString());
      q.set("mode", m);
      router.push(`${path}?${q.toString()}`, { scroll: false });
    },
    [params, path, router],
  );

  /** A link that stays in the same briefing. */
  const href = useCallback((p: string) => {
    const [base, hash] = p.split("#");
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}mode=${mode}${hash ? `#${hash}` : ""}`;
  }, [mode]);

  return { mode, setMode, href, view: mode };
}
