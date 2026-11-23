"""Retries can't double-allocate or self-flag; parallel approvals can't overspend a PO."""
import threading
from decimal import Decimal

from conftest import MANIFEST, allocations_total, get_run, open_balance, pdf, submit


def test_retrying_a_run_is_idempotent(runner):
    first = submit(runner, "e1-a")
    calls = runner.extractor.calls
    runner.execute(first["id"])            # retry the same run (e.g. after a crash before it finished)
    again = get_run(first["id"])
    assert again["decision"] == "APPROVE" and again["deciding_rule"] is None
    assert again["attempts"] == 2
    assert not [t for t in again["trace"] if t["rule"] == "SUSPECTED_DUPLICATE" and t["ok"] is False]
    assert allocations_total("PO-1042") == Decimal("20000")
    assert runner.extractor.calls == calls  # extraction served from cache on retry


def test_parallel_approvals_cannot_exceed_po(runner):
    """B (₹30,000) and C (₹28,000) each fit a fresh ₹48,000 PO but not together."""
    ids = [runner.create_run(pdf(s), MANIFEST[s]["file"]) for s in ("e1-b", "e1-c")]
    threads = [threading.Thread(target=runner.execute, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    runs = [get_run(i) for i in ids]
    assert sorted(r["decision"] for r in runs) == ["APPROVE", "HOLD"], [r["deciding_message"] for r in runs]
    assert allocations_total("PO-1042") <= Decimal("48000")
    held = next(r for r in runs if r["decision"] == "HOLD")
    assert held["deciding_rule"] in ("EXCEEDS_OPEN_BALANCE", "QTY_EXCEEDS_OPEN")
    assert open_balance("PO-1042") + allocations_total("PO-1042") == Decimal("48000")


def test_stale_snapshot_is_refused_by_ledger(runner):
    """Directly: a decision made on an old balance can't commit."""
    from app import db, ledger
    submit(runner, "e1-a")                         # balance now 28,000
    run_id = runner.create_run(pdf("e1-c"), "e1-c.pdf")
    conn = db.connect()
    try:
        inv_id = conn.execute("SELECT invoice_id FROM runs WHERE id=?", (run_id,)).fetchone()[0]
        line_id = conn.execute("SELECT id FROM po_lines WHERE po_id='PO-1042'").fetchone()[0]
        res = ledger.commit_approval(conn, run_id=run_id, invoice_id=inv_id, po_id="PO-1042",
                                     allocations=[{"po_line_id": line_id, "qty": Decimal(560), "amount": Decimal("28000")}],
                                     snapshot={"open_balance": Decimal("48000"), "open_qty": {str(line_id): Decimal(960)}},
                                     decision={"decision": "APPROVE"})
    finally:
        conn.close()
    assert res["status"] == "stale"
    assert open_balance("PO-1042") == Decimal("28000")
