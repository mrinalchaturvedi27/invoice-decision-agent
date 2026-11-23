"""Exact threshold math. Allowed overcharge per line = min(2% × PO price × qty, ₹500)."""
from decimal import Decimal as D

from app.pipeline.consumption import price_allowance, price_variance_ok


def test_cap_binds_on_a_48000_base():
    # 40 × ₹1,200 = ₹48,000; 2% would be ₹960, so the ₹500 cap binds.
    assert price_allowance(D("1200"), D("40")) == D("500")
    assert price_variance_ok(D("1200"), D("1212.50"), D("40"))[0] is True         # +₹500.00 exactly
    ok, variance, _ = price_variance_ok(D("1200.00"), D("1212.50025"), D("40"))      # +₹500.01
    assert variance == D("500.01000") and ok is False


def test_one_percent_on_48000_is_480_and_passes():
    ok, variance, allowance = price_variance_ok(D("1200"), D("1212"), D("40"))
    assert (variance, allowance, ok) == (D("480"), D("500"), True)


def test_pct_binds_on_small_base():
    # 10 × ₹1,000 = ₹10,000; 2% = ₹200 is below the cap.
    assert price_allowance(D("1000"), D("10")) == D("200")
    assert price_variance_ok(D("1000"), D("1020"), D("10"))[0] is True
    assert price_variance_ok(D("1000"), D("1020.01"), D("10"))[0] is False


def test_underbilling_never_fails_price():
    assert price_variance_ok(D("50"), D("45"), D("100"))[0] is True


def test_invoice_must_pass_both_price_tolerance_and_ceiling():
    """An invoice must pass both controls. A full ₹48,000 bill at +1% is within price tolerance
    (₹480 ≤ ₹500) but exceeds the open balance by ₹480 — so it is held by the ceiling."""
    from app.pipeline.consumption import check_consumption
    state = {"po": {"id": "PO-X"}, "total": D("48000"), "open_balance": D("48000"),
             "lines": {1: {"id": 1, "line_no": 1, "sku": "P", "description": "pump", "qty": D("40"),
                           "unit_price": D("1200"), "open_qty": D("40")}}}
    ext = {"line_items": [{"sku": "P", "description": "pump", "quantity": "40", "unit_price": "1212.00",
                           "amount": "48480.00"}], "subtotal": "48480.00", "tax": None, "tax_treatment": "none"}
    rules, _ = check_consumption(ext, None, {"state": state, "mapping": [{"invoice_line": 0, "po_line_id": 1}],
                                             "po_id": "PO-X"})
    by_rule = {r["rule"]: r for r in rules}
    assert by_rule["PRICE_WITHIN_TOLERANCE"]["ok"] is True
    assert [r["rule"] for r in rules if r["ok"] is False] == ["EXCEEDS_OPEN_BALANCE"]
