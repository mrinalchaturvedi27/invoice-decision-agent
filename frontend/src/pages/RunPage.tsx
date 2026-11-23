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
  if (!snap) return <div className="card p-6 text-sm text-slate-500">Loading run #{runId}…</div>;
  const { run } = snap;
  const statusText = { queued: "Queued", running: "Running live", done: "Finished", error: "Failed" }[run.status];

  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold">Run #{run.id}
            <span className="ml-2 text-sm font-normal text-slate-500">{snap.invoice.invoice_number ?? snap.invoice.filename}</span>
          </h1>
          <p className="text-xs text-slate-500">
            Started {time(run.started_at)}{run.finished_at && ` · finished ${time(run.finished_at)}`}
            {run.attempts > 1 && ` · attempt ${run.attempts}`}
            {snap.other_runs_of_invoice.length > 0 && <> · same file also in {snap.other_runs_of_invoice.map((o, i) => (
              <a key={o.id} href={`#/run/${o.id}`} className="underline">{i ? ", " : ""}#{o.id}</a>))}</>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${run.status === "running" || run.status === "queued"
            ? "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300" : run.status === "error"
            ? "bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-300" : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"}`}>
            {(run.status === "running" || run.status === "queued") && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-500" />}
            {statusText}
          </span>
          {run.status === "error" && (
            <button disabled={retrying} className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60 dark:bg-white dark:text-slate-900"
                    onClick={async () => { setRetrying(true); await api(`/api/runs/${run.id}/retry`, { method: "POST" }).catch(() => undefined); window.location.reload(); }}>
              Retry run
            </button>
          )}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <Timeline snap={snap} />
        <DecisionPanel snap={snap} />
      </div>
      <Extraction snap={snap} />
    </div>
  );
}

export default function RunPage({ runId, health }: { runId: number | null; health: Health | null }) {
  return (
    <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
      <div className={runId ? "order-2 lg:order-1" : ""}><Submit activeRunId={runId} health={health} /></div>
      {runId ? <div className="order-1 min-w-0 lg:order-2"><RunDetail key={runId} runId={runId} /></div> : (
        <div className="card grid min-h-80 place-items-center p-8 text-center">
          <div className="max-w-md">
            <p className="text-base font-semibold">Submit an invoice to watch it run</p>
            <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              Each stage streams in as it executes. The decision comes from named rules, and every posting to a PO
              shows the balance before and after. Upload your own PDF or start with scenario E1·A.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
