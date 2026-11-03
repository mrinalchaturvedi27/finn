"use client";

import { useCallback, useEffect, useState } from "react";
import { getWaking } from "./api";

export type LoadState = "loading" | "waking" | "ready" | "error";

/** GET with cold-start handling. Keeps the previous data while a new path loads. */
export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const ctl = new AbortController();
    setState("loading");
    setErr(null);
    getWaking<T>(path, () => setState((s) => (s === "loading" ? "waking" : s)), ctl.signal)
      .then((d) => {
        setData(d);
        setState("ready");
      })
      .catch((e) => {
        if (ctl.signal.aborted) return;
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      });
    return () => ctl.abort();
  }, [path, nonce]);

  const retry = useCallback(() => setNonce((n) => n + 1), []);
  return { data, setData, state, err, retry };
}
