import { DECISION_STYLE, money, Stamp } from "../lib";
import type { Snapshot } from "../types";
import { RuleList } from "./Timeline";

function LedgerEntry({ snap }: { snap: Snapshot }) {
  const { run, po } = snap;
  if (!po) return null;
  const before = run.balance_before, after = run.balance_after;
  const posted = before !== null && after !== null ? Number(before) - Number(after) : 0;
  const row = "grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-4 py-1.5";
  return (
    <div className="mt-3">
      <div className={row}>
        <span className="text-[13px] text-muted">Open before this invoice</span>
        <span className="figure text-[20px]">{money(before)}</span>
      </div>
      <div className={row}>
        <span className="text-[13px] text-muted">{posted > 0 ? "Posted by this invoice" : "Posted"}</span>
        <span className={`figure text-[20px] ${posted > 0 ? "text-approve" : "text-faint"}`}>{posted > 0 ? `− ${money(posted)}` : money(0)}</span>
      </div>
      <div className={`${row} double-rule mt-1 pt-2`}>
        <span className="text-[13px] font-semibold">Open after</span>
        <span className="figure text-[26px] font-semibold">{money(after)}</span>
      </div>
      <p className="mt-2 text-[12px] text-muted">
        {posted > 0 ? `${money(posted)} allocated to ${po.id}.` : "Nothing was posted. The ledger is untouched."}
        {" "}Open on {po.id} right now: <span className="num font-medium text-ink">{money(po.open_now)}</span>
      </p>
    </div>
  );
}

export default function DecisionPanel({ snap }: { snap: Snapshot }) {
  const { run, po, linked } = snap;
  const failing = run.trace.filter((r) => r.ok === false);
  const poStep = snap.steps.filter((s) => s.stage === "po").at(-1);
  const inference = poStep?.detail?.method === "inferred" ? poStep.detail : null;

  if (run.status === "error" && !run.decision) {
    return (
      <section className="card border-reject/40 p-5">
        <p className="label text-reject">Run failed · no decision made</p>
        <p className="mt-2 text-[14px] leading-relaxed">{run.error}</p>
        <p className="mt-2 text-[12px] text-muted">The ledger was not touched. Fix the cause and retry; a retry reuses this run.</p>
      </section>
    );
  }
  if (!run.decision) {
    return (
      <section className="card p-5">
        <p className="label">Decision</p>
        <p className="mt-3 flex items-center gap-2.5 text-[14px] text-muted">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-faint border-t-transparent" /> Working through the checks…
        </p>
      </section>
    );
  }

  const st = DECISION_STYLE[run.decision];
  const fresh = run.status === "running";

  return (
    <div className="min-w-0 space-y-4">
      <section className={`overflow-hidden rounded-[10px] border ${st.border} bg-surface`}>
        <div className={`flex flex-wrap items-center justify-between gap-3 border-b ${st.border} ${st.bg} px-5 py-4`}>
          <div className="min-w-0">
            <p className="label">Decision</p>
            <p className={`display mt-0.5 text-[24px] font-medium leading-tight ${st.tone}`}>{st.word}</p>
            {run.deciding_rule && <code className="mt-1 inline-block font-mono text-[11.5px] text-ink-2">{run.deciding_rule}</code>}
          </div>
          <Stamp decision={run.decision} animate={fresh} />
        </div>

        <div className="px-5 py-4">
          {run.deciding_message && run.decision !== "APPROVE" && !run.explanation && (
            <p className="text-[14px] leading-relaxed">{run.deciding_message}</p>
          )}
          {run.explanation ? (
            <>
              <p className="text-[14.5px] leading-relaxed text-ink">{run.explanation}</p>
              <p className="mt-2 font-mono text-[10.5px] text-faint">
                {run.explanation_source === "claude" ? "summary written by Claude from the rule trace" : "summary built from the rule trace"} · decided by policy {run.policy_version}
              </p>
            </>
          ) : run.status === "error" ? (
            <p className="mt-2 text-[12.5px] text-reject">
              The decision {run.decision === "APPROVE" ? "and its ledger posting were" : "was"} recorded before the run failed. Retrying only writes the summary; it won't re-decide.
            </p>
          ) : (
            <p className="mt-2 flex items-center gap-2 text-[12.5px] text-muted">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-faint border-t-transparent" />
              Decision recorded{run.decision === "APPROVE" ? " and posted" : ""} · writing the summary…
            </p>
          )}

          {snap.next_step && (
            <div className={`mt-4 border-l-[3px] ${run.decision === "REJECT" ? "border-reject" : "border-hold"} bg-sunken py-2.5 pl-3.5 pr-3`}>
              <p className="label">Next step for AP</p>
              <p className="mt-1 text-[14.5px] font-medium leading-snug">{snap.next_step}</p>
            </div>
          )}
        </div>
      </section>

      <section className="card p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="label">PO ledger</p>
          {po && <span className="font-mono text-[10.5px] text-muted">{run.po_method === "inferred" ? "PO inferred (none printed)" : "PO printed on invoice"}</span>}
        </div>
        {po ? (
          <>
            <p className="mt-2 text-[14px]">
              <span className="font-mono font-semibold">{po.id}</span>
              <span className="text-muted"> · {po.description} · {money(po.total)} ordered</span>
            </p>
            <LedgerEntry snap={snap} />
            {po.allocations.length > 0 && (
              <div className="mt-4 border-t border-line pt-3">
                <p className="label mb-1.5">Postings against {po.id}</p>
                <ul className="space-y-1 text-[12.5px]">
                  {po.allocations.map((a, i) => (
                    <li key={i} className="flex justify-between gap-2">
                      <a href={`#/run/${a.run_id}`} className={`hover:underline ${a.run_id === run.id ? "font-semibold" : "text-ink-2"}`}>
                        <span className="font-mono">{a.invoice_number}</span> · run #{a.run_id}{a.run_id === run.id ? " (this run)" : ""}
                      </a>
                      <span className="num font-mono">{money(a.amount)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className="mt-2 text-[14px] text-muted">No PO resolved, so nothing was compared or posted.</p>
        )}
        {inference?.candidates?.length > 0 && (
          <div className="mt-4 border-t border-line pt-3">
            <p className="mb-2 text-[12px] text-muted">
              No PO printed. Candidates among this vendor's open POs; one is accepted only with score ≥ {inference.thresholds.min_score} and
              a lead ≥ {inference.thresholds.min_lead} (lead here: <span className="num font-medium text-ink">{inference.lead}</span>).
            </p>
            <table className="w-full text-[12.5px]">
              <thead><tr className="text-left">
                {["PO", "Purpose", "Open", "Score"].map((h, i) => <th key={h} className={`label pb-1 font-medium ${i > 1 ? "text-right" : ""}`}>{h}</th>)}
              </tr></thead>
              <tbody className="num">
                {inference.candidates.map((c: any, i: number) => (
                  <tr key={c.po_id} className={`border-t border-line ${i < 2 ? "" : "text-muted"}`}>
                    <td className="py-1.5 font-mono">{c.po_id}</td><td>{c.description}</td>
                    <td className="text-right font-mono">{money(c.open_balance)}</td>
                    <td className="text-right font-mono font-medium">{Number(c.score).toFixed(2)}</td>
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
          <p className="mt-2 text-[14px]">
            <span className="font-mono">{linked.invoice_number}</span> · {linked.invoice_date} · <span className="num">{money(linked.total)}</span>
            {linked.approved_run_id && (<> · approved in <a className="font-medium underline underline-offset-2" href={`#/run/${linked.approved_run_id}`}>run #{linked.approved_run_id}</a></>)}
          </p>
        </section>
      )}

      <section className="card p-5">
        <p className="label">Rule trace · {failing.length} failing of {run.trace.length}</p>
        <div className="mt-3"><RuleList rules={[...failing, ...run.trace.filter((r) => r.ok !== false)]} /></div>
      </section>
    </div>
  );
}
