import type { GuidanceItem, ResearchReport, ResearchSummary, Verdict } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { SectionLabel } from "./ui";

export const VERDICT: Record<Verdict["status"], { label: string; cls: string }> = {
  delivered: { label: "Delivered", cls: "bg-up/10 text-up" },
  partial: { label: "Near miss", cls: "bg-warn-bg text-warn" },
  missed: { label: "Missed", cls: "bg-down/10 text-down" },
  pending: { label: "Pending", cls: "bg-surface-2 text-muted" },
  not_comparable: { label: "Not checkable", cls: "bg-surface-2 text-faint" },
};

export function VerdictChip({ v }: { v: Verdict }) {
  const s = VERDICT[v.status];
  const label = v.status === "pending" && v.tracking ? "Pending · run-rate indication" : s.label;
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${s.cls}`}>{label}</span>;
}

/** One line for lists: only what was found. */
export function SummaryLine({ s }: { s: ResearchSummary }) {
  const parts: [Verdict["status"], number][] = (
    [["delivered", s.delivered], ["partial", s.partial], ["missed", s.missed], ["pending", s.pending]] as [Verdict["status"], number][]
  ).filter(([, n]) => n > 0);
  if (!parts.length) {
    return (
      <span className="text-[12px] text-faint">
        {s.statements ? `No checkable guidance · ${s.not_comparable} statements not checkable` : `No numeric guidance in ${s.calls_read} calls`}
      </span>
    );
  }
  return (
    <span className="flex flex-wrap gap-1.5">
      {parts.map(([k, n]) => (
        <span key={k} className={`rounded-full px-2 py-0.5 text-[11.5px] ${VERDICT[k].cls}`}>
          <span className="num font-semibold">{n}</span> {VERDICT[k].label.toLowerCase()}
        </span>
      ))}
      {s.not_comparable > 0 && <span className="self-center text-[11.5px] text-faint">+{s.not_comparable} not checkable</span>}
    </span>
  );
}

export function SummaryStrip({ s }: { s: ResearchSummary }) {
  const items: [Verdict["status"], number][] = [
    ["delivered", s.delivered],
    ["partial", s.partial],
    ["missed", s.missed],
    ["pending", s.pending],
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map(([k, n]) => (
        <span key={k} className={`rounded-full px-2.5 py-1 text-[12px] ${n ? VERDICT[k].cls : "bg-surface-2 text-faint"}`}>
          <span className="num font-semibold">{n}</span> {VERDICT[k].label.toLowerCase()}
        </span>
      ))}
      {s.not_comparable > 0 && (
        <span className="rounded-full bg-surface-2 px-2.5 py-1 text-[12px] text-faint">
          <span className="num">{s.not_comparable}</span> not checkable
        </span>
      )}
    </div>
  );
}

function pageLink(url: string, page: number) {
  return `${url}#page=${page}`;
}

function delivered(g: GuidanceItem): string | null {
  const v = g.verdict.value;
  if (v == null) return null;
  if (g.metric === "ebitda_margin") return `${v.toFixed(1)}%`;
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function PromiseCard({ g }: { g: GuidanceItem }) {
  const d = delivered(g);
  const v = g.verdict;
  return (
    <li className="border-b border-line py-4 last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <h3 className="serif text-[18px] font-semibold leading-snug">
          {g.metric_label} <span className="font-normal text-muted">· {g.period_label}</span>
        </h3>
        <VerdictChip v={v} />
      </div>
      <dl className="mt-2 grid grid-cols-2 border-y border-line">
        <div className="py-2 pr-3">
          <dt className="text-[11px] text-faint">Guided ({fullDate(g.stated_on)})</dt>
          <dd className="num serif text-[21px] font-semibold leading-tight">{g.target}</dd>
        </div>
        <div className="border-l border-line py-2 pl-3">
          <dt className="text-[11px] text-faint">
            {v.status === "pending" ? `Run-rate, ${v.quarters?.length ?? 0} of 4 quarters` : v.status === "not_comparable" ? "Delivered" : "Delivered (from filings)"}
          </dt>
          <dd className={`num serif text-[21px] font-semibold leading-tight ${d ? "" : "text-faint"}`}>{d ?? "—"}</dd>
        </div>
      </dl>
      {(v.calc || v.reason) && <p className="num mt-2 text-[12px] leading-snug text-muted">{v.calc || v.reason}</p>}
      {v.run_rate && v.reason && v.calc && <p className="mt-1 text-[12px] font-medium leading-snug text-warn">{v.reason}</p>}
      {g.revisions.length > 0 && (
        <p className="mt-1.5 text-[12px] text-warn">
          Revised: {g.revisions.map((r) => `${r.target} (${fullDate(r.stated_on)})`).join(" → ")} → {g.target} ({fullDate(g.stated_on)})
        </p>
      )}
      {(g.reiterated_on?.length ?? 0) > 0 && (
        <p className="mt-1 text-[12px] text-faint">Also said on {g.reiterated_on!.map((x) => fullDate(x)).join(", ")}</p>
      )}
      <blockquote className="serif mt-2.5 border-l-2 border-accent pl-3 text-[14.5px] italic leading-snug text-ink-2">
        “{g.quote}”
        <footer className="mt-1 font-sans text-[11.5px] not-italic text-faint">
          {g.speaker}, earnings call {fullDate(g.stated_on)} ·{" "}
          <a href={pageLink(g.source_url, g.page)} target="_blank" rel="noreferrer" className="font-semibold text-accent underline underline-offset-2">
            transcript p.{g.page} ↗
          </a>
        </footer>
      </blockquote>
    </li>
  );
}

export function NotCheckable({ items }: { items: GuidanceItem[] }) {
  if (!items.length) return null;
  return (
    <details className="group mt-4 border-y border-dashed border-line">
      <summary className="flex min-h-[44px] cursor-pointer items-center justify-between text-[13px] text-muted">
        <span>
          <span className="font-semibold text-ink">{items.length}</span> more statement{items.length > 1 ? "s" : ""} FINN can’t check
          against the filings, with the reason
        </span>
        <span className="group-open:rotate-90" aria-hidden>›</span>
      </summary>
      <ul className="space-y-3 pb-3">
        {items.map((g, i) => (
          <li key={i} className="text-[12.5px]">
            <span className="font-medium">{g.metric_label}</span> <span className="num">{g.target}</span>{" "}
            <span className="text-faint">· {g.period_label}</span>
            <div className="text-[11.5px] text-faint">{g.verdict.reason}</div>
            <div className="mt-0.5 text-[12px] text-muted">
              “{g.quote.length > 180 ? g.quote.slice(0, 180) + "…" : g.quote}”{" "}
              <a href={pageLink(g.source_url, g.page)} target="_blank" rel="noreferrer" className="text-accent">
                p.{g.page} ↗
              </a>
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}

const cr = (v: number | null | undefined) => (v == null ? "—" : Math.round(v / 1e7).toLocaleString("en-IN"));

export function Trajectory({ r }: { r: ResearchReport }) {
  const f = r.financials;
  if (!f || !f.quarters.length) return null;
  const qs = f.quarters;
  const byQe = new Map(qs.map((q) => [q.quarter_end, q]));
  const yoy = (qe: string, k: string) => {
    const d = new Date(qe);
    const prev = byQe.get(`${d.getFullYear() - 1}${qe.slice(4)}`);
    const a = byQe.get(qe)?.values[k];
    const b = prev?.values[k];
    if (a == null || b == null || b <= 0) return null;
    return (a / b - 1) * 100;
  };
  const lender = f.taxonomy === "banking" || f.taxonomy === "nbfc";
  const top = lender ? (f.taxonomy === "banking" ? "nii" : "revenue") : "revenue";
  return (
    <>
      <SectionLabel id="trajectory" right={`${f.basis} · ₹ crore`}>Quarterly trajectory</SectionLabel>
      <div className="overflow-x-auto">
        <table className="num w-full min-w-[340px] text-right text-[12.5px]">
          <thead className="text-[11px] text-faint">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Quarter</th>
              <th className="px-2 py-2 font-medium">{top === "nii" ? "NII" : "Revenue"}</th>
              <th className="px-2 py-2 font-medium">YoY</th>
              {!lender && <th className="px-2 py-2 font-medium">EBITDA %</th>}
              <th className="px-3 py-2 font-medium">PAT</th>
            </tr>
          </thead>
          <tbody>
            {[...qs].reverse().map((q) => {
              const g = yoy(q.quarter_end, top);
              return (
                <tr key={q.quarter_end} className="border-t border-line">
                  <td className="px-3 py-1.5 text-left text-muted">{q.label}</td>
                  <td className="px-2 py-1.5">{cr(q.values[top])}</td>
                  <td className={`px-2 py-1.5 ${g == null ? "text-faint" : g >= 0 ? "text-up" : "text-down"}`}>
                    {g == null ? "—" : `${g >= 0 ? "+" : ""}${g.toFixed(1)}%`}
                  </td>
                  {!lender && (
                    <td className="px-2 py-1.5">{q.values.ebitda_margin == null ? "—" : `${q.values.ebitda_margin.toFixed(1)}%`}</td>
                  )}
                  <td className="px-3 py-1.5">{cr(q.values.pat)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 px-1 text-[11px] text-faint">
        From each quarter’s XBRL results filing (latest revision).{!lender && " EBITDA is FINN’s operating calculation (excludes other income)."}
      </p>
    </>
  );
}

export function Sources({ r }: { r: ResearchReport }) {
  const t = r.sources.transcripts;
  return (
    <>
      <SectionLabel id="sources">Sources</SectionLabel>
      <ul className="space-y-1.5 px-1 text-[12px] text-muted">
        {t.map((s) => (
          <li key={s.call_date + s.nse_url}>
            Earnings call {fullDate(s.call_date)} ·{" "}
            {s.status === "read" ? (
              <>
                <a href={s.url ?? s.nse_url} target="_blank" rel="noreferrer" className="text-accent">
                  transcript ↗
                </a>{" "}
                {s.source === "company_site_via_filing" && <span className="text-faint">(company site, linked from its NSE filing)</span>}
                <span className="text-faint"> · {s.statements} guidance statement{s.statements === 1 ? "" : "s"}</span>
              </>
            ) : (
              <span className="text-down">could not be read</span>
            )}
          </li>
        ))}
        <li>{r.sources.xbrl.length} quarterly XBRL results filings (NSE)</li>
      </ul>
      {r.failures.length > 0 && (
        <ul className="mt-2 space-y-1 px-1 text-[11.5px] text-warn">
          {r.failures.map((f, i) => (
            <li key={i}>
              {f.stage}
              {f.call_date ? ` ${fullDate(f.call_date)}` : ""}
              {f.quarter_end ? ` ${f.quarter_end}` : ""}: {f.error}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
