"""E3 — scanned invoices with no PO reference: infer only with a clear lead."""
import json
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


def _scan_truth():
    import hashlib
    from conftest import TRUTH, pdf
    sha = hashlib.sha256(pdf("e3-a")).hexdigest()
    return sha, json.loads(json.dumps(TRUTH[sha]))


def test_scan_missing_only_price_evidence_holds(runner):
    """Evidence for a line's quantity must not vouch for its price: each critical field needs its own."""
    sha, ext = _scan_truth()
    ext["evidence"] = [e for e in ext["evidence"] if e["field"] != "line_items[0].unit_price"]
    runner.extractor.overrides[sha] = ext
    r = submit(runner, "e3-a")
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "MISSING_EVIDENCE")
    assert _step(r, "MISSING_EVIDENCE")["data"]["no_evidence"] == ["line_items[0].unit_price"]
    assert not any(t["rule"] == "SCAN_EVIDENCE" for t in r["trace"])
    assert open_balance("PO-3101") == Decimal("3070")


def test_scan_evidence_with_empty_snippet_does_not_count(runner):
    sha, ext = _scan_truth()
    for e in ext["evidence"]:
        if e["field"] == "total":
            e["snippet"] = "  "
    runner.extractor.overrides[sha] = ext
    r = submit(runner, "e3-a")
    assert _step(r, "MISSING_EVIDENCE")["data"]["no_evidence"] == ["total"]


def test_scan_evidence_field_name_variants_are_accepted(runner):
    """Model writes 'line_items.0.qty' style names: normalised, not a false hold."""
    sha, ext = _scan_truth()
    for e in ext["evidence"]:
        e["field"] = (e["field"].replace("[", ".").replace("]", "").replace("quantity", "qty")
                      .replace("unit_price", "price"))
    runner.extractor.overrides[sha] = ext
    assert submit(runner, "e3-a")["decision"] == "APPROVE"


def test_unreadable_critical_field_on_scan_holds(runner):
    import hashlib
    from conftest import TRUTH, pdf
    sha = hashlib.sha256(pdf("e3-a")).hexdigest()
    misread = dict(TRUTH[sha], unreadable_fields=["line_items[1].quantity"])
    runner.extractor.overrides[sha] = misread
    r = submit(runner, "e3-a")
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "UNREADABLE_FIELD")
