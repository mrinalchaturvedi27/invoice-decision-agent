import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, DecisionPill, go, passcode, setPasscode } from "../lib";
import type { Health, Sample } from "../types";

export default function Submit({ activeRunId, health }: { activeRunId: number | null; health: Health | null }) {
  const [code, setCode] = useState(passcode());
  const [draft, setDraft] = useState("");
  const locked = !!health?.passcode_required && !code;
  const [samples, setSamples] = useState<Sample[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  // Re-read which steps have run in this sandbox whenever the selected run changes, and while runs are going.
  useEffect(() => {
    const load = () => api<Sample[]>("/api/samples").then(setSamples).catch((e) => setError(e.message));
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [activeRunId]);
  const nextId = samples.find((s) => !s.runs.some((r) => r.decision))?.id;   // first step without a recorded decision
  const groups = useMemo(() => {
    const g = new Map<string, Sample[]>();
    samples.forEach((s) => g.set(s.group, [...(g.get(s.group) ?? []), s]));
    return [...g.entries()];
  }, [samples]);

  async function start(key: string, req: () => Promise<{ run_id: number }>) {
    setBusy(key); setError(null);
    try { go(`#/run/${(await req()).run_id}`); }
    catch (e) {
      if (e instanceof ApiError && e.status === 401) { setPasscode(""); setCode(""); setError("That passcode wasn't accepted."); }
      else setError((e as Error).message);
    }
    finally { setBusy(null); }
  }

  function upload(file: File | undefined) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    start("upload", () => api("/api/runs", { method: "POST", body }));
  }

  return (
    <aside className="space-y-4">
      {locked && (
        <form className="card p-4" onSubmit={(e) => { e.preventDefault(); const v = draft.trim(); if (v) { setPasscode(v); setCode(v); setError(null); } }}>
          <p className="label">Reviewer passcode</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Each run calls Claude, so running invoices needs the passcode that came with this link. Reading runs and history doesn't.
          </p>
          <div className="mt-2 flex gap-2">
            <input type="password" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Passcode" autoComplete="off"
                   className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-transparent px-2 py-1.5 text-sm dark:border-slate-700" />
            <button className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white dark:bg-white dark:text-slate-900">Unlock</button>
          </div>
        </form>
      )}
      <div
        aria-disabled={locked}
        className={`card cursor-pointer border-dashed p-5 ${locked ? "pointer-events-none opacity-50" : ""} text-center transition ${drag ? "border-slate-900 bg-slate-100 dark:border-white dark:bg-slate-800" : "hover:border-slate-400"}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]); }}
      >
        <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden"
               onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
        <svg viewBox="0 0 24 24" className="mx-auto h-7 w-7 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <p className="mt-2 text-sm font-medium">{busy === "upload" ? "Uploading…" : "Upload an invoice PDF"}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">Drop a file here or click to choose · native or scanned</p>
      </div>
      <p className="-mt-2 px-1 text-[11px] leading-snug text-slate-500 dark:text-slate-400">
        <span className="font-semibold text-slate-600 dark:text-slate-300">Your sandbox:</span> this browser has its own ledger
        and history. There are no accounts, so anyone holding the sandbox id could read it. Use synthetic invoices only.
      </p>

      {error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-300">{error}</p>}

      <div className="card p-4">
        <div className="flex items-baseline justify-between">
          <p className="label">Prepared scenarios</p>
          <a href="#/history" className="text-xs text-slate-500 underline-offset-2 hover:underline">Reset in History</a>
        </div>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Run top to bottom. Each step expects the ledger the steps above it left. Steps already run in your
          sandbox show their actual result; reset in History to replay from the seed.
        </p>
        <div className="mt-3 space-y-4">
          {groups.map(([group, items]) => (
            <div key={group}>
              <p className="mb-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300">{group}</p>
              <ul className="space-y-1">
                {items.map((s) => {
                  const last = s.runs.at(-1);
                  const differs = last?.decision && last.decision !== s.expected_decision;
                  return (
                  <li key={s.id}>
                    <button
                      disabled={!!busy || locked}
                      onClick={() => start(s.id, () => api(`/api/runs/sample/${s.id}`, { method: "POST" }))}
                      className={`group flex w-full items-start justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-100 disabled:opacity-60 dark:hover:bg-slate-800 ${s.id === nextId ? "ring-1 ring-slate-300 dark:ring-slate-600" : ""}`}
                    >
                      <span className={last ? "text-slate-500 dark:text-slate-400" : ""}>
                        {busy === s.id ? "Starting…" : s.label}
                        {s.scan && <span className="ml-1.5 rounded bg-slate-200 px-1 py-px text-[10px] font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-300">SCAN</span>}
                        {s.id === nextId && <span className="ml-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">next</span>}
                      </span>
                      <span className="shrink-0 opacity-70 group-hover:opacity-100" title={`Expected: ${s.expected_decision}${s.expected_rule ? " · " + s.expected_rule : ""}`}>
                        <DecisionPill decision={s.expected_decision} small />
                      </span>
                    </button>
                    {last && (
                      <a href={`#/run/${last.id}`}
                         className={`block px-2 pb-1 text-[11px] underline-offset-2 hover:underline ${differs ? "text-amber-700 dark:text-amber-300" : "text-slate-500 dark:text-slate-400"}`}>
                        ran{s.runs.length > 1 ? ` ${s.runs.length}×` : ""} here · run #{last.id} → {last.decision ?? last.status}
                        {differs && " · not the expected result (out of order, or run twice?)"}
                      </a>
                    )}
                  </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-slate-400">Pills show the expected outcome when the steps are run in order from a fresh sandbox.</p>
      </div>
      {health && health.model_calls.used >= health.model_calls.limit * 0.8 && (
        <p className="px-1 text-[11px] text-amber-700 dark:text-amber-300">
          Model calls today: {health.model_calls.used} of {health.model_calls.limit}. At the limit, new invoices can't be read until the 24-hour window frees up.
        </p>
      )}
      {activeRunId && <a href="#/" className="block text-center text-xs text-slate-500 hover:underline">Clear selection</a>}
    </aside>
  );
}
