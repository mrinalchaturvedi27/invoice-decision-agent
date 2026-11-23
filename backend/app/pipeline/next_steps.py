"""One concrete instruction for the AP reviewer per deciding rule.

Rule-based and derived only from the recorded decision (deciding rule + the data stored with it), so it is
as reproducible as the decision itself and never depends on the model's wording.
"""
from __future__ import annotations

from app.money import D, fmt
from app.policy import PO_INFER_MIN_LEAD, PO_INFER_MIN_SCORE


def _rule_data(trace: list[dict], rule: str | None) -> dict:
    r = next((r for r in trace if r.get("rule") == rule and r.get("ok") is False), None)
    return (r or {}).get("data") or {}


def _or_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def next_step(run: dict, trace: list[dict]) -> str | None:
    """None for APPROVE (nothing to do) and for runs without a decision."""
    decision, rule, po = run.get("decision"), run.get("deciding_rule"), run.get("po_id")
    if decision not in ("HOLD", "REJECT"):
        return None
    d = _rule_data(trace, rule)
    the_po = po or "the PO"

    if rule == "EXCEEDS_OPEN_BALANCE":
        return "Request a corrected invoice or an approved PO amendment."
    if rule == "QTY_EXCEEDS_OPEN":
        return "Request a corrected invoice for the open quantity, or an approved PO amendment for the extra units."
    if rule == "PO_EXHAUSTED":
        bal = D(run.get("balance_before"))
        return (f"Nothing is left to bill on {the_po}" + (f" ({fmt(bal)} open)" if bal is not None else "") +
                ". Get an approved PO amendment from the buyer, or reject the invoice.")
    if rule == "PO_AMBIGUOUS":
        cands = d.get("candidates") or []
        top = cands[0]["score"] if cands else 0.0
        if top >= PO_INFER_MIN_SCORE:
            # The POs that made the match ambiguous: those within the required lead of the best fit.
            close = [c["po_id"] for c in cands if top - c["score"] < PO_INFER_MIN_LEAD]
            if len(close) >= 2:
                return f"Confirm whether this invoice belongs to {_or_list(close)}."
        if cands:
            return (f"Ask the vendor for the PO number. The closest open PO, {cands[0]['po_id']}, "
                    f"isn't a confident fit.")
        return "Ask the vendor for the PO number this invoice bills against."
    if rule == "LINE_AMBIGUOUS":
        lines = d.get("lines") or []
        if lines:
            first = lines[0]
            opts = [f"line {c['line_no']} ({c['sku'] or c['description']})" for c in first["candidates"]]
            more = f" (and {len(lines) - 1} more invoice line(s))" if len(lines) > 1 else ""
            return f"Confirm whether invoice line {first['invoice_line']} bills {the_po} {_or_list(opts)}{more}."
        return f"Confirm which {the_po} line each invoice line bills."
    if rule == "LINE_UNMAPPED":
        return f"Ask the vendor which {the_po} line(s) invoice line(s) {d.get('lines') or ''} bill, or have the buyer amend the PO."
    if rule == "PRICE_VARIANCE":
        return "Confirm the new price with the buyer, or request a corrected invoice at the PO price."
    if rule == "BANK_CHANGED":
        return ("Verify the new bank account with the vendor through a contact already on file, not the details on "
                "this invoice, before releasing payment.")
    if rule == "SUSPECTED_DUPLICATE":
        num, rid = d.get("original_number"), d.get("original_run_id")
        ref = f"approved invoice {num}" + (f" (run #{rid})" if rid else "") if num else "the linked approved invoice"
        return f"Compare with {ref}. Reject this one if it bills the same goods; otherwise release it with a note."
    if rule == "DUPLICATE_OF_APPROVED":
        rid = d.get("original_run_id")
        return f"No payment needed: this file was already approved{f' in run #{rid}' if rid else ''}. Tell the vendor it was a resubmission."
    if rule == "PO_VENDOR_MISMATCH":
        return ("Ask the vendor for their own PO number, and flag this to procurement: the invoice cites another "
                "vendor's PO.")
    if rule == "PO_NOT_FOUND":
        return "Ask the vendor for a valid PO number, or have procurement confirm whether the PO should exist."
    if rule == "PO_CLOSED":
        return f"Ask procurement whether {the_po} should be reopened; otherwise reject the invoice."
    if rule == "CURRENCY_MISMATCH":
        return f"Request a corrected invoice in the PO currency, or confirm the currency with the buyer."
    if rule == "MULTI_PO":
        return "Ask the vendor for one invoice per PO."
    if rule == "VENDOR_UNKNOWN":
        return "Match the vendor to an existing vendor-master record, or start vendor onboarding before paying."
    if rule == "VENDOR_TAX_ID_MISMATCH":
        return "Confirm the vendor's tax ID with the vendor-master owner before paying."
    if rule == "TAX_RATE":
        return "Request a corrected invoice with the expected tax rate, or confirm the rate with the tax team."
    if rule == "TAX_BASIS":
        return "Request an invoice that shows tax separately, so the pre-tax amount can be compared with the PO."
    if rule in ("LINE_MATH", "TOTAL_MATH"):
        return "Check the flagged figures against the PDF; if the invoice's own arithmetic is wrong, request a corrected invoice."
    if rule == "NOT_IN_TEXT_LAYER":
        return "Check the flagged values against the PDF by hand: what was read doesn't appear in the document's text."
    if rule in ("UNREADABLE_FIELD", "MISSING_EVIDENCE"):
        return "Check the flagged fields against the scan by hand, or ask the vendor for a clearer copy."
    if rule == "MISSING_FIELD":
        return "Ask the vendor for a complete invoice with an invoice number and total."
    return "Review the deciding rule in the trace and decide manually."
