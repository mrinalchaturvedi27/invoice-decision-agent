import { useEffect, useState } from "react";
import type { Decision, Health, Snapshot } from "./types";

// Each browser gets its own demo ledger on the server, keyed by a random id kept in localStorage.
const SANDBOX_KEY = "invoice-agent-sandbox";
const SANDBOX_RE = /^[A-Za-z0-9_-]{16,64}$/;
function newId(): string {
  const a = new Uint8Array(16);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}
let SANDBOX: string = (() => {
  try {
    const v = localStorage.getItem(SANDBOX_KEY);
    if (v && SANDBOX_RE.test(v)) return v;
    const n = newId();
    localStorage.setItem(SANDBOX_KEY, n);
    return n;
  } catch { return newId(); }   // storage blocked: a sandbox for this page load only
})();
export function sandboxId(): string { return SANDBOX; }
export function startNewSandbox(): void {
  SANDBOX = newId();
  try { localStorage.setItem(SANDBOX_KEY, SANDBOX); } catch { /* page-load only */ }
}
/** For URLs the browser fetches itself (EventSource, iframe), where a header can't be set. */
export function inSandbox(path: string): string {
  const [base, hash] = path.split("#");
  return `${base}${base.includes("?") ? "&" : "?"}ws=${SANDBOX}${hash ? "#" + hash : ""}`;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("X-Workspace", SANDBOX);
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not json */ }
    throw new Error(detail);
  }
  return r.json();
}

export function go(hash: string) { window.location.hash = hash; }

export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function time(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export const DECISION_STYLE: Record<Decision, { pill: string; panel: string; word: string }> = {
  APPROVE: { pill: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
             panel: "border-emerald-300 bg-emerald-50 dark:border-emerald-500/40 dark:bg-emerald-500/10", word: "Approved" },
  HOLD: { pill: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
          panel: "border-amber-300 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-500/10", word: "Held for review" },
  REJECT: { pill: "bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-300",
            panel: "border-rose-300 bg-rose-50 dark:border-rose-500/40 dark:bg-rose-500/10", word: "Rejected" },
};

export function DecisionPill({ decision, small }: { decision: Decision | null; small?: boolean }) {
  if (!decision) return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">—</span>;
  return (
    <span className={`rounded-full font-semibold ${small ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs"} ${DECISION_STYLE[decision].pill}`}>
      {decision}
    </span>
  );
}

export function useRunStream(runId: number): Snapshot | null {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  useEffect(() => {
    setSnap(null);
    let closed = false;
    const es = new EventSource(inSandbox(`/api/runs/${runId}/stream`));
    es.onmessage = (e) => setSnap(JSON.parse(e.data));
    es.addEventListener("end", () => { closed = true; es.close(); });
    es.onerror = () => {
      es.close();
      if (!closed) api<Snapshot>(`/api/runs/${runId}`).then(setSnap).catch(() => undefined);
    };
    return () => es.close();
  }, [runId]);
  return snap;
}

export function useHealth(): Health | null {
  const [h, setH] = useState<Health | null>(null);
  useEffect(() => { api<Health>("/api/health").then(setH).catch(() => undefined); }, []);
  return h;
}
