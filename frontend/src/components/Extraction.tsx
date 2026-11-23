import { useState } from "react";
import { inSandbox, money } from "../lib";
import type { Snapshot } from "../types";

export default function Extraction({ snap }: { snap: Snapshot }) {
  const [showPdf, setShowPdf] = useState(true);
  const step = snap.steps.filter((s) => s.stage === "extract").at(-1);
  const ext = step?.detail?.extraction;
  const checks = snap.steps.filter((s) => s.stage === "checks").at(-1);
  const th = "label pb-1.5 font-medium";

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="card min-w-0 p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="label">What the model read</p>
          {checks?.detail?.source && <span className="font-mono text-[10.5px] text-muted">verified against: {checks.detail.source}</span>}
        </div>
        {!ext ? (
          <p className="mt-3 text-[14px] text-muted">{step?.status === "error" ? "Extraction failed." : "Waiting for extraction…"}</p>
        ) : (
          <>
            <dl className="mt-4 grid grid-cols-2 gap-x-5 gap-y-3 sm:grid-cols-3">
              {([
                ["Vendor", ext.vendor_name, false], ["Invoice no.", ext.invoice_number, true], ["Invoice date", ext.invoice_date, true],
                ["PO printed", ext.po_references?.join(", ") || "none", true], ["Bank, last 4", ext.bank_account_last4, true],
                ["Tax treatment", ext.tax_treatment, false],
              ] as [string, string | null, boolean][]).map(([k, v, mono]) => (
                <div key={k} className="min-w-0 border-t border-line pt-1.5">
                  <dt className="text-[11px] text-muted">{k}</dt>
                  <dd className={`truncate text-[13.5px] font-medium ${mono ? "font-mono text-[12.5px]" : ""}`}>{v ?? "—"}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-[12.5px]">
                <thead className="text-left">
                  <tr><th className={`${th} pr-2`}>Item</th><th className={`${th} pr-2`}>Description</th>
                    <th className={`${th} pr-2 text-right`}>Qty</th><th className={`${th} pr-2 text-right`}>Unit</th>
                    <th className={`${th} text-right`}>Amount</th></tr>
                </thead>
                <tbody className="num">
                  {ext.line_items.map((l: any, i: number) => (
                    <tr key={i} className="border-t border-line">
                      <td className="py-1.5 pr-2 font-mono text-[11.5px]">{l.sku ?? "—"}</td><td className="pr-2">{l.description}</td>
                      <td className="pr-2 text-right font-mono">{l.quantity ?? "—"}</td><td className="pr-2 text-right font-mono">{money(l.unit_price)}</td>
                      <td className="text-right font-mono">{money(l.amount)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="num font-mono">
                  <tr className="border-t border-line-strong"><td colSpan={4} className="pt-1.5 text-right font-sans text-muted">Subtotal</td><td className="pt-1.5 text-right">{money(ext.subtotal)}</td></tr>
                  <tr><td colSpan={4} className="text-right font-sans text-muted">Tax</td><td className="text-right">{money(ext.tax)}</td></tr>
                  <tr><td colSpan={3} /><td className="double-rule pt-1 text-right font-sans font-semibold">Total</td><td className="double-rule pt-1 text-right font-semibold">{money(ext.total)}</td></tr>
                </tfoot>
              </table>
            </div>
            {ext.evidence?.length > 0 && (
              <details className="mt-5 border-t border-line pt-3">
                <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-wider text-muted hover:text-ink">Page evidence ({ext.evidence.length})</summary>
                <ul className="mt-2.5 space-y-1.5">
                  {ext.evidence.map((e: any, i: number) => (
                    <li key={i} className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)] gap-3 text-[12px]">
                      <code className="truncate font-mono text-[11px] text-muted">{e.field} · p.{e.page}</code>
                      <span className="min-w-0"><mark className="rounded-sm bg-highlight px-1 font-mono text-[11px] text-ink">{e.snippet}</mark></span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {ext.unreadable_fields?.length > 0 && <p className="mt-2 text-[12px] text-hold">Unreadable: {ext.unreadable_fields.join(", ")}</p>}
            {ext.notes && <p className="mt-2 text-[12px] text-muted">Model note: {ext.notes}</p>}
          </>
        )}
      </section>
      <section className="card min-w-0 p-5">
        <div className="flex items-baseline justify-between">
          <p className="label">Source document</p>
          <button onClick={() => setShowPdf(!showPdf)} className="font-mono text-[10.5px] uppercase tracking-wider text-muted hover:text-ink">{showPdf ? "hide" : "show"}</button>
        </div>
        <p className="mt-1 truncate font-mono text-[11px] text-muted">{snap.invoice.filename} · {snap.invoice.pages} page(s) · {snap.invoice.has_text_layer ? "text layer present" : "image only (scan)"}</p>
        {showPdf && <iframe title="Invoice PDF" src={inSandbox(`/api/invoices/${snap.invoice.id}/pdf#view=FitH`)} className="mt-3 h-[560px] w-full rounded-md border border-line bg-white" />}
      </section>
    </div>
  );
}
