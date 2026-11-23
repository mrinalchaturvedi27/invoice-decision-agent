"""Stage: find the PO and verify it belongs to this invoice (DECISION_POLICY.md §2).

A PO number only identifies a *candidate*; ownership, currency, status and line compatibility are
verified after lookup. Without a reference, a PO is inferred only with a clear lead over the runner-up.
"""
from __future__ import annotations

import re
import sqlite3
from decimal import Decimal

from rapidfuzz import fuzz

from app import ledger
from app.money import D, fmt
from app.pipeline.rules import hold, ok
from app.policy import PO_INFER_MIN_LEAD, PO_INFER_MIN_SCORE

STAGE = "po"


def _alnum(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _desc_sim(li: dict, pl: dict) -> float:
    if li.get("sku") and pl["sku"] and _alnum(li["sku"]) == _alnum(pl["sku"]):
        return 1.0
    return fuzz.token_set_ratio(li.get("description") or "", pl["description"] or "") / 100


def map_lines(ext_lines: list[dict], po_lines: dict) -> list[dict]:
    """Map each invoice line to its PO line by SKU, else by description similarity ≥ 0.80."""
    out = []
    for i, li in enumerate(ext_lines):
        best, best_sim = None, 0.0
        for pl in po_lines.values():
            sim = _desc_sim(li, pl)
            if sim > best_sim:
                best, best_sim = pl, sim
        out.append({"invoice_line": i, "po_line_id": best["id"] if best and best_sim >= 0.8 else None,
                    "po_line_no": best["line_no"] if best and best_sim >= 0.8 else None,
                    "similarity": round(best_sim, 2)})
    return out


def score_po(ext_lines: list[dict], state: dict, subtotal: Decimal | None) -> float:
    if not ext_lines or not state["lines"]:
        return 0.0
    total = 0.0
    for li in ext_lines:
        p = D(li.get("unit_price"))
        best = 0.0
        for pl in state["lines"].values():
            price_sim = max(0.0, 1 - float(abs(p - pl["unit_price"]) / pl["unit_price"]) * 10) if p else 0.0
            best = max(best, 0.6 * _desc_sim(li, pl) + 0.4 * price_sim)
        total += best
    score = total / len(ext_lines)
    if subtotal is not None and subtotal > state["open_balance"]:
        score *= 0.5
    return round(score, 3)


def resolve_po(conn: sqlite3.Connection, ext: dict, vendor: dict | None) -> tuple[dict | None, list[dict], dict]:
    """Returns (resolution {po_id, state, mapping, method} | None, rules, detail)."""
    refs, lines, currency = ext.get("po_references") or [], ext.get("line_items") or [], ext.get("currency")
    rules: list[dict] = []

    if len(refs) > 1:
        rules.append(hold("MULTI_PO", STAGE, f"Invoice references {len(refs)} POs ({', '.join(refs)}); v1 handles one"))
        return None, rules, {"refs": refs}

    if refs:
        ref = refs[0]
        po_ids = [r["id"] for r in conn.execute("SELECT id FROM purchase_orders")]
        po_id = next((p for p in po_ids if _alnum(p) == _alnum(ref)), None)
        if po_id is None:
            rules.append(hold("PO_NOT_FOUND", STAGE, f"PO '{ref}' does not exist in procurement"))
            return None, rules, {"ref": ref}
        state = ledger.open_state(conn, po_id)
        po = state["po"]
        detail = {"method": "explicit", "ref": ref, "po_id": po_id}
        if vendor and po["vendor_id"] != vendor["id"]:
            owner = conn.execute("SELECT name FROM vendors WHERE id = ?", (po["vendor_id"],)).fetchone()
            rules.append(hold("PO_VENDOR_MISMATCH", STAGE,
                              f"{po_id} belongs to {owner['name'] if owner else po['vendor_id']}, "
                              f"not {vendor['name']}", po_owner=po["vendor_id"]))
            # Never compare against (or reveal) another vendor's PO balance.
            return None, rules, detail
        else:
            rules.append(ok("PO_OWNERSHIP", STAGE, f"{po_id} belongs to this vendor"))
        if currency and currency.upper() != po["currency"]:
            rules.append(hold("CURRENCY_MISMATCH", STAGE, f"Invoice is in {currency}, {po_id} is in {po['currency']}"))
        else:
            rules.append(ok("CURRENCY", STAGE, f"Currency {po['currency']}" + ("" if currency else " (not printed; PO currency assumed)")))
        if po["status"] != "open":
            rules.append(hold("PO_CLOSED", STAGE, f"{po_id} status is '{po['status']}'"))
        mapping = map_lines(lines, state["lines"])
        unmapped = [m["invoice_line"] + 1 for m in mapping if m["po_line_id"] is None]
        rules.append(hold("LINE_UNMAPPED", STAGE, f"Invoice line(s) {unmapped} match no line on {po_id}",
                          lines=unmapped) if unmapped
                     else ok("LINES_MAPPED", STAGE, f"All {len(mapping)} line(s) map to {po_id} lines"))
        detail["mapping"] = mapping
        return {"po_id": po_id, "state": state, "mapping": mapping, "method": "explicit"}, rules, detail

    # No PO printed: infer among this vendor's open POs.
    if vendor is None:
        rules.append(hold("PO_AMBIGUOUS", STAGE, "No PO reference and the vendor is unknown, so no PO can be inferred"))
        return None, rules, {"method": "inferred", "candidates": []}
    subtotal = D(ext.get("subtotal"))
    cands = []
    for r in conn.execute("SELECT id, currency FROM purchase_orders WHERE vendor_id = ? AND status = 'open'",
                          (vendor["id"],)):
        if currency and currency.upper() != r["currency"]:
            continue
        st = ledger.open_state(conn, r["id"])
        cands.append({"po_id": r["id"], "score": score_po(lines, st, subtotal),
                      "open_balance": st["open_balance"], "description": st["po"]["description"]})
    cands.sort(key=lambda c: c["score"], reverse=True)
    top = cands[0] if cands else None
    runner_up = cands[1]["score"] if len(cands) > 1 else 0.0
    lead = round(top["score"] - runner_up, 3) if top else 0.0
    detail = {"method": "inferred", "candidates": cands[:4], "lead": lead,
              "thresholds": {"min_score": PO_INFER_MIN_SCORE, "min_lead": PO_INFER_MIN_LEAD}}
    if not top or top["score"] < PO_INFER_MIN_SCORE or lead < PO_INFER_MIN_LEAD:
        why = ("no open PO for this vendor" if not top else
               f"best match {top['po_id']} scores {top['score']:.2f} (needs ≥ {PO_INFER_MIN_SCORE:.2f})"
               if top["score"] < PO_INFER_MIN_SCORE else
               f"{top['po_id']} ({top['score']:.2f}) and {cands[1]['po_id']} ({cands[1]['score']:.2f}) both fit — "
               f"lead {lead:.2f} is below {PO_INFER_MIN_LEAD:.2f}")
        rules.append(hold("PO_AMBIGUOUS", STAGE, f"No PO on the invoice and it can't be inferred safely: {why}",
                          candidates=cands[:4], lead=lead))
        return None, rules, detail
    state = ledger.open_state(conn, top["po_id"])
    mapping = map_lines(lines, state["lines"])
    rules.append(ok("PO_INFERRED", STAGE,
                    f"No PO printed; inferred {top['po_id']} (score {top['score']:.2f}, lead {lead:.2f} over next "
                    f"candidate; open balance {fmt(top['open_balance'])})", po_id=top["po_id"]))
    unmapped = [m["invoice_line"] + 1 for m in mapping if m["po_line_id"] is None]
    if unmapped:
        rules.append(hold("LINE_UNMAPPED", STAGE, f"Invoice line(s) {unmapped} match no line on {top['po_id']}"))
    detail.update(po_id=top["po_id"], mapping=mapping)
    return {"po_id": top["po_id"], "state": state, "mapping": mapping, "method": "inferred"}, rules, detail
