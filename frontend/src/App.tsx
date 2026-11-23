import { useEffect, useState } from "react";
import { money, useHealth, usePoBalances } from "./lib";
import History from "./pages/History";
import RunPage from "./pages/RunPage";

type Route = { page: "run"; runId: number | null } | { page: "history" };

function parse(hash: string): Route {
  if (hash.startsWith("#/history")) return { page: "history" };
  const m = hash.match(/^#\/run\/(\d+)/);
  return { page: "run", runId: m ? Number(m[1]) : null };
}

function Mark() {
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8 shrink-0" aria-hidden>
      <rect width="32" height="32" rx="7" className="fill-accent" />
      <path d="M9 7h14v18l-3.5-2-3.5 2-3.5-2L9 25z" className="fill-surface" />
      <path d="M12.5 12h7M12.5 15.5h7M12.5 19h4" className="stroke-accent" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** Every PO's open balance, live. Watching PO-1042 fall from $48,000 to $28,000 is the point of the demo. */
function LedgerStrip() {
  const { pos, changed } = usePoBalances();
  if (!pos.length) return null;
  return (
    <div className="border-t border-line bg-surface/80">
      <div className="mx-auto flex max-w-[1400px] items-stretch gap-0 overflow-x-auto px-4 sm:px-6">
        <span className="label flex shrink-0 items-center pr-4">PO ledger · open</span>
        {pos.map((p) => {
          const total = Number(p.total), open = Number(p.open_balance);
          const used = total > 0 ? Math.min(1, Math.max(0, 1 - open / total)) : 0;
          return (
            <div key={p.id} title={`${p.id} · ${p.vendor} · ${p.description}`}
                 className={`flex shrink-0 flex-col justify-center border-l border-line px-3 py-1.5 ${changed.has(p.id) ? "flash" : ""}`}>
              <span className="flex items-baseline gap-1.5">
                <span className="font-mono text-[10.5px] text-muted">{p.id}</span>
                <span className={`figure text-[15px] font-medium ${open === 0 ? "text-faint" : ""}`}>{money(p.open_balance)}</span>
              </span>
              <span className="mt-1 block h-[3px] w-full overflow-hidden rounded-full bg-sunken" aria-hidden>
                <span className="block h-full rounded-full bg-accent/70" style={{ width: `${used * 100}%` }} />
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(parse(window.location.hash));
  const health = useHealth();
  useEffect(() => {
    const f = () => { setRoute(parse(window.location.hash)); window.scrollTo({ top: 0 }); };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);

  const tab = (active: boolean) =>
    `relative px-1 py-1 text-sm font-medium transition ${active ? "text-ink after:absolute after:inset-x-0 after:-bottom-[13px] after:h-[2px] after:bg-ink" : "text-muted hover:text-ink"}`;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <a href="#/" className="flex min-w-0 items-center gap-3">
            <Mark />
            <span className="min-w-0">
              <span className="display block truncate text-[17px] font-medium leading-tight sm:text-[19px]">Invoice Decision Agent</span>
              <span className="hidden truncate text-[11.5px] text-muted sm:block">Reads the PDF · checks the PO · posts to the ledger, or holds with a reason</span>
            </span>
          </a>
          <nav className="flex shrink-0 gap-5">
            <a href="#/" className={tab(route.page === "run")}>Run</a>
            <a href="#/history" className={tab(route.page === "history")}>History</a>
          </nav>
        </div>
        <LedgerStrip />
      </header>
      {health && !health.model_credentials && (
        <div className="border-b border-hold/40 bg-hold-bg px-4 py-2 text-center text-sm text-hold">
          No Anthropic API key is configured on the server, so new invoices can't be read. Invoices already in the extraction cache still run.
        </div>
      )}
      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
        {route.page === "history" ? <History health={health} /> : <RunPage runId={route.runId} health={health} />}
      </main>
      <footer className="mx-auto max-w-[1400px] border-t border-line px-4 py-5 text-[11.5px] text-muted sm:px-6">
        <span className="font-mono">policy {health?.policy_version ?? "…"}</span>
        <span className="mx-2 text-faint">/</span>
        <span className="font-mono">{health?.extract_model ?? "…"}</span>
        <span className="mx-2 text-faint">/</span>
        Claude reads the invoice and writes the summary. Deterministic rules make every decision.
      </footer>
    </div>
  );
}
