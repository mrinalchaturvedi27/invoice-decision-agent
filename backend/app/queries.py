"""Read models for the API: one run's full picture, and the history list."""
from __future__ import annotations

import json
import sqlite3

from app import ledger
from app.pipeline.next_steps import next_step


def run_snapshot(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["trace"] = json.loads(run["trace"]) if run["trace"] else []
    steps = []
    for s in conn.execute("SELECT * FROM run_steps WHERE run_id = ? ORDER BY seq", (run_id,)):
        s = dict(s)
        s["detail"] = json.loads(s["detail"]) if s["detail"] else None
        steps.append(s)
    inv = dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (run["invoice_id"],)).fetchone())
    inv.pop("path", None)
    vendor = None
    if inv["vendor_id"]:
        v = conn.execute("SELECT id, name, bank_last4, tax_rate FROM vendors WHERE id = ?", (inv["vendor_id"],)).fetchone()
        vendor = dict(v) if v else None

    po = None
    if run["po_id"]:
        st = ledger.open_state(conn, run["po_id"])
        allocs = [dict(a) for a in conn.execute(
            "SELECT a.run_id, a.invoice_id, a.amount, a.qty, i.invoice_number FROM allocations a "
            "JOIN invoices i ON i.id = a.invoice_id WHERE a.po_id = ? ORDER BY a.id", (run["po_id"],))]
        po = {"id": run["po_id"], "description": st["po"]["description"], "status": st["po"]["status"],
              "total": st["total"], "open_now": st["open_balance"], "lines": list(st["lines"].values()),
              "allocations": allocs}

    linked = None
    if run["linked_invoice_id"] and run["linked_invoice_id"] != run["invoice_id"]:
        l = conn.execute("SELECT id, invoice_number, invoice_date, total, approved_run_id FROM invoices WHERE id = ?",
                         (run["linked_invoice_id"],)).fetchone()
        linked = dict(l) if l else None
    elif run["deciding_rule"] == "DUPLICATE_OF_APPROVED":
        linked = {"id": inv["id"], "invoice_number": inv["invoice_number"], "invoice_date": inv["invoice_date"],
                  "total": inv["total"], "approved_run_id": inv["approved_run_id"]}

    other_runs = [dict(r) for r in conn.execute(
        "SELECT id, decision, deciding_rule, started_at FROM runs WHERE invoice_id = ? AND id != ? ORDER BY id",
        (run["invoice_id"], run_id))]
    return {"run": run, "steps": steps, "invoice": inv, "vendor": vendor, "po": po, "linked": linked,
            "other_runs_of_invoice": other_runs, "next_step": next_step(run, run["trace"])}


def list_runs(conn: sqlite3.Connection, decision: str | None = None) -> list[dict]:
    sql = ("SELECT r.id, r.status, r.decision, r.deciding_rule, r.deciding_message, r.po_id, r.po_method, "
           "r.balance_before, r.balance_after, r.extraction_cached, r.started_at, r.finished_at, r.error, "
           "i.id AS invoice_id, i.filename, i.invoice_number, i.total, i.subtotal, v.name AS vendor_name "
           "FROM runs r JOIN invoices i ON i.id = r.invoice_id LEFT JOIN vendors v ON v.id = i.vendor_id")
    args: tuple = ()
    if decision:
        sql += " WHERE r.decision = ?"
        args = (decision,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY r.id DESC LIMIT 500", args)]


def stats(conn: sqlite3.Connection) -> dict:
    out = {"runs": 0, "APPROVE": 0, "HOLD": 0, "REJECT": 0, "error": 0, "running": 0}
    for r in conn.execute("SELECT status, decision, COUNT(*) n FROM runs GROUP BY status, decision"):
        out["runs"] += r["n"]
        key = r["decision"] if r["status"] == "done" else ("error" if r["status"] == "error" else "running")
        out[key] = out.get(key, 0) + r["n"]
    approved = conn.execute("SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) FROM allocations").fetchone()[0]
    out["approved_amount"] = round(approved, 2)
    return out
