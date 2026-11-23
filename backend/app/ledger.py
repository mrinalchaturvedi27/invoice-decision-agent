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


DECISION_FIELDS = ("decision", "deciding_rule", "deciding_message", "po_id", "po_method", "balance_before",
                   "balance_after", "linked_invoice_id", "trace")


def _write_decision(conn: sqlite3.Connection, run_id: int, fields: dict) -> None:
    cols = [f for f in DECISION_FIELDS if f in fields]
    vals = [db.dumps(fields[f]) if f == "trace" else (str(fields[f]) if isinstance(fields[f], Decimal) else fields[f])
            for f in cols]
    conn.execute(f"UPDATE runs SET {', '.join(c + '=?' for c in cols)}, decided_at=? WHERE id=?",
                 (*vals, db.now(), run_id))


def record_decision(conn: sqlite3.Connection, run_id: int, fields: dict) -> None:
    """HOLD / REJECT: the ledger is untouched, so recording the verdict is a single atomic write."""
    _write_decision(conn, run_id, fields)


def commit_approval(conn: sqlite3.Connection, *, run_id: int, invoice_id: int, po_id: str,
                    allocations: list[dict], snapshot: dict, decision: dict) -> dict:
    """One BEGIN IMMEDIATE transaction that re-checks duplicates and the balance, posts the allocations, and
    records the run's decision with its before/after balances, so a posting never exists without its verdict.

    allocations: [{po_line_id, qty, amount}]. snapshot: {open_balance, open_qty: {line_id: qty}} seen when the
    decision was made. decision: the run fields to record (balances are filled in here).
    Returns status applied | already_applied | stale | duplicate | suspected_duplicate."""
    from app.pipeline.duplicates import find_approved_match

    conn.execute("BEGIN IMMEDIATE")
    try:
        inv = dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())
        if inv["approved_run_id"] and inv["approved_run_id"] != run_id:
            conn.execute("ROLLBACK")
            return {"status": "duplicate", "approved_run_id": inv["approved_run_id"]}
        existing = conn.execute("SELECT amount FROM allocations WHERE invoice_id = ?", (invoice_id,)).fetchall()
        if existing:  # this run already posted (pre-dates recorded decisions): idempotent
            st = open_state(conn, po_id)
            used = sum((D(r["amount"]) for r in existing), Decimal(0))
            result = {"status": "already_applied", "balance_before": st["open_balance"] + used,
                      "balance_after": st["open_balance"]}
            _write_decision(conn, run_id, {**decision, "balance_before": result["balance_before"],
                                           "balance_after": result["balance_after"]})
            conn.execute("COMMIT")
            return result
        # Business duplicate approved by another run after this run's duplicate stage looked.
        match = find_approved_match(conn, inv)
        if match:
            st = open_state(conn, po_id)
            conn.execute("ROLLBACK")
            o, reasons = match
            return {"status": "suspected_duplicate", "original": {k: o[k] for k in ("id", "invoice_number",
                                                                                   "approved_run_id")},
                    "reasons": reasons, "open_balance": st["open_balance"]}

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
        result = {"status": "applied", "balance_before": st["open_balance"],
                  "balance_after": st["open_balance"] - claimed}
        _write_decision(conn, run_id, {**decision, "balance_before": result["balance_before"],
                                       "balance_after": result["balance_after"]})
        conn.execute("COMMIT")
        return result
    except Exception:
        conn.execute("ROLLBACK")
        raise
