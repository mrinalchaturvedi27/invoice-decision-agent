import { useState } from "react";
import { inSandbox, money } from "../lib";
import type { Snapshot } from "../types";

export default function Extraction({ snap }: { snap: Snapshot }) {
  const [showPdf, setShowPdf] = useState(true);
  const step = snap.steps.filter((s) => s.stage === "extract").at(-1);
  const ext = step?.detail?.extraction;
  const checks = snap.steps.filter((s) => s.stage === "checks").at(-1);

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="card min-w-0 p-5">
        <div className="flex items-baseline justify-between">
          <p className="label">What the model read</p>
          {checks?.detail?.source && <span className="text-[11px] text-slate-500">verified against: {checks.detail.source}</span>}
        </div>
        {!ext ? (
          <p className="mt-2 text-sm text-slate-500">{step?.status === "error" ? "Extraction failed." : "Waiting for extraction…"}</p>
        ) : (
          <>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
              {([
                ["Vendor", ext.vendor_name], ["Invoice no.", ext.invoice_number], ["Date", ext.invoice_date],
                ["PO printed", ext.po_references?.join(", ") || "none"], ["Bank last 4", ext.bank_account_last4],
                ["Tax treatment", ext.tax_treatment],
              ] as [string, string | null][]).map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="text-[11px] text-slate-500">{k}</dt>
                  <dd className="truncate font-medium">{v ?? "—"}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-slate-500">
                  <tr><th className="py-1 pr-2 font-medium">Item</th><th className="pr-2 font-medium">Description</th>
                    <th className="pr-2 text-right font-medium">Qty</th><th className="pr-2 text-right font-medium">Unit</th>
                    <th className="text-right font-medium">Amount</th></tr>
                </thead>
                <tbody className="num">
                  {ext.line_items.map((l: any, i: number) => (
                    <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="py-1 pr-2 font-mono">{l.sku ?? "—"}</td><td className="pr-2">{l.description}</td>
                      <td className="pr-2 text-right">{l.quantity ?? "—"}</td><td className="pr-2 text-right">{money(l.unit_price)}</td>
                      <td className="text-right">{money(l.amount)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="num">
                  <tr className="border-t border-slate-200 dark:border-slate-700"><td colSpan={4} className="py-1 text-right text-slate-500">Subtotal</td><td className="text-right">{money(ext.subtotal)}</td></tr>
                  <tr><td colSpan={4} className="text-right text-slate-500">Tax</td><td className="text-right">{money(ext.tax)}</td></tr>
                  <tr><td colSpan={4} className="text-right font-semibold">Total</td><td className="text-right font-semibold">{money(ext.total)}</td></tr>
                </tfoot>
              </table>
            </div>
            {ext.evidence?.length > 0 && (
              <details className="mt-4">
                <summary className="cursor-pointer text-xs font-medium text-slate-600 dark:text-slate-300">Page evidence ({ext.evidence.length})</summary>
                <ul className="mt-2 space-y-1">
                  {ext.evidence.map((e: any, i: number) => (
                    <li key={i} className="text-xs">
                      <code className="font-mono text-[11px] text-slate-500">{e.field}</code> · p.{e.page} ·{" "}
                      <span className="rounded bg-yellow-100 px-1 font-mono text-[11px] dark:bg-yellow-500/20">{e.snippet}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {ext.unreadable_fields?.length > 0 && <p className="mt-2 text-xs text-amber-700">Unreadable: {ext.unreadable_fields.join(", ")}</p>}
            {ext.notes && <p className="mt-2 text-xs text-slate-500">Model note: {ext.notes}</p>}
          </>
        )}
      </section>
      <section className="card min-w-0 p-5">
        <div className="flex items-baseline justify-between">
          <p className="label">Source document</p>
          <button onClick={() => setShowPdf(!showPdf)} className="text-xs text-slate-500 hover:underline">{showPdf ? "Hide" : "Show"}</button>
        </div>
        <p className="mt-1 truncate text-xs text-slate-500">{snap.invoice.filename} · {snap.invoice.pages} page(s) · {snap.invoice.has_text_layer ? "text layer present" : "image only (scan)"}</p>
        {showPdf && <iframe title="Invoice PDF" src={inSandbox(`/api/invoices/${snap.invoice.id}/pdf#view=FitH`)} className="mt-3 h-[560px] w-full rounded-lg border border-slate-200 bg-white dark:border-slate-700" />}
      </section>
    </div>
  );
}
