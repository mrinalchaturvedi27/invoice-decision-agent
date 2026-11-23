import { useState } from "react";
import type { Rule, Snapshot, Step, StepStatus } from "../types";

const STAGES: { key: string; label: string; hint: string }[] = [
  { key: "ingest", label: "Ingest", hint: "Hash, pages, text layer" },
  { key: "extract", label: "Read invoice", hint: "Claude transcribes fields with page evidence" },
  { key: "vendor", label: "Vendor master", hint: "Known vendor, tax ID, bank details" },
  { key: "duplicates", label: "Duplicates", hint: "Against already-approved invoices" },
  { key: "checks", label: "Verify extraction", hint: "Arithmetic and PDF text-layer cross-check" },
  { key: "po", label: "Resolve PO", hint: "Ownership, currency, status, lines" },
  { key: "consumption", label: "PO consumption", hint: "Price, quantity, open-balance ceiling" },
  { key: "decide", label: "Decide & post", hint: "First failing rule decides; approvals post atomically" },
  { key: "explain", label: "Explain", hint: "Plain-English summary for AP" },
];

const NODE: Record<StepStatus | "pending", string> = {
  pending: "border-line-strong bg-surface text-faint",
  running: "border-info bg-info-bg text-info",
  pass: "border-approve bg-approve text-surface",
  fail: "border-hold bg-hold text-surface",
  error: "border-reject bg-reject text-surface",
  info: "border-info bg-info text-surface",
  skipped: "border-line-strong bg-sunken text-faint",
};
const GLYPH: Partial<Record<StepStatus, string>> = { pass: "✓", fail: "!", error: "×", info: "i", skipped: "–" };

export function RuleList({ rules }: { rules: Rule[] }) {
  return (
    <ul className="space-y-1.5">
      {rules.map((r, i) => (
        <li key={i} className="grid grid-cols-[14px_minmax(0,1fr)] gap-2 text-[12.5px] leading-snug">
          <span className={`font-mono ${r.ok === false ? "text-hold" : r.ok ? "text-approve" : "text-faint"}`}>
            {r.ok === false ? "✗" : r.ok ? "✓" : "–"}
          </span>
          <span className="min-w-0">
            <code className={`mr-1.5 font-mono text-[11px] ${r.ok === false ? "font-semibold text-ink" : "text-muted"}`}>{r.rule}</code>
            <span className="text-ink-2">{r.message}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function StepDetail({ step }: { step: Step }) {
  const d = step.detail ?? {};
  const rules: Rule[] | undefined = d.rules;
  const extra = Object.fromEntries(Object.entries(d).filter(([k]) => !["rules", "extraction"].includes(k)));
  return (
    <div className="mt-2.5 space-y-2 rounded-md border border-line bg-sunken p-3">
      {rules && <RuleList rules={rules} />}
      {d.extraction && <p className="text-xs text-muted">The extracted fields are shown in full under the decision.</p>}
      {Object.keys(extra).length > 0 && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-ink-2">
          {JSON.stringify(extra, null, 2)}
        </pre>
      )}
    </div>
  );
}

export default function Timeline({ snap }: { snap: Snapshot }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const running = snap.run.status === "running" || snap.run.status === "queued";
  const byStage = new Map<string, Step[]>();
  snap.steps.forEach((s) => byStage.set(s.stage, [...(byStage.get(s.stage) ?? []), s]));
  const total = snap.steps.reduce((n, s) => n + (s.duration_ms ?? 0), 0);

  return (
    <section className="card min-w-0 px-5 pb-3 pt-4">
      <div className="mb-2 flex items-baseline justify-between">
        <p className="label">Pipeline</p>
        {!running && total > 0 && <span className="num font-mono text-[11px] text-muted">{(total / 1000).toFixed(1)} s total</span>}
      </div>
      <ol>
        {STAGES.map((stage, idx) => {
          const all = byStage.get(stage.key) ?? [];
          const step = all[all.length - 1];
          const status: StepStatus | "pending" = step ? step.status : "pending";
          const isOpen = open[stage.key] ?? false;
          const cached = stage.key === "extract" && step?.detail?.cached;
          const live = stage.key === "extract" && step && step.status !== "running" && step.detail && !step.detail.cached;
          const last = idx === STAGES.length - 1;
          const done = step && step.status !== "running";
          return (
            <li key={stage.key} className="relative grid grid-cols-[28px_minmax(0,1fr)] gap-3">
              {!last && <span aria-hidden className={`absolute left-[13.5px] top-7 bottom-0 w-px ${done ? "bg-line-strong" : "bg-line"}`} />}
              <span className={`relative z-[1] mt-2 grid h-7 w-7 place-items-center rounded-full border-[1.5px] font-mono text-[11px] font-semibold ${NODE[status]}`}>
                {status === "running" ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-info border-t-transparent" />
                  : status === "pending" ? String(idx + 1).padStart(2, "0") : GLYPH[status as StepStatus]}
              </span>
              <div className="min-w-0 py-2">
                <button className="block w-full text-left disabled:cursor-default" disabled={!done}
                        onClick={() => setOpen({ ...open, [stage.key]: !isOpen })}>
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className={`text-[13.5px] font-semibold ${status === "pending" ? "text-muted" : ""}`}>{stage.label}</span>
                    {cached && <span className="rounded-sm border border-line-strong px-1.5 font-mono text-[9.5px] font-medium tracking-wider text-muted">CACHED READ</span>}
                    {live && <span className="rounded-sm bg-info-bg px-1.5 font-mono text-[9.5px] font-medium tracking-wider text-info">LIVE MODEL CALL</span>}
                    {all.length > 1 && <span className="rounded-sm bg-sunken px-1.5 font-mono text-[9.5px] text-muted">re-evaluated ×{all.length}</span>}
                    {done && step.duration_ms != null && (
                      <span className="num ml-auto font-mono text-[10.5px] text-faint">{step.duration_ms < 1000 ? `${step.duration_ms} ms` : `${(step.duration_ms / 1000).toFixed(1)} s`}</span>
                    )}
                  </span>
                  <span className={`mt-0.5 block text-[12.5px] leading-snug ${status === "fail" ? "text-hold" : status === "error" ? "text-reject" : "text-muted"}`}>
                    {step ? (step.status === "running" ? "Running…" : step.summary) : running ? "Waiting" : stage.hint}
                  </span>
                  {done && <span className="mt-1 inline-block font-mono text-[10px] uppercase tracking-wider text-faint hover:text-ink">{isOpen ? "hide ▴" : "details ▾"}</span>}
                </button>
                {isOpen && step && <StepDetail step={step} />}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
