"""Stage: compare the invoice with what is still open on the PO (DECISION_POLICY.md §3).

The open balance is a ceiling, not a tolerance target: a partial bill well under the balance is
normal; anything above it is held. Price tolerance applies per line against the agreed PO price.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.money import D, fmt
from app.pipeline.rules import hold, ok
from app.policy import PRICE_VARIANCE_CAP, PRICE_VARIANCE_PCT, TAX_RATE_TOLERANCE_PP

STAGE = "consumption"


def price_allowance(po_unit_price: Decimal, qty: Decimal) -> Decimal:
    """Allowed overcharge on a line: min(2% of the line's value at PO price, $500)."""
    return min(PRICE_VARIANCE_PCT * po_unit_price * qty, PRICE_VARIANCE_CAP)


def price_variance_ok(po_unit_price: Decimal, invoice_unit_price: Decimal, qty: Decimal) -> tuple[bool, Decimal, Decimal]:
    variance = (invoice_unit_price - po_unit_price) * qty
    allowance = price_allowance(po_unit_price, qty)
    return variance <= allowance, variance, allowance


def check_consumption(ext: dict, vendor: dict | None, resolution: dict) -> tuple[list[dict], dict]:
    state, mapping, po_id = resolution["state"], resolution["mapping"], resolution["po_id"]
    lines = ext.get("line_items") or []
    subtotal = D(ext.get("subtotal"))
    if subtotal is None:
        subtotal = sum((D(l.get("amount")) or Decimal(0) for l in lines), Decimal(0))
    open_bal = state["open_balance"]
    rules: list[dict] = []

    rules.append(hold("PO_EXHAUSTED", STAGE, f"{po_id} has no open balance left ({fmt(open_bal)} of "
                                             f"{fmt(state['total'])}); further charges need a PO amendment")
                 if open_bal <= 0 else ok("PO_HAS_BALANCE", STAGE, f"{po_id} open balance {fmt(open_bal)}"))
    if open_bal > 0:
        rules.append(hold("EXCEEDS_OPEN_BALANCE", STAGE,
                          f"Claims {fmt(subtotal)} pre-tax but only {fmt(open_bal)} is open on {po_id}",
                          claimed=subtotal, open_balance=open_bal, over_by=subtotal - open_bal)
                     if subtotal > open_bal else
                     ok("WITHIN_OPEN_BALANCE", STAGE, f"Claims {fmt(subtotal)} of {fmt(open_bal)} open; "
                                                      f"{fmt(open_bal - subtotal)} would remain"))

    # Quantity and price, per PO line.
    qty_by_line: dict[int, Decimal] = defaultdict(Decimal)
    amt_by_line: dict[int, Decimal] = defaultdict(Decimal)
    price_rows, qty_problems = [], []
    for m in mapping:
        if m["po_line_id"] is None:
            continue
        li, pl = lines[m["invoice_line"]], state["lines"][m["po_line_id"]]
        q, p, a = D(li.get("quantity")), D(li.get("unit_price")), D(li.get("amount"))
        if None in (q, p, a):
            continue
        qty_by_line[pl["id"]] += q
        amt_by_line[pl["id"]] += a
        within, variance, allowance = price_variance_ok(pl["unit_price"], p, q)
        price_rows.append({"line": m["invoice_line"] + 1, "sku": pl["sku"], "po_price": pl["unit_price"],
                           "invoice_price": p, "qty": q, "variance": variance, "allowance": allowance, "ok": within})
    for line_id, q in qty_by_line.items():
        pl = state["lines"][line_id]
        if q > pl["open_qty"]:
            qty_problems.append(f"{pl['sku']}: bills {q}, {pl['open_qty']} of {pl['qty']} open")
    rules.append(hold("QTY_EXCEEDS_OPEN", STAGE, "Quantity above what is open: " + "; ".join(qty_problems))
                 if qty_problems else ok("QTY_WITHIN_OPEN", STAGE, "Billed quantities within open PO quantities"))

    over = [r for r in price_rows if not r["ok"]]
    rules.append(hold("PRICE_VARIANCE", STAGE, "Unit price above agreed PO price beyond tolerance: " + "; ".join(
        f"{r['sku']} {fmt(r['invoice_price'])} vs PO {fmt(r['po_price'])} × {r['qty']} = {fmt(r['variance'])} over "
        f"(allowed {fmt(r['allowance'])})" for r in over), rows=price_rows)
        if over else ok("PRICE_WITHIN_TOLERANCE", STAGE, "Unit prices within tolerance of PO prices", rows=price_rows))

    if vendor:
        rate, tax, treat = D(vendor["tax_rate"]), D(ext.get("tax")), ext.get("tax_treatment")
        if treat == "separate" and tax is not None and subtotal:
            actual = tax / subtotal
            rules.append(hold("TAX_RATE", STAGE, f"Tax is {actual:.2%} of subtotal; vendor's expected rate is {rate:.2%}")
                         if abs(actual - rate) > TAX_RATE_TOLERANCE_PP else
                         ok("TAX_RATE", STAGE, f"Tax {actual:.2%} matches expected {rate:.2%}"))
        elif treat == "none" or tax in (None, Decimal(0)):
            rules.append(hold("TAX_RATE", STAGE, f"No tax charged; vendor's expected rate is {rate:.2%}") if rate > 0
                         else ok("TAX_RATE", STAGE, "No tax charged; vendor is tax-exempt"))

    allocations = [{"po_line_id": lid, "qty": qty_by_line[lid], "amount": amt_by_line[lid]} for lid in qty_by_line]
    snapshot = {"open_balance": open_bal,
                "open_qty": {str(lid): state["lines"][lid]["open_qty"] for lid in qty_by_line}}
    detail = {"po_id": po_id, "po_total": state["total"], "open_balance": open_bal, "claimed_pre_tax": subtotal,
              "would_remain": open_bal - subtotal, "price_rows": price_rows}
    return rules, {"detail": detail, "allocations": allocations, "snapshot": snapshot,
                   "balance_before": open_bal, "subtotal": subtotal}
