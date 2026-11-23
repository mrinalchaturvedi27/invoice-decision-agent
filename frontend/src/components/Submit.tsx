import { useEffect, useMemo, useRef, useState } from "react";
import { api, DecisionPill, go } from "../lib";
import type { Health, Sample } from "../types";

/** Short step tag: the group's code plus the step's position, e.g. E1·A, E2·C; a lone step keeps its id (X1). */
function tag(group: string, items: Sample[], i: number): string {
  const code = group.match(/^E\d+/)?.[0];
  if (!code || items.length === 1) return items[i].id.toUpperCase();
  return `${code}·${String.fromCharCode(65 + i)}`;
}

export default function Submit({ activeRunId, health }: { activeRunId: number | null; health: Health | null }) {
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
    catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  }

  function upload(file: File | undefined) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    start("upload", () => api("/api/runs", { method: "POST", body }));
  }

  return (
    <aside className="space-y-4 lg:sticky lg:top-[126px] lg:max-h-[calc(100vh-142px)] lg:overflow-y-auto lg:pr-1">
      <div
        role="button" tabIndex={0}
        className={`group rounded-[10px] border-[1.5px] border-dashed px-5 py-6 text-center transition cursor-pointer
          ${drag ? "border-accent bg-approve-bg" : "border-line-strong bg-surface hover:border-ink/60"}`}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") input.current?.click(); }}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]); }}
      >
        <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden"
               onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
        <svg viewBox="0 0 24 24" className="mx-auto h-7 w-7 text-muted transition group-hover:text-ink" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M7 3h7l5 5v13H7z" strokeLinejoin="round" /><path d="M14 3v5h5" strokeLinejoin="round" />
          <path d="M12 17v-6m0 0-2.5 2.5M12 11l2.5 2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <p className="display mt-2 text-[17px] font-medium">{busy === "upload" ? "Uploading…" : "Upload an invoice PDF"}</p>
        <p className="mt-0.5 text-[12px] text-muted">Drop it here or click to choose · native or scanned</p>
      </div>
      <p className="-mt-1.5 px-1 text-[11.5px] leading-snug text-muted">
        <span className="font-semibold text-ink-2">Your sandbox:</span> this browser has its own ledger and history. There are no
        accounts, so anyone holding the sandbox id could read it. Use synthetic invoices only.
      </p>

      {error && <p className="rounded-md border border-reject/40 bg-reject-bg px-3 py-2 text-[13px] text-reject">{error}</p>}

      <section className="card">
        <div className="flex items-baseline justify-between border-b border-line px-4 pb-2.5 pt-3.5">
          <p className="label">Demo script</p>
          <a href="#/history" className="font-mono text-[10.5px] text-muted underline-offset-2 hover:text-ink hover:underline">reset in history</a>
        </div>
        <p className="px-4 pt-2.5 text-[12px] leading-snug text-muted">
          Run top to bottom. Each step expects the ledger the steps above it left behind.
        </p>
        <div className="space-y-3 px-2 pb-3 pt-2">
          {groups.map(([group, items]) => (
            <div key={group}>
              <p className="px-2 pb-1 pt-1.5 text-[12px] font-semibold text-ink-2">{group}</p>
              <ul>
                {items.map((s, i) => {
                  const last = s.runs.at(-1);
                  const ran = !!last?.decision;
                  const differs = last?.decision && last.decision !== s.expected_decision;
                  const isNext = s.id === nextId;
                  return (
                    <li key={s.id} className={`rounded-md ${isNext ? "bg-sunken ring-1 ring-line-strong" : ""}`}>
                      <button
                        disabled={!!busy}
                        onClick={() => start(s.id, () => api(`/api/runs/sample/${s.id}`, { method: "POST" }))}
                        title={`Expected: ${s.expected_decision}${s.expected_rule ? " · " + s.expected_rule : ""}`}
                        className="group grid w-full grid-cols-[44px_minmax(0,1fr)_auto] items-start gap-2 rounded-md px-2 py-2 text-left hover:bg-sunken disabled:cursor-not-allowed disabled:opacity-55"
                      >
                        <span className="pt-px">
                          <span className={`block font-mono text-[11px] font-semibold ${ran ? "text-muted" : "text-ink"}`}>
                            {tag(group, items, i)}{ran && <span className="ml-0.5 text-approve">✓</span>}
                          </span>
                          {isNext && <span className="block font-mono text-[9px] font-semibold uppercase tracking-wider text-accent">next</span>}
                        </span>
                        <span className={`text-[13px] leading-snug ${ran ? "text-muted" : ""}`}>
                          {busy === s.id ? "Starting…" : s.label}
                          {s.scan && <span className="ml-1.5 rounded-sm border border-line-strong px-1 font-mono text-[9px] text-muted">SCAN</span>}
                        </span>
                        <span className="pt-0.5 opacity-80 group-hover:opacity-100"><DecisionPill decision={s.expected_decision} small /></span>
                      </button>
                      {last && (
                        <a href={`#/run/${last.id}`}
                           className={`block pb-2 pl-[62px] pr-2 font-mono text-[10.5px] underline-offset-2 hover:underline ${differs ? "text-hold" : "text-muted"}`}>
                          ran{s.runs.length > 1 ? ` ${s.runs.length}×` : ""} · run #{last.id} → {last.decision ?? last.status}
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
        <p className="border-t border-line px-4 py-2.5 text-[11px] text-faint">Stamps show the expected outcome from a fresh sandbox, run in order.</p>
      </section>
      {health && health.model_calls.used >= health.model_calls.limit * 0.8 && (
        <p className="px-1 text-[11.5px] text-hold">
          Model calls today: {health.model_calls.used} of {health.model_calls.limit}. At the limit, new invoices can't be read until the 24-hour window frees up.
        </p>
      )}
      {activeRunId && <a href="#/" className="block text-center font-mono text-[11px] text-muted hover:text-ink hover:underline">clear selection</a>}
    </aside>
  );
}
