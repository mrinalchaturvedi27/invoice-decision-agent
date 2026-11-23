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
    line_sum = sum((D(li.get("amount")) or Decimal(0)) for li in lines)
    problems = []
    if sub is None:
        problems.append("no subtotal")
    elif abs(line_sum - sub) > MONEY_TOLERANCE:
        problems.append(f"lines sum to {fmt(line_sum)} but subtotal is {fmt(sub)}")
    if sub is not None and total is not None and abs(sub + (tax or 0) - total) > MONEY_TOLERANCE:
        problems.append(f"subtotal {fmt(sub)} + tax {fmt(tax or Decimal(0))} ≠ total {fmt(total)}")
    rules.append(hold("TOTAL_MATH", STAGE, "Totals don't add up: " + "; ".join(problems)) if problems
                 else ok("TOTAL_MATH", STAGE, f"Lines → subtotal {fmt(sub)} → total {fmt(total)} add up"))

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
        rules.append(hold("NOT_IN_TEXT_LAYER", STAGE,
                          "Extracted values not found in the PDF's own text: " +
                          ", ".join(f"{f}={v}" for f, v in not_found),
                          values=[{"field": f, "value": v} for f, v in not_found]) if not_found
                     else ok("TEXT_LAYER_MATCH", STAGE,
                             f"All {len(crit)} critical values found in the PDF's own text layer"))
    else:
        unreadable = ext.get("unreadable_fields") or []
        evidenced = {e.get("field", "") for e in ext.get("evidence") or []}
        needs = ["invoice_number", "subtotal", "total"] + [f"line_items[{i}]" for i in range(len(lines))]
        no_evidence = [f for f in needs if not any(e == f or e.startswith(f + ".") or e.startswith(f + "[")
                                                   for e in evidenced)]
        if unreadable or no_evidence:
            parts = ([f"unreadable: {', '.join(unreadable)}"] if unreadable else []) + \
                    ([f"no page evidence for: {', '.join(no_evidence)}"] if no_evidence else [])
            rules.append(hold("UNREADABLE_FIELD", STAGE, "Scan is not legible enough to rely on — " + "; ".join(parts),
                              unreadable=unreadable, no_evidence=no_evidence))
        else:
            rules.append(ok("SCAN_EVIDENCE", STAGE, f"Scanned document: every critical field has page evidence; "
                                                    f"PO price/quantity agreement is the independent check"))
    return rules, detail
