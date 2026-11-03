"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMode } from "@/lib/mode";

const sections = [
  { path: "/", label: "Brief", code: "01" },
  { path: "/research", label: "Research", code: "02" },
  { path: "/settings", label: "Watch rules", code: "03" },
];

export function TerminalShell() {
  const path = usePathname();
  const { mode, href } = useMode();
  return (
    <>
      <a href="#workspace" className="terminal-skip">Skip to workspace</a>
      <header className="terminal-bar">
        <Link href={href("/")} className="terminal-brand" aria-label="FINN home">
          <span className="terminal-mark" aria-hidden>F<span>_</span></span>
          <span>FINN<span className="terminal-brand-sub"> / TERMINAL</span></span>
        </Link>
        <nav aria-label="Workspace" className="terminal-nav">
          {sections.map((s) => {
            const active = s.path === "/" ? path === "/" || path.startsWith("/e/") : s.path === "/research" ? path === s.path || path.startsWith("/r/") : path === s.path;
            return <Link key={s.path} href={href(s.path)} aria-current={active ? "page" : undefined} className={active ? "is-active" : ""}>
              <span className="terminal-nav-code" aria-hidden>{s.code}</span>{s.label}
            </Link>;
          })}
        </nav>
        <span className="terminal-context">{mode === "demo" ? "REPLAY MODE" : "LIVE VIEW"}</span>
      </header>
      <footer className="terminal-footer">
        <span><span className="terminal-footer-dot" />FINN / INVESTMENT INTELLIGENCE</span>
        <span>{mode === "demo" ? "HISTORICAL REPLAY · NOT LIVE" : "CHECK SOURCE STATUS FOR FRESHNESS"}</span>
      </footer>
    </>
  );
}
