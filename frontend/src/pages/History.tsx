import { useCallback, useEffect, useState } from "react";
import { api, DecisionPill, go, money, startNewSandbox, time } from "../lib";
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
      setMsg(clearCache ? "Reset. Extraction cache cleared, so the next runs call the model live." : "Reset. PO balances restored; history cleared.");
      setArmed(false); onDone();
    } catch (e) { setMsg((e as Error).message); }
  }
  const btn = "rounded-md px-3 py-1.5 text-xs font-medium";
  return (
    <div className="card flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4">
      <div className="min-w-0 flex-1 basis-80">
        <p className="label">{health?.sandbox ? "Your sandbox ledger" : "Demo ledger"}</p>
        <p className="mt-1 text-[12.5px] leading-snug text-muted">
          {health?.sandbox
            ? "This browser has its own copy of the POs and its own history; other reviewers don't affect it. Reset restores the seeded balances so you can replay the demo script."
            : "Restore every PO to its seeded balance and clear run history to replay the scenarios."}
        </p>
      </div>
      <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
        <input type="checkbox" className="accent-[var(--accent)]" checked={clearCache} onChange={(e) => setClearCache(e.target.checked)} />
        Also clear the extraction cache
      </label>
      {health?.reset_requires_token && (
        <input type="password" placeholder="Admin token" value={token} onChange={(e) => setToken(e.target.value)}
               className="w-40 rounded-md border border-line-strong bg-paper px-2.5 py-1.5 text-sm outline-none focus:border-ink" />
      )}
      <div className="flex gap-2">
        {!armed ? (
          <>
            <button onClick={() => setArmed(true)} className={`${btn} border border-line-strong bg-surface hover:border-ink`}>{health?.sandbox ? "Reset my sandbox…" : "Reset demo ledger…"}</button>
            {health?.sandbox && (
              <button onClick={() => { startNewSandbox(); window.location.hash = "#/"; window.location.reload(); }}
                      title="Keep this sandbox as it is and start another with fresh balances"
                      className={`${btn} text-muted hover:text-ink hover:underline`}>New sandbox</button>
            )}
          </>
        ) : (
          <>
            <button onClick={reset} className={`${btn} bg-reject text-surface hover:opacity-90`}>Confirm reset</button>
            <button onClick={() => setArmed(false)} className={`${btn} text-muted hover:underline`}>Cancel</button>
          </>
        )}
      </div>
      {msg && <p className="w-full text-[12.5px] text-ink-2">{msg}</p>}
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
    { label: "Runs", value: s?.runs ?? "—", sub: s && (s.running || s.error) ? `${s.running} running · ${s.error} failed` : "all submissions", tone: "" },
    { label: "Approved", value: s?.APPROVE ?? "—", sub: s ? `${money(s.approved_amount)} posted to POs` : "", tone: "text-approve" },
    { label: "Held for review", value: s?.HOLD ?? "—", sub: "ledger untouched", tone: "text-hold" },
    { label: "Rejected", value: s?.REJECT ?? "—", sub: "duplicates of approved invoices", tone: "text-reject" },
  ];
  const th = "label px-3 pb-2 pt-3 text-left font-medium";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-line pb-3">
        <div>
          <p className="label">{health?.sandbox ? "This sandbox" : "Default ledger"}</p>
          <h1 className="display mt-0.5 text-[28px] font-medium leading-tight">History</h1>
        </div>
        <p className="max-w-md text-[12.5px] text-muted">Every run, its decision, the rule that decided it, and what was left open on the PO afterwards.</p>
      </div>

      <div className="card grid grid-cols-2 divide-line lg:grid-cols-4 lg:divide-x [&>*:nth-child(n+3)]:border-t [&>*:nth-child(n+3)]:border-line lg:[&>*:nth-child(n+3)]:border-t-0 [&>*:nth-child(2)]:border-l [&>*:nth-child(4)]:border-l [&>*]:border-line">
        {tiles.map((t) => (
          <div key={t.label} className="px-5 py-4">
            <p className="label">{t.label}</p>
            <p className={`figure mt-1 text-[34px] font-medium leading-none ${t.tone}`}>{t.value}</p>
            <p className="mt-1.5 text-[12px] text-muted">{t.sub}</p>
          </div>
        ))}
      </div>

      <Reset health={health} onDone={load} />

      <section className="card min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
          <p className="label">Runs</p>
          <div className="flex gap-1">
            {FILTERS.map((f) => (
              <button key={f.label} onClick={() => setFilter(f.key)}
                      className={`rounded-md px-2.5 py-1 text-[12px] font-medium ${filter === f.key ? "bg-ink text-paper" : "text-muted hover:bg-sunken hover:text-ink"}`}>
                {f.label}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[880px] text-[13px]">
            <thead>
              <tr>
                {["Run", "When", "Vendor", "Invoice", "Invoice total", "PO", "Decision", "Deciding rule", "PO open after", "Read"].map((h, i) => (
                  <th key={h} className={`${th} ${[4, 8].includes(i) ? "text-right" : ""}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.runs.map((r) => (
                <tr key={r.id} onClick={() => go(`#/run/${r.id}`)} className="cursor-pointer border-t border-line hover:bg-sunken">
                  <td className="num px-3 py-2.5 font-mono font-medium">#{r.id}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-[12px] text-muted">{time(r.started_at)}</td>
                  <td className="max-w-44 truncate px-3 py-2.5">{r.vendor_name ?? <span className="text-faint">—</span>}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[12px]">{r.invoice_number ?? r.filename}</td>
                  <td className="num whitespace-nowrap px-3 py-2.5 text-right font-mono text-[12.5px]">{money(r.total, r.currency)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[12px]">{r.po_id ?? <span className="text-faint">—</span>}{r.po_method === "inferred" && <span className="ml-1 font-sans text-[11px] text-muted">(inferred)</span>}</td>
                  <td className="px-3 py-2.5">
                    {r.status === "done" ? <DecisionPill decision={r.decision} small /> :
                      <span className={`font-mono text-[11px] ${r.status === "error" ? "text-reject" : "text-info"}`}>{r.status === "error" ? "failed" : "running…"}</span>}
                  </td>
                  <td className="max-w-56 px-3 py-2.5"><code className="font-mono text-[11px] text-ink-2" title={r.deciding_message ?? r.error ?? ""}>{r.deciding_rule ?? (r.status === "done" ? <span className="text-muted">all checks passed</span> : "")}</code></td>
                  <td className="num whitespace-nowrap px-3 py-2.5 text-right">
                    <span className="figure text-[15px]">{money(r.balance_after)}</span>
                    {r.balance_before && r.balance_before === r.balance_after && <span className="ml-1.5 font-mono text-[10px] text-muted">unchanged</span>}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[10.5px] text-muted">{r.extraction_cached === null ? "—" : r.extraction_cached ? "cache" : "live"}</td>
                </tr>
              ))}
              {data && data.runs.length === 0 && (
                <tr><td colSpan={10} className="px-3 py-12 text-center text-[14px] text-muted">No runs yet. <a href="#/" className="text-ink underline underline-offset-2">Run the demo script</a>.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
