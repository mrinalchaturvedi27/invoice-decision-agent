import { useCallback, useEffect, useState } from "react";
import { api, DecisionPill, go, money, time } from "../lib";
import type { Decision, Health, HistoryRow, Stats } from "../types";

const FILTERS: { key: Decision | null; label: string }[] = [
  { key: null, label: "All" }, { key: "APPROVE", label: "Approved" }, { key: "HOLD", label: "Held" }, { key: "REJECT", label: "Rejected" },
];

function Reset({ health, onDone }: { health: Health | null; onDone: () => void }) {
  const [armed, setArmed] = useState(false);
  const [clearCache, setClearCache] = useState(false);
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  async function reset() {
    setMsg(null);
    try {
      await api("/api/admin/reset", { method: "POST", headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
                                      body: JSON.stringify({ clear_cache: clearCache }) });
      setMsg(clearCache ? "Reset. Extraction cache cleared — the next runs call the model live." : "Reset. PO balances restored; history cleared.");
      setArmed(false); onDone();
    } catch (e) { setMsg((e as Error).message); }
  }
  return (
    <div className="card flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="label">Demo ledger</p>
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Restore every PO to its seeded balance and clear run history to replay the scenarios.</p>
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={clearCache} onChange={(e) => setClearCache(e.target.checked)} />
        Also clear the extraction cache
      </label>
      {health?.reset_requires_token && (
        <input type="password" placeholder="Admin token" value={token} onChange={(e) => setToken(e.target.value)}
               className="w-40 rounded-lg border border-slate-300 bg-transparent px-2 py-1.5 text-sm dark:border-slate-700" />
      )}
      <div className="flex gap-2">
        {!armed ? (
          <button onClick={() => setArmed(true)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">Reset demo ledger…</button>
        ) : (
          <>
            <button onClick={reset} className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700">Confirm reset</button>
            <button onClick={() => setArmed(false)} className="rounded-lg px-3 py-1.5 text-xs text-slate-500 hover:underline">Cancel</button>
          </>
        )}
      </div>
      {msg && <p className="w-full text-xs text-slate-600 dark:text-slate-300">{msg}</p>}
    </div>
  );
}

export default function History({ health }: { health: Health | null }) {
  const [filter, setFilter] = useState<Decision | null>(null);
  const [data, setData] = useState<{ runs: HistoryRow[]; stats: Stats } | null>(null);
  const load = useCallback(() => {
    api<{ runs: HistoryRow[]; stats: Stats }>(`/api/runs${filter ? `?decision=${filter}` : ""}`).then(setData).catch(() => undefined);
  }, [filter]);
  useEffect(() => { load(); const t = setInterval(load, 2500); return () => clearInterval(t); }, [load]);
  const s = data?.stats;

  const tiles = [
    { label: "Runs", value: s?.runs ?? "—", sub: s && (s.running || s.error) ? `${s.running} running · ${s.error} failed` : "all submissions" },
    { label: "Approved", value: s?.APPROVE ?? "—", sub: s ? `${money(s.approved_amount)} posted to POs` : "", tone: "text-emerald-700 dark:text-emerald-400" },
    { label: "Held for review", value: s?.HOLD ?? "—", sub: "ledger untouched", tone: "text-amber-700 dark:text-amber-400" },
    { label: "Rejected", value: s?.REJECT ?? "—", sub: "duplicates of approved", tone: "text-rose-700 dark:text-rose-400" },
  ];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="card p-4">
            <p className="label">{t.label}</p>
            <p className={`num mt-1 text-2xl font-semibold ${t.tone ?? ""}`}>{t.value}</p>
            <p className="mt-0.5 text-xs text-slate-500">{t.sub}</p>
          </div>
        ))}
      </div>

      <Reset health={health} onDone={load} />
      <div>
        <section className="card min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
            <h1 className="text-sm font-semibold">Run history</h1>
            <div className="flex gap-1">
              {FILTERS.map((f) => (
                <button key={f.label} onClick={() => setFilter(f.key)}
                        className={`rounded-md px-2.5 py-1 text-xs font-medium ${filter === f.key ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-sm">
              <thead className="text-left text-xs text-slate-500">
                <tr>
                  {["Run", "When", "Vendor", "Invoice", "Invoice total", "PO", "Decision", "Deciding rule", "PO open after", "Read"].map((h) => (
                    <th key={h} className="px-3 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data?.runs.map((r) => (
                  <tr key={r.id} onClick={() => go(`#/run/${r.id}`)} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
                    <td className="num px-3 py-2 font-medium">#{r.id}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{time(r.started_at)}</td>
                    <td className="max-w-40 truncate px-3 py-2">{r.vendor_name ?? <span className="text-slate-400">—</span>}</td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{r.invoice_number ?? r.filename}</td>
                    <td className="num whitespace-nowrap px-3 py-2">{money(r.total)}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-xs">{r.po_id ?? "—"}{r.po_method === "inferred" && <span className="ml-1 text-slate-400">(inferred)</span>}</td>
                    <td className="px-3 py-2">
                      {r.status === "done" ? <DecisionPill decision={r.decision} small /> :
                        <span className={`text-xs ${r.status === "error" ? "text-rose-600" : "text-sky-600"}`}>{r.status === "error" ? "failed" : "running…"}</span>}
                    </td>
                    <td className="max-w-56 px-3 py-2"><code className="font-mono text-[11px] text-slate-500" title={r.deciding_message ?? r.error ?? ""}>{r.deciding_rule ?? (r.status === "done" ? "all checks passed" : "")}</code></td>
                    <td className="num whitespace-nowrap px-3 py-2">
                      {money(r.balance_after)}
                      {r.balance_before && r.balance_before === r.balance_after && <span className="ml-1 text-[11px] text-slate-400">unchanged</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-500">{r.extraction_cached === null ? "—" : r.extraction_cached ? "cache" : "live"}</td>
                  </tr>
                ))}
                {data && data.runs.length === 0 && (
                  <tr><td colSpan={10} className="px-3 py-10 text-center text-sm text-slate-500">No runs yet. <a href="#/" className="underline">Submit an invoice</a>.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
