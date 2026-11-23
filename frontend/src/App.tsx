import { useEffect, useState } from "react";
import { useHealth } from "./lib";
import History from "./pages/History";
import RunPage from "./pages/RunPage";

type Route = { page: "run"; runId: number | null } | { page: "history" };

function parse(hash: string): Route {
  if (hash.startsWith("#/history")) return { page: "history" };
  const m = hash.match(/^#\/run\/(\d+)/);
  return { page: "run", runId: m ? Number(m[1]) : null };
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
    `rounded-lg px-3 py-1.5 text-sm font-medium transition ${active
      ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
      : "text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-800"}`;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/85 backdrop-blur dark:border-slate-800 dark:bg-slate-950/85">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <a href="#/" className="flex items-center gap-2.5">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-slate-900 text-white dark:bg-white dark:text-slate-900">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor"><path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" /></svg>
            </span>
            <span>
              <span className="block text-sm font-semibold leading-tight">Invoice Decision Agent</span>
              <span className="block text-xs text-slate-500 dark:text-slate-400">PDF → verified decision → PO ledger</span>
            </span>
          </a>
          <nav className="flex gap-1">
            <a href="#/" className={tab(route.page === "run")}>Run</a>
            <a href="#/history" className={tab(route.page === "history")}>History</a>
          </nav>
        </div>
      </header>
      {health && !health.model_credentials && (
        <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
          No Anthropic API key is configured on the server, so new invoices can't be read. Invoices already in the extraction cache still run.
        </div>
      )}
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {route.page === "history" ? <History health={health} /> : <RunPage runId={route.runId} health={health} />}
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-slate-400 sm:px-6">
        Policy {health?.policy_version ?? "…"} · extraction model {health?.extract_model ?? "…"} · decisions are made by deterministic rules; the model reads and explains.
      </footer>
    </div>
  );
}
