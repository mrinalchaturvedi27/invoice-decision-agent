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

export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("X-Workspace", SANDBOX);
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not json */ }
    throw new ApiError(detail, r.status);
  }
  return r.json();
}

export function go(hash: string) { window.location.hash = hash; }

export function money(v: string | number | null | undefined, currency: string | null = "INR"): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(n)) return String(v);
  if (!currency || !/^[A-Z]{3}$/.test(currency)) return n.toLocaleString("en-IN", { minimumFractionDigits: 2 });
  return n.toLocaleString("en-IN", { style: "currency", currency, currencyDisplay: currency === "INR" ? "symbol" : "code" });
}

export function time(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export const DECISION_STYLE: Record<Decision, { tone: string; bg: string; border: string; stamp: string; word: string }> = {
  APPROVE: { tone: "text-approve", bg: "bg-approve-bg", border: "border-approve/40", stamp: "Approved", word: "Approved for payment" },
  HOLD: { tone: "text-hold", bg: "bg-hold-bg", border: "border-hold/40", stamp: "On hold", word: "Held for review" },
  REJECT: { tone: "text-reject", bg: "bg-reject-bg", border: "border-reject/40", stamp: "Rejected", word: "Rejected" },
};

/** Small inline stamp for lists and tables. */
export function DecisionPill({ decision, small }: { decision: Decision | null; small?: boolean }) {
  if (!decision) return <span className="font-mono text-[11px] text-faint">—</span>;
  const st = DECISION_STYLE[decision];
  return <span className={`stamp stamp-sm ${small ? "text-[9.5px]" : "text-[11px]"} ${st.tone}`}>{st.stamp}</span>;
}

/** The decision stamp on a run. */
export function Stamp({ decision, animate }: { decision: Decision; animate?: boolean }) {
  const st = DECISION_STYLE[decision];
  return <span className={`stamp text-[13px] ${st.tone} ${animate ? "stamp-in" : ""}`}>{st.stamp}</span>;
}

export interface PoBalance { id: string; vendor: string; description: string; status: string; total: string; open_balance: string }

/** Live open balance of every PO in this sandbox; ids whose balance just changed are returned in `changed`. */
export function usePoBalances(intervalMs = 2500): { pos: PoBalance[]; changed: Set<string> } {
  const [pos, setPos] = useState<PoBalance[]>([]);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  useEffect(() => {
    let prev: Record<string, string> | null = null;
    let alive = true;
    const load = () => api<PoBalance[]>("/api/pos").then((next) => {
      if (!alive) return;
      if (prev) {
        const diff = new Set(next.filter((p) => prev![p.id] !== undefined && prev![p.id] !== p.open_balance).map((p) => p.id));
        if (diff.size) { setChanged(diff); setTimeout(() => alive && setChanged(new Set()), 1900); }
      }
      prev = Object.fromEntries(next.map((p) => [p.id, p.open_balance]));
      setPos(next);
    }).catch(() => undefined);
    load();
    const t = setInterval(load, intervalMs);
    return () => { alive = false; clearInterval(t); };
  }, [intervalMs]);
  return { pos, changed };
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
