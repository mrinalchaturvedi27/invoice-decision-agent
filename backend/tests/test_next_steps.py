"""Every HOLD/REJECT carries one rule-based instruction the AP reviewer can act on."""
import re
from pathlib import Path

from app import db, queries
from app.pipeline.next_steps import next_step
from conftest import submit

FALLBACK = "Review the deciding rule in the trace and decide manually."


def _snapshot(run_id):
    conn = db.connect()
    try:
        return queries.run_snapshot(conn, run_id)
    finally:
        conn.close()


def test_e1b_asks_for_a_corrected_invoice_or_amendment(runner):
    submit(runner, "e1-a")
    b = submit(runner, "e1-b")
    assert _snapshot(b["id"])["next_step"] == "Request a corrected invoice or an approved PO amendment."


def test_ambiguous_scan_names_both_candidate_pos(runner):
    b = submit(runner, "e3-b")
    assert _snapshot(b["id"])["next_step"] == "Confirm whether this invoice belongs to PO-3103 or PO-3104."


def test_duplicate_points_at_the_original(runner):
    original = submit(runner, "e2-original")
    held = submit(runner, "e2-disguised")
    step = _snapshot(held["id"])["next_step"]
    assert "INV-2231" in step and f"run #{original['id']}" in step


def test_approvals_have_no_next_step(runner):
    assert _snapshot(submit(runner, "e1-a")["id"])["next_step"] is None


def test_every_hold_and_reject_rule_has_a_specific_step():
    src = "\n".join(p.read_text() for p in Path("app").rglob("*.py"))
    rules = set(re.findall(r'(?:hold|reject)\("([A-Z_]+)"', src))
    assert len(rules) >= 20
    missing = [r for r in sorted(rules)
               if next_step({"decision": "HOLD", "deciding_rule": r, "po_id": "PO-1"}, []) == FALLBACK]
    assert not missing, f"rules without a specific next step: {missing}"
