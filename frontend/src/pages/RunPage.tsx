import { useState } from "react";
import DecisionPanel from "../components/DecisionPanel";
import Extraction from "../components/Extraction";
import Submit from "../components/Submit";
import Timeline from "../components/Timeline";
import { api, time, useRunStream } from "../lib";
import type { Health } from "../types";

function RunDetail({ runId }: { runId: number }) {
  const snap = useRunStream(runId);
  const [retrying, setRetrying] = useState(false);
  if (!snap) return <div className="card p-6 text-sm text-muted">Loading run #{runId}…</div>;
  const { run } = snap;
  const live = run.status === "running" || run.status === "queued";
  const statusText = { queued: "Queued", running: "Running live", done: "Finished", error: "Failed" }[run.status];

  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
        <div className="min-w-0">
          <p className="label">Run #{run.id}{snap.vendor ? ` · ${snap.vendor.name}` : ""}</p>
          <h1 className="display mt-0.5 truncate text-[28px] font-medium leading-tight">
            {snap.invoice.invoice_number ?? snap.invoice.filename}
          </h1>
          <p className="mt-0.5 text-[12px] text-muted">
            Started {time(run.started_at)}{run.finished_at && ` · finished ${time(run.finished_at)}`}
            {run.attempts > 1 && ` · attempt ${run.attempts}`}
            {snap.other_runs_of_invoice.length > 0 && <> · same file also in {snap.other_runs_of_invoice.map((o, i) => (
              <a key={o.id} href={`#/run/${o.id}`} className="underline underline-offset-2">{i ? ", " : ""}#{o.id}</a>))}</>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10.5px] font-medium uppercase tracking-wider ${live
            ? "border-info/40 bg-info-bg text-info" : run.status === "error" ? "border-reject/40 bg-reject-bg text-reject" : "border-line bg-surface text-muted"}`}>
            {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-info" />}
            {statusText}
          </span>
          {run.status === "error" && (
            <button disabled={retrying} className="rounded-md bg-ink px-3 py-1.5 text-xs font-medium text-paper disabled:opacity-60"
                    onClick={async () => { setRetrying(true); await api(`/api/runs/${run.id}/retry`, { method: "POST" }).catch(() => undefined); window.location.reload(); }}>
              Retry run
            </button>
          )}
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <Timeline snap={snap} />
        <DecisionPanel snap={snap} />
      </div>
      <Extraction snap={snap} />
    </div>
  );
}

function Welcome() {
  const steps = [
    ["Read", "Claude transcribes the PDF, with page evidence for every number the decision uses."],
    ["Verify", "Arithmetic, the PDF's own text layer, vendor master, duplicates, PO ownership and lines."],
    ["Decide", "Named rules approve, hold or reject. An approval posts to the PO ledger in one transaction."],
  ];
  return (
    <div className="card overflow-hidden">
      <div className="border-b border-line px-8 py-10 sm:px-10">
        <p className="label">Accounts payable · PO-backed invoice decisions</p>
        <h1 className="display mt-3 max-w-2xl text-[34px] font-medium leading-[1.1] sm:text-[40px]">
          Upload an invoice. Watch it get read, checked against the PO, and approved or held with a reason.
        </h1>
        <p className="mt-4 max-w-xl text-[14.5px] leading-relaxed text-ink-2">
          Start with scenario <span className="font-mono">E1·A</span>: a ₹20,000 partial bill against a ₹48,000 PO. Then run
          <span className="font-mono"> E1·B</span>, a ₹30,000 bill against the ₹28,000 that's left. Keep an eye on PO-1042 in the ledger strip above.
        </p>
      </div>
      <ol className="grid divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {steps.map(([t, d], i) => (
          <li key={t} className="px-8 py-6 sm:px-6">
            <p className="font-mono text-[11px] text-faint">0{i + 1}</p>
            <p className="display mt-1 text-[19px] font-medium">{t}</p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{d}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function RunPage({ runId, health }: { runId: number | null; health: Health | null }) {
  return (
    <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
      <div className={runId ? "order-2 lg:order-1" : ""}><Submit activeRunId={runId} health={health} /></div>
      <div className="order-1 min-w-0 lg:order-2">{runId ? <RunDetail key={runId} runId={runId} /> : <Welcome />}</div>
    </div>
  );
}
