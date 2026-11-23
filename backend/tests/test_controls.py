"""Extraction verification, PO ownership, and the E4 stretch cases (each on a fresh seed)."""
import hashlib
import json
from decimal import Decimal

from conftest import TRUTH, open_balance, pdf, submit


def test_consistent_misread_caught_by_text_layer(runner):
    """Model misreads 400 as 410 and keeps the arithmetic consistent; totals alone would pass."""
    sha = hashlib.sha256(pdf("e1-a")).hexdigest()
    bad = dict(TRUTH[sha])
    bad["line_items"] = [dict(bad["line_items"][0], quantity="410", amount="20500.00")]
    bad.update(subtotal="20500.00", tax="1640.00", total="22140.00")
    runner.extractor.overrides[sha] = bad
    r = submit(runner, "e1-a")
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "NOT_IN_TEXT_LAYER")
    assert "line_items[0].quantity=410" in r["deciding_message"]
    assert open_balance("PO-1042") == Decimal("48000")


def test_row_swap_passes_text_layer_but_po_comparison_catches_it(runner):
    """The text-layer check is presence-only. If the model assigns real numbers to the wrong rows
    (bolts get the nuts' qty/price and vice versa), every value still appears in the PDF and the
    arithmetic still holds — the per-line comparison against the PO is what catches it."""
    sha = hashlib.sha256(pdf("e2-original")).hexdigest()
    bad = json.loads(json.dumps(TRUTH[sha]))
    a, b = bad["line_items"]
    bad["line_items"] = [dict(a, quantity=b["quantity"], unit_price=b["unit_price"], amount=b["amount"]),
                         dict(b, quantity=a["quantity"], unit_price=a["unit_price"], amount=a["amount"])]
    runner.extractor.overrides[sha] = bad
    r = submit(runner, "e2-original")
    rules = {t["rule"]: t for t in r["trace"]}
    assert rules["TEXT_LAYER_MATCH"]["ok"] is True          # the limitation, stated as a test
    assert rules["LINE_MATH"]["ok"] is True
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "PRICE_VARIANCE")
    assert "NUT-M8 $6.00 vs PO $3.00" in r["deciding_message"]
    assert open_balance("PO-2050") == Decimal("12000")


def test_line_math_mismatch_holds(runner):
    sha = hashlib.sha256(pdf("e1-a")).hexdigest()
    bad = dict(TRUTH[sha])
    bad["line_items"] = [dict(bad["line_items"][0], quantity="40")]
    runner.extractor.overrides[sha] = bad
    r = submit(runner, "e1-a")
    assert r["deciding_rule"] == "LINE_MATH"


def test_tax_inclusive_invoice_holds(runner):
    sha = hashlib.sha256(pdf("e1-a")).hexdigest()
    runner.extractor.overrides[sha] = dict(TRUTH[sha], tax_treatment="inclusive")
    assert submit(runner, "e1-a")["deciding_rule"] == "TAX_BASIS"


def test_real_po_of_another_vendor_is_held(runner):
    r = submit(runner, "x1")
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "PO_VENDOR_MISMATCH")
    assert "belongs to Acme Industrial Supply Ltd" in r["deciding_message"]
    assert r["po_id"] is None and r["balance_before"] is None   # other vendor's PO not used or exposed
    assert open_balance("PO-1042") == Decimal("48000")


def test_e4_price_variance_alone(runner):
    r = submit(runner, "e4-a")
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "PRICE_VARIANCE")
    assert [t["rule"] for t in r["trace"] if t["ok"] is False] == ["PRICE_VARIANCE"]


def test_e4_bank_change_alone(runner):
    r = submit(runner, "e4-b")
    assert (r["decision"], r["deciding_rule"]) == ("HOLD", "BANK_CHANGED")
    assert [t["rule"] for t in r["trace"] if t["ok"] is False] == ["BANK_CHANGED"]


def test_e4_one_step_over_cap_holds(runner):
    assert submit(runner, "e4-d")["deciding_rule"] == "PRICE_VARIANCE"


def test_e4_exactly_at_cap_approves(runner):
    r = submit(runner, "e4-c")
    assert r["decision"] == "APPROVE"
    assert open_balance("PO-4001") == Decimal("48000") - Decimal("30500.00")
