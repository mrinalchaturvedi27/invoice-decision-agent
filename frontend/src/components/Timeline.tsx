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
  { key: "explain", label: "Explain", hint: "Summary for the AP team" },
];

function Icon({ status }: { status: StepStatus | "pending" }) {
  const base = "grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold";
  switch (status) {
    case "running":
      return <span className={`${base} border-2 border-sky-500 border-t-transparent animate-spin`} />;
    case "pass":
      return <span className={`${base} bg-emerald-500 text-white`}>✓</span>;
    case "fail":
      return <span className={`${base} bg-amber-500 text-white`}>!</span>;
    case "error":
      return <span className={`${base} bg-rose-600 text-white`}>×</span>;
    case "info":
      return <span className={`${base} bg-sky-500 text-white`}>i</span>;
    case "skipped":
      return <span className={`${base} bg-slate-300 text-slate-600 dark:bg-slate-700 dark:text-slate-300`}>–</span>;
    default:
      return <span className={`${base} border-2 border-slate-300 dark:border-slate-700`} />;
  }
}

export function RuleList({ rules }: { rules: Rule[] }) {
  return (
    <ul className="space-y-1">
      {rules.map((r, i) => (
        <li key={i} className="flex gap-2 text-xs">
          <span className={r.ok === false ? "text-amber-600 dark:text-amber-400" : r.ok ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}>
            {r.ok === false ? "✗" : r.ok ? "✓" : "–"}
          </span>
          <span>
            <code className="font-mono text-[11px] text-slate-500 dark:text-slate-400">{r.rule}</code>{" "}
            <span className="text-slate-700 dark:text-slate-300">{r.message}</span>
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
    <div className="mt-2 space-y-2 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/60">
      {rules && <RuleList rules={rules} />}
      {d.extraction && <p className="text-xs text-slate-500">Extracted fields are shown in full below the decision.</p>}
      {Object.keys(extra).length > 0 && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-slate-600 dark:text-slate-300">
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

  return (
    <ol className="card divide-y divide-slate-100 dark:divide-slate-800">
      {STAGES.map((stage) => {
        const all = byStage.get(stage.key) ?? [];
        const step = all[all.length - 1];
        const status: StepStatus | "pending" = step ? step.status : "pending";
        const isOpen = open[stage.key] ?? false;
        const cached = stage.key === "extract" && step?.detail?.cached;
        const live = stage.key === "extract" && step && step.status !== "running" && step.detail && !step.detail.cached;
        return (
          <li key={stage.key} className="px-4 py-3">
            <button className="flex w-full items-start gap-3 text-left" disabled={!step || step.status === "running"}
                    onClick={() => setOpen({ ...open, [stage.key]: !isOpen })}>
              <Icon status={status} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-semibold">{stage.label}</span>
                  {cached && <span className="rounded bg-violet-100 px-1.5 py-px text-[10px] font-semibold text-violet-700 dark:bg-violet-500/15 dark:text-violet-300">CACHED EXTRACTION</span>}
                  {live && <span className="rounded bg-sky-100 px-1.5 py-px text-[10px] font-semibold text-sky-700 dark:bg-sky-500/15 dark:text-sky-300">LIVE MODEL CALL</span>}
                  {all.length > 1 && <span className="rounded bg-slate-100 px-1.5 py-px text-[10px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">re-evaluated ×{all.length}</span>}
                  {step?.duration_ms != null && step.status !== "running" && (
                    <span className="num ml-auto text-[11px] text-slate-400">{step.duration_ms < 1000 ? `${step.duration_ms} ms` : `${(step.duration_ms / 1000).toFixed(1)} s`}</span>
                  )}
                </div>
                <p className={`mt-0.5 text-xs ${status === "fail" ? "text-amber-700 dark:text-amber-300" : status === "error" ? "text-rose-700 dark:text-rose-300" : "text-slate-500 dark:text-slate-400"}`}>
                  {step ? (step.status === "running" ? "Running…" : step.summary) : running ? "Waiting" : stage.hint}
                </p>
                {step && step.status !== "running" && (
                  <span className="mt-1 inline-block text-[11px] text-slate-400">{isOpen ? "Hide details ▴" : "Details ▾"}</span>
                )}
              </div>
            </button>
            {isOpen && step && <div className="pl-9"><StepDetail step={step} /></div>}
          </li>
        );
      })}
    </ol>
  );
}
