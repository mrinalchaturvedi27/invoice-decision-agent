"""PO ledger. Open balance = PO total − Σ allocations. Approvals are written in one BEGIN IMMEDIATE
transaction that re-reads the balance, so two approvals can never consume the same money."""
from __future__ import annotations

import sqlite3
from decimal import Decimal

from app import db
from app.money import D


def open_state(conn: sqlite3.Connection, po_id: str) -> dict | None:
    po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if po is None:
        return None
    allocated = sum((D(r["amount"]) for r in conn.execute(
        "SELECT amount FROM allocations WHERE po_id = ?", (po_id,))), Decimal(0))
    lines = {}
    for l in conn.execute("SELECT * FROM po_lines WHERE po_id = ? ORDER BY line_no", (po_id,)):
        used = sum((D(r["qty"]) for r in conn.execute(
            "SELECT qty FROM allocations WHERE po_line_id = ?", (l["id"],))), Decimal(0))
        lines[l["id"]] = {"id": l["id"], "line_no": l["line_no"], "sku": l["sku"], "description": l["description"],
                          "qty": D(l["qty"]), "unit_price": D(l["unit_price"]), "allocated_qty": used,
                          "open_qty": D(l["qty"]) - used}
    total = D(po["total"])
    return {"po": dict(po), "total": total, "allocated": allocated, "open_balance": total - allocated, "lines": lines}


def commit_approval(conn: sqlite3.Connection, *, run_id: int, invoice_id: int, po_id: str,
                    allocations: list[dict], snapshot: dict) -> dict:
    """allocations: [{po_line_id, qty, amount}]. snapshot: {open_balance, open_qty: {line_id: qty}} seen when
    the decision was made. Returns status applied | already_applied | stale | duplicate."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        inv = conn.execute("SELECT approved_run_id FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        existing = conn.execute("SELECT amount FROM allocations WHERE invoice_id = ?", (invoice_id,)).fetchall()
        if inv["approved_run_id"] and inv["approved_run_id"] != run_id:
            conn.execute("ROLLBACK")
            return {"status": "duplicate", "approved_run_id": inv["approved_run_id"]}
        if existing:  # a retry of the run that already committed: idempotent
            st = open_state(conn, po_id)
            conn.execute("COMMIT")
            used = sum((D(r["amount"]) for r in existing), Decimal(0))
            return {"status": "already_applied", "balance_before": st["open_balance"] + used,
                    "balance_after": st["open_balance"]}

        st = open_state(conn, po_id)
        claimed = sum((a["amount"] for a in allocations), Decimal(0))
        changed = st["open_balance"] != snapshot["open_balance"] or any(
            st["lines"][int(k)]["open_qty"] != v for k, v in snapshot["open_qty"].items())
        if changed or claimed > st["open_balance"]:
            conn.execute("ROLLBACK")
            return {"status": "stale", "open_balance": st["open_balance"]}

        ts = db.now()
        for a in allocations:
            conn.execute("INSERT INTO allocations(run_id, invoice_id, po_id, po_line_id, qty, amount, created_at) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (run_id, invoice_id, po_id, a["po_line_id"], str(a["qty"]), str(a["amount"]), ts))
        conn.execute("UPDATE invoices SET approved_run_id = ? WHERE id = ?", (run_id, invoice_id))
        conn.execute("COMMIT")
        return {"status": "applied", "balance_before": st["open_balance"],
                "balance_after": st["open_balance"] - claimed}
    except Exception:
        conn.execute("ROLLBACK")
        raise
