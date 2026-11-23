"""Stage: verify the extraction before trusting it (DECISION_POLICY.md §1).

The model's confidence and snippets come from the same read as its values, so for native PDFs we
cross-check every critical value against the PDF's own text layer, which the model never touches.
"""
from __future__ import annotations

import re
from decimal import Decimal

from app.money import D, fmt
from app.pipeline.rules import hold, ok
from app.policy import MONEY_TOLERANCE

STAGE = "checks"
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers_in(text: str) -> set[Decimal]:
    out = set()
    for tok in _NUM.findall(text):
        d = D(tok.replace(",", ""))
        if d is not None:
            out.add(d)
    return out


def _alnum(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def critical_values(ext: dict) -> list[tuple[str, str, str]]:
    """(field, kind, value) for every value the decision depends on."""
    vals = []
    if ext.get("invoice_number"):
        vals.append(("invoice_number", "id", ext["invoice_number"]))
    for i, ref in enumerate(ext.get("po_references") or []):
        vals.append((f"po_references[{i}]", "id", ref))
    for i, li in enumerate(ext.get("line_items") or []):
        for f in ("quantity", "unit_price", "amount"):
            if li.get(f) is not None:
                vals.append((f"line_items[{i}].{f}", "num", li[f]))
    for f in ("subtotal", "tax", "total"):
        if ext.get(f) is not None:
            vals.append((f, "num", ext[f]))
    return vals


def run_checks(ext: dict, text: str, has_text_layer: bool) -> tuple[list[dict], dict]:
    rules: list[dict] = []
    detail: dict = {"source": "text layer" if has_text_layer else "scanned image (no text layer)"}

    missing = [f for f in ("invoice_number", "total") if not ext.get(f)]
    rules.append(hold("MISSING_FIELD", STAGE, f"Missing {', '.join(missing)}", fields=missing) if missing
                 else ok("REQUIRED_FIELDS", STAGE, "Invoice number and total present"))

    # Line arithmetic: qty × unit price = amount. A consistent misread can pass totals; this catches more.
    bad_lines, lines = [], ext.get("line_items") or []
    for i, li in enumerate(lines):
        q, p, a = D(li.get("quantity")), D(li.get("unit_price")), D(li.get("amount"))
        if None in (q, p, a):
            bad_lines.append({"line": i + 1, "problem": "no quantity/unit price (bundled line?) — cannot compare to PO"})
        elif abs(q * p - a) > MONEY_TOLERANCE:
            bad_lines.append({"line": i + 1, "problem": f"{q} × {p} = {q * p:.2f}, invoice says {a}"})
    if not lines:
        bad_lines.append({"line": None, "problem": "no line items"})
    rules.append(hold("LINE_MATH", STAGE, "Line items don't verify: " + "; ".join(
        f"line {b['line']}: {b['problem']}" if b["line"] else b["problem"] for b in bad_lines), lines=bad_lines)
        if bad_lines else ok("LINE_MATH", STAGE, f"{len(lines)} line(s): quantity × unit price = amount"))

    sub, tax, total = D(ext.get("subtotal")), D(ext.get("tax")), D(ext.get("total"))
    currency = ext.get("currency")
    line_sum = sum((D(li.get("amount")) or Decimal(0)) for li in lines)
    problems = []
    if sub is None:
        problems.append("no subtotal")
    elif abs(line_sum - sub) > MONEY_TOLERANCE:
        problems.append(f"lines sum to {fmt(line_sum, currency)} but subtotal is {fmt(sub, currency)}")
    if sub is not None and total is not None and abs(sub + (tax or 0) - total) > MONEY_TOLERANCE:
        problems.append(f"subtotal {fmt(sub, currency)} + tax {fmt(tax or Decimal(0), currency)} ≠ total {fmt(total, currency)}")
    rules.append(hold("TOTAL_MATH", STAGE, "Totals don't add up: " + "; ".join(problems)) if problems
                 else ok("TOTAL_MATH", STAGE, f"Lines → subtotal {fmt(sub, currency)} → total {fmt(total, currency)} add up"))

    treatment = ext.get("tax_treatment")
    rules.append(hold("TAX_BASIS", STAGE, f"Tax treatment is '{treatment}', so the pre-tax amount can't be compared "
                                          f"like-for-like with the PO") if treatment in ("inclusive", "unclear")
                 else ok("TAX_BASIS", STAGE, f"Tax shown {'separately' if treatment == 'separate' else 'as none'}"))

    crit = critical_values(ext)
    if has_text_layer:
        nums, alnum = _numbers_in(text), _alnum(text)
        not_found = [(f, v) for f, kind, v in crit
                     if (kind == "num" and D(v) not in nums) or (kind == "id" and _alnum(v) not in alnum)]
        detail["verified_against_text_layer"] = len(crit) - len(not_found)
        # Presence check only: a value is accepted if it appears anywhere in the document, not necessarily on
        # the same row. Row assignment errors are caught downstream by the per-line PO price/quantity comparison.
        rules.append(hold("NOT_IN_TEXT_LAYER", STAGE,
                          "Extracted values that appear nowhere in the PDF's own text: " +
                          ", ".join(f"{f}={v}" for f, v in not_found),
                          values=[{"field": f, "value": v} for f, v in not_found]) if not_found
                     else ok("TEXT_LAYER_MATCH", STAGE,
                             f"All {len(crit)} critical values appear in the PDF's own text layer "
                             f"(presence only; row assignment is checked against the PO)"))
    else:
        unreadable = [f for f in (ext.get("unreadable_fields") or []) if f]
        evidenced = {normalise_field(e.get("field")) for e in ext.get("evidence") or [] if (e.get("snippet") or "").strip()}
        needs = required_evidence(ext)
        no_evidence = [f for f in needs if f not in evidenced]
        detail["evidence_required"] = len(needs)
        detail["evidence_present"] = len(needs) - len(no_evidence)
        if unreadable:
            rules.append(hold("UNREADABLE_FIELD", STAGE, f"Scan not legible enough to rely on: unreadable "
                                                         f"{', '.join(unreadable)}", unreadable=unreadable))
        if no_evidence:
            rules.append(hold("MISSING_EVIDENCE", STAGE, f"No page evidence for {len(no_evidence)} of {len(needs)} "
                                                         f"decision-critical fields: {', '.join(no_evidence)}",
                              no_evidence=no_evidence))
        if not unreadable and not no_evidence:
            rules.append(ok("SCAN_EVIDENCE", STAGE, f"Scanned document: all {len(needs)} decision-critical fields have "
                                                    f"their own page evidence. The model reports that evidence from "
                                                    f"the same read, so the PO price/quantity comparison is the "
                                                    f"independent check"))
    return rules, detail


_ALIASES = {"qty": "quantity", "price": "unit_price", "unitprice": "unit_price", "rate": "unit_price",
            "line_total": "amount", "linetotal": "amount", "total": "amount"}


def normalise_field(name: str | None) -> str:
    """'line_items.0.qty' / 'Line_Items[0].Quantity' -> 'line_items[0].quantity'; 'po_references[0]' -> 'po_references'."""
    s = (name or "").strip().lower().replace(" ", "_")
    s = re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", s)
    m = re.fullmatch(r"line_items\[(\d+)\]\.(\w+)", s)
    if m:
        return f"line_items[{m.group(1)}].{_ALIASES.get(m.group(2), m.group(2))}"
    return re.sub(r"\[\d+\]$", "", s)


def required_evidence(ext: dict) -> list[str]:
    """Every field the decision depends on needs its own evidence entry."""
    need = ["invoice_number", "subtotal", "total"]
    if ext.get("tax") is not None:
        need.append("tax")
    if ext.get("po_references"):
        need.append("po_references")
    for i in range(len(ext.get("line_items") or [])):
        need += [f"line_items[{i}].quantity", f"line_items[{i}].unit_price", f"line_items[{i}].amount"]
    return need
