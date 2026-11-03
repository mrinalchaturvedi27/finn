"use client";

import { useState } from "react";
import type { Check, MetricRow, ResultsCard } from "@/lib/api";
import { crore, istDate } from "@/lib/format";
import { Delta } from "./ui";

const TAG_LABEL: Record<string, string> = {
  ProfitBeforeExceptionalItemsAndTax: "Profit before exceptional items & tax",
  FinanceCosts: "Finance costs",
  DepreciationDepletionAndAmortisationExpense: "Depreciation & amortisation",
  OtherIncome: "Other income",
  InterestEarned: "Interest earned",
  "InterestExpended/FinanceCosts": "Interest expended / finance costs",
  ebitda_op_proxy: "Operating EBITDA (calculated)",
  revenue: "Revenue",
};

/** Higher is worse for these, so colour is inverted (arrow direction is not). */
const COST_LIKE = new Set(["provisions"]);

/** Margin sits directly under the line it is a margin of. */
function ordered(ms: MetricRow[]): MetricRow[] {
  const margin = ms.find((m) => m.id === "ebitda_margin");
  const rest = ms.filter((m) => m !== margin);
  const i = rest.findIndex((m) => m.id === "ebitda_op_proxy");
  if (margin && i >= 0) rest.splice(i + 1, 0, margin);
  return rest;
}

function fmt(m: MetricRow, v: number | null) {
  if (v == null) return "—";
  return m.value_kind === "margin_pct" ? `${v.toFixed(1)}%` : crore(v).replace(" cr", "");
}

export function ResultsView({ card }: { card: ResultsCard }) {
  const [open, setOpen] = useState<string | null>(null);
  const cur = card.periods.current;
  const prev = card.periods.prev_q;
  const yoy = card.periods.yoy_q;
  const pdfUrl = card.pdf && !card.pdf.rejected ? card.pdf.url : null;
  const fmtLabel = card.taxonomy === "banking" ? "bank format" : card.taxonomy === "nbfc" ? "NBFC format" : null;

  return (
    <section className="mt-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 border-b border-rule pb-1.5">
        <h2 className="serif text-[17px] font-semibold">Results at a glance</h2>
        <p className="text-[11.5px] text-faint">
          ₹ crore · {card.basis} · {(cur?.audited ?? "").replace("Un-Audited", "unaudited").toLowerCase()}
          {fmtLabel && ` · ${fmtLabel}`}
        </p>
      </div>
      <table className="num w-full text-right">
        <caption className="sr-only">
          {card.label} against {prev?.label} and {yoy?.label}; tap a row for its source and definition
        </caption>
        <thead>
          <tr className="text-[11px] text-faint">
            <th scope="col" className="py-2 text-left font-medium" />
            <th scope="col" className="py-2 pl-2 font-semibold text-ink">{card.label}</th>
            <th scope="col" className="py-2 pl-2 font-medium">{prev?.label ?? "Prev Q"}</th>
            <th scope="col" className="py-2 pl-2 font-medium">{yoy?.label ?? "Year ago"}</th>
          </tr>
        </thead>
        {ordered(card.metrics).map((m) => (
          <MetricLine key={m.id} m={m} open={open === m.id} onToggle={() => setOpen(open === m.id ? null : m.id)} pdfUrl={pdfUrl} card={card} />
        ))}
      </table>
      <p className="mt-2 text-[11.5px] leading-snug text-faint">
        Changes under each comparison are this quarter against that period. ✓ = found on the printed statement in the right
        column; calc. = calculated by FINN, not reported. Tap a row for its source.
      </p>
      <Evidence card={card} pdfUrl={pdfUrl} />
    </section>
  );
}

function Mark({ m }: { m: MetricRow }) {
  const c = m.corroboration;
  if (m.verification_status === "unavailable") return <span className="ml-1 text-[11px] font-semibold text-warn" title="Unavailable">!</span>;
  if (c?.status === "definition_differs")
    return <span className="ml-1.5 rounded-sm bg-warn-bg px-1 text-[10.5px] font-semibold text-warn">def ≠ print</span>;
  if (m.calculation_kind === "calculated") return <span className="ml-1.5 text-[10.5px] text-faint">calc.</span>;
  if (c?.status === "aligned") return <span className="ml-1.5 text-[10.5px] text-up" title={`On p.${c.page} of the results PDF`}>✓ p.{c.page}</span>;
  return null;
}

function MetricLine({ m, open, onToggle, pdfUrl, card }: {
  m: MetricRow; open: boolean; onToggle: () => void; pdfUrl: string | null; card: ResultsCard;
}) {
  const sub = m.value_kind === "margin_pct";
  const label = m.label.replace(" (calculated)", "").replace("Operating EBITDA margin", "EBITDA margin");
  const inv = COST_LIKE.has(m.id);
  return (
    <tbody className="border-t border-line">
      <tr onClick={onToggle} className="cursor-pointer align-top hover:bg-surface-2">
        <th scope="row" className="py-2.5 pr-1 text-left font-normal">
          <button onClick={(e) => { e.stopPropagation(); onToggle(); }} aria-expanded={open}
            className={`text-left text-[13.5px] leading-snug ${sub ? "pl-3 text-muted" : "font-semibold"}`}>
            {label}
            <Mark m={m} />
          </button>
        </th>
        <td className={`py-2.5 pl-2 ${sub ? "text-[13px] text-muted" : "serif text-[16px] font-semibold"}`}>{fmt(m, m.current)}</td>
        <td className="py-2.5 pl-2 text-[12.5px] text-muted">
          {fmt(m, m.prev_q)}
          <div><Delta c={m.prev_q_change} invert={inv} className="text-[11.5px] font-semibold" /></div>
        </td>
        <td className="py-2.5 pl-2 text-[12.5px] text-muted">
          {fmt(m, m.yoy_q)}
          <div><Delta c={m.yoy_q_change} invert={inv} className="text-[11.5px] font-semibold" /></div>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={4} className="p-0 text-left">
            <MetricEvidence m={m} pdfUrl={pdfUrl} card={card} />
          </td>
        </tr>
      )}
    </tbody>
  );
}

function MetricEvidence({ m, pdfUrl, card }: { m: MetricRow; pdfUrl: string | null; card: ResultsCard }) {
  const pageLink = (p: number | null | undefined, text?: string) =>
    p && pdfUrl ? (
      <a href={`${pdfUrl}#page=${p}`} target="_blank" rel="noreferrer" className="font-medium text-accent">
        {text ?? `p.${p}`} ↗
      </a>
    ) : null;

  return (
    <div className="space-y-2 border-l-2 border-accent bg-surface-2 px-3 py-3 text-[12.5px] leading-snug text-muted">

      {m.unavailable_reason && <p className="text-warn">Unavailable: {m.unavailable_reason}</p>}

      {m.calculation_kind === "reported" ? (
        <div className="space-y-1.5">
          <p>
            <span className="text-ink">Reported</span> in the company’s XBRL results filing
            {m.definition?.xbrl_concept && <span className="text-faint"> (concept {m.definition.xbrl_concept})</span>}.
          </p>
          <Corroboration m={m} card={card} pageLink={pageLink} hasPdf={!!pdfUrl} />
        </div>
      ) : (
        <div>
          <p>
            <span className="text-ink">Calculated:</span> {m.formula}
          </p>
          {Object.keys(m.inputs).length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {Object.entries(m.inputs).map(([k, v]) => (
                <li key={k} className="num flex justify-between gap-3">
                  <span>{TAG_LABEL[k] ?? k}</span>
                  <span>
                    {crore(v)}
                    {m.input_pages?.[k] && m.input_alignment?.[k] ? <> · {pageLink(m.input_pages[k])}</> : null}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {m.note && <p className="text-faint">{m.note}</p>}
    </div>
  );
}

function Corroboration({ m, card, pageLink, hasPdf }: {
  m: MetricRow; card: ResultsCard; hasPdf: boolean;
  pageLink: (p: number | null | undefined, text?: string) => React.ReactNode;
}) {
  const c = m.corroboration;
  if (!c || c.status === "no_pdf" || !hasPdf)
    return <p className="text-warn">No confirmed results PDF — shown from XBRL only.</p>;
  if (c.status === "aligned") {
    const by = c.aligned?.by === "yoy_q" ? card.periods.yoy_q?.label : card.periods.prev_q?.label;
    return (
      <p>
        Located on {pageLink(c.page, `p.${c.page} of the results PDF`)} in the current-quarter column: printed as{" "}
        <span className="num text-ink">{c.match}</span>, and the next column matches {by} from its own filing
        {c.raw && c.raw !== c.match && <span className="text-faint"> (raw OCR text “{c.raw}”, repaired)</span>}.
      </p>
    );
  }
  if (c.status === "definition_differs")
    return (
      <div className="rounded-lg border border-warn/30 bg-warn-bg px-3 py-2 text-warn">
        <div className="font-medium">Definition differs from printed {m.label}</div>
        <div className="mt-0.5">
          The statement prints <span className="num">{c.printed_value}</span> for “{c.printed_label?.replace(/^[\d\s.-]+/, "")}”
          ({pageLink(c.page)}). FINN shows the XBRL concept and excludes it from comparisons that need the printed figure.
        </div>
      </div>
    );
  if (c.status === "column_unconfirmed")
    return (
      <p className="text-warn">
        The value appears on {pageLink(c.page)} but its column couldn’t be confirmed against the comparison quarters — not
        counted as corroborated.
      </p>
    );
  return <p className="text-warn">Not located in the printed statement — shown from XBRL only.</p>;
}

function CheckList({ checks }: { checks?: Check[] }) {
  if (!checks?.length) return null;
  return (
    <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
      {checks.map((c) => (
        <li key={c.check} title={c.detail} className={c.ok ? "text-up" : "text-down"}>
          {c.ok ? "✓" : "✕"} {c.check.replace("_", " ")}
        </li>
      ))}
    </ul>
  );
}

function Evidence({ card, pdfUrl }: { card: ResultsCard; pdfUrl: string | null }) {
  const located = card.metrics.filter((m) => m.calculation_kind === "reported" && m.current != null);
  const n = located.filter((m) => m.corroboration?.status === "aligned").length;
  const defDiff = located.filter((m) => m.corroboration?.status === "definition_differs").length;
  const allXbrl = (["current", "prev_q", "yoy_q"] as const).every((k) => card.periods[k]?.checks?.every((c) => c.ok) ?? false);
  return (
    <details className="group mt-5 border-y border-line">
      <summary className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 py-2 text-[13px]">
        <span>
          <span className="font-semibold">How these numbers were checked</span>
          <span className="block text-[12px] text-muted">
            {allXbrl ? "Company, basis and period confirmed in all three XBRL filings" : "XBRL checks: see details"}
            {card.pdf && !card.pdf.rejected ? ` · ${n}/${located.length} reported values found on the printed statement` : " · no confirmed results PDF"}
            {defDiff ? ` · ${defDiff} definition difference` : ""}
            {card.pdf?.statement_page_repairs?.length ? " · OCR repairs disclosed" : ""}
          </span>
        </span>
        <span className="text-faint group-open:rotate-90" aria-hidden>›</span>
      </summary>
      <div className="space-y-3 pb-4 text-[12.5px] leading-snug text-muted">
        <div>
          <div className="font-medium text-ink">XBRL results filings (primary, machine-readable)</div>
          {(["current", "prev_q", "yoy_q"] as const).map((k) => {
            const p = card.periods[k];
            if (!p) return <div key={k} className="text-warn">{k}: no filing found</div>;
            return (
              <div key={k} className="mt-1.5">
                <a href={p.xbrl_url} target="_blank" rel="noreferrer" className="font-medium text-accent underline underline-offset-2">{p.label} XBRL ↗</a>
                <span className="text-faint"> · filed {istDate(p.filed)}{p.revisions_superseded ? ` · supersedes ${p.revisions_superseded} earlier version` : ""}</span>
                <CheckList checks={p.checks} />
              </div>
            );
          })}
        </div>
        <div className="border-t border-line pt-3">
          <div className="font-medium text-ink">Printed results statement</div>
          {card.pdf ? (
            <>
              <div className="mt-1">
                {card.pdf.rejected ? (
                  <span className="text-warn">Candidate rejected — couldn’t confirm it inside the document{card.pdf.text_pages <= 1 ? " (scanned image, no text layer)" : ""}. </span>
                ) : (
                  <>
                    {n}/{located.length} reported values located in their current-quarter column
                    {card.statement_page ? <> on <a href={`${pdfUrl}#page=${card.statement_page}`} target="_blank" rel="noreferrer" className="text-accent">p.{card.statement_page} ↗</a></> : null}
                    {defDiff ? `; ${defDiff} with a different printed definition` : ""}.{" "}
                  </>
                )}
                <span className="text-faint">{card.pdf.n_pages} pages · {card.pdf.subject}</span>
              </div>
              <CheckList checks={card.pdf.checks} />
              {card.pdf.statement_page_repairs && card.pdf.statement_page_repairs.length > 0 && (
                <div className="mt-1.5 text-faint">Text repairs on that page: {card.pdf.statement_page_repairs.join("; ")}. Raw text is kept.</div>
              )}
            </>
          ) : (
            <div className="mt-1 text-warn">No results PDF identified in the filings feed.</div>
          )}
        </div>
        {card.problems.length > 0 && (
          <div className="border-t border-line pt-3 text-warn">
            {card.problems.map((p) => <div key={p}>{p}</div>)}
          </div>
        )}
      </div>
    </details>
  );
}
