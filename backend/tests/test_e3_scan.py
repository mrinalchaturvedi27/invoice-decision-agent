"""E3 — scanned invoices with no PO reference: infer only with a clear lead."""
from decimal import Decimal

from conftest import open_balance, submit


def _step(run, rule):
    return next(t for t in run["trace"] if t["rule"] == rule)


def test_scan_with_one_fitting_po_is_inferred_and_approved(runner):
    r = submit(runner, "e3-a")
    assert r["decision"] == "APPROVE", r["deciding_message"]
    assert (r["po_id"], r["po_method"]) == ("PO-3101", "inferred")
    assert any(t["rule"] == "SCAN_EVIDENCE" and t["ok"] for t in r["trace"])
    inferred = _step(r, "PO_INFERRED")
    assert "PO-3101" in inferred["message"] and "lead" in inferred["message"]
    assert open_balance("PO-3101") == Decimal("0")


def test_scan_fitting_two_pos_is_held_with_both_candidates(runner):
    r = submit(runner, "e3-b")
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "PO_AMBIGUOUS")
    cands = _step(r, "PO_AMBIGUOUS")["data"]["candidates"]
    assert {c["po_id"] for c in cands[:2]} == {"PO-3103", "PO-3104"}
    assert cands[0]["score"] == cands[1]["score"]
    assert open_balance("PO-3103") == open_balance("PO-3104") == Decimal("4200")


def test_unreadable_critical_field_on_scan_holds(runner):
    import hashlib
    from conftest import TRUTH, pdf
    sha = hashlib.sha256(pdf("e3-a")).hexdigest()
    misread = dict(TRUTH[sha], unreadable_fields=["line_items[1].quantity"])
    runner.extractor.overrides[sha] = misread
    r = submit(runner, "e3-a")
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "UNREADABLE_FIELD")
