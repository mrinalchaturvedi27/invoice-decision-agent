import { DECISION_STYLE, DecisionPill, money } from "../lib";
import type { Snapshot } from "../types";
import { RuleList } from "./Timeline";

export default function DecisionPanel({ snap }: { snap: Snapshot }) {
  const { run, po, linked } = snap;
  const failing = run.trace.filter((r) => r.ok === false);
  const poStep = snap.steps.filter((s) => s.stage === "po").at(-1);
  const inference = poStep?.detail?.method === "inferred" ? poStep.detail : null;

  if (run.status === "error") {
    return (
      <div className="card border-rose-300 p-5 dark:border-rose-500/40">
        <p className="label text-rose-600">Run failed — no decision made</p>
        <p className="mt-2 text-sm">{run.error}</p>
        <p className="mt-2 text-xs text-slate-500">The ledger was not touched. Fix the cause and retry; a retry reuses this run.</p>
      </div>
    );
  }
  if (!run.decision) {
    return (
      <div className="card p-5">
        <p className="label">Decision</p>
        <p className="mt-2 flex items-center gap-2 text-sm text-slate-500">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" /> Working through the checks…
        </p>
      </div>
    );
  }

  const style = DECISION_STYLE[run.decision];
  const unchanged = run.balance_before !== null && run.balance_before === run.balance_after;
  const delta = run.balance_before !== null && run.balance_after !== null ? Number(run.balance_before) - Number(run.balance_after) : 0;

  return (
    <div className="space-y-4">
      <section className={`rounded-xl border p-5 ${style.panel}`}>
        <div className="flex flex-wrap items-center gap-2">
          <DecisionPill decision={run.decision} />
          <span className="text-lg font-semibold">{style.word}</span>
          {run.deciding_rule && <code className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-xs dark:bg-black/30">{run.deciding_rule}</code>}
        </div>
        <p className="mt-3 text-sm leading-relaxed">{run.explanation}</p>
        <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
          {run.explanation_source === "claude" ? "Summary written by Claude from the rule trace" : "Summary built from the rule trace"} · decision by policy {run.policy_version}
        </p>
      </section>

      <section className="card p-5">
        <p className="label">PO ledger</p>
        {po ? (
          <>
            <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm">
                <span className="font-semibold">{po.id}</span>{" "}
                <span className="text-slate-500 dark:text-slate-400">· {po.description} · {money(po.total)} total</span>
              </p>
              <span className="text-xs text-slate-500">{run.po_method === "inferred" ? "Inferred (no PO printed)" : "PO printed on invoice"}</span>
            </div>
            <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
              <div>
                <p className="text-xs text-slate-500">Open before</p>
                <p className="num text-xl font-semibold">{money(run.balance_before)}</p>
              </div>
              <span className="text-slate-400">→</span>
              <div>
                <p className="text-xs text-slate-500">Open after</p>
                <p className={`num text-xl font-semibold ${unchanged ? "" : "text-emerald-700 dark:text-emerald-400"}`}>{money(run.balance_after)}</p>
              </div>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {unchanged ? "Unchanged — nothing was posted for this invoice." : `${money(delta)} posted to ${po.id}.`}
              {" "}Open on {po.id} right now: <span className="num font-medium">{money(po.open_now)}</span>
            </p>
            {po.allocations.length > 0 && (
              <div className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-800">
                <p className="mb-1 text-xs text-slate-500">Postings against {po.id}</p>
                <ul className="space-y-0.5 text-xs">
                  {po.allocations.map((a, i) => (
                    <li key={i} className="flex justify-between gap-2">
                      <a href={`#/run/${a.run_id}`} className={`hover:underline ${a.run_id === run.id ? "font-semibold" : ""}`}>
                        {a.invoice_number} · run #{a.run_id}{a.run_id === run.id ? " (this run)" : ""}
                      </a>
                      <span className="num">{money(a.amount)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className="mt-2 text-sm text-slate-500">No PO resolved, so nothing was compared or posted.</p>
        )}
        {inference?.candidates?.length > 0 && (
          <div className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-800">
            <p className="mb-1 text-xs text-slate-500">
              No PO printed — candidates among this vendor's open POs (accept only if score ≥ {inference.thresholds.min_score} and
              lead ≥ {inference.thresholds.min_lead}; lead here {inference.lead})
            </p>
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500"><tr><th className="py-1 font-medium">PO</th><th className="font-medium">Purpose</th>
                <th className="text-right font-medium">Open</th><th className="text-right font-medium">Score</th></tr></thead>
              <tbody className="num">
                {inference.candidates.map((c: any, i: number) => (
                  <tr key={c.po_id} className={`border-t border-slate-100 dark:border-slate-800 ${i < 2 ? "font-medium" : "text-slate-500"}`}>
                    <td className="py-1">{c.po_id}</td><td>{c.description}</td>
                    <td className="text-right">{money(c.open_balance)}</td><td className="text-right">{Number(c.score).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {linked && (
        <section className="card p-5">
          <p className="label">Linked invoice</p>
          <p className="mt-2 text-sm">
            {linked.invoice_number} · {linked.invoice_date} · {money(linked.total)}
            {linked.approved_run_id && (<> — approved in <a className="font-medium underline" href={`#/run/${linked.approved_run_id}`}>run #{linked.approved_run_id}</a></>)}
          </p>
        </section>
      )}

      <section className="card p-5">
        <p className="label">Rule trace · {failing.length} failing of {run.trace.length}</p>
        <div className="mt-2"><RuleList rules={[...failing, ...run.trace.filter((r) => r.ok !== false)]} /></div>
      </section>
    </div>
  );
}
