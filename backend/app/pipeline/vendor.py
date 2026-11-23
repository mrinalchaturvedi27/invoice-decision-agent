"""Stage: match the invoice to the vendor master and check remittance details."""
from __future__ import annotations

import re
import sqlite3

from rapidfuzz import fuzz, process

from app.pipeline.rules import hold, ok

STAGE = "vendor"


def _norm(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def check_vendor(conn: sqlite3.Connection, ext: dict) -> tuple[dict | None, list[dict], dict]:
    vendors = [dict(r) for r in conn.execute("SELECT * FROM vendors")]
    tax_id, name = _norm(ext.get("vendor_tax_id")), ext.get("vendor_name") or ""
    vendor, how, score = None, None, None

    if tax_id:
        vendor = next((v for v in vendors if _norm(v["tax_id"]) == tax_id), None)
        how = "tax ID" if vendor else None
    if vendor is None and name:
        best = process.extractOne(name, {v["id"]: v["name"] for v in vendors}, scorer=fuzz.token_sort_ratio)
        if best and best[1] >= 88:
            vendor, how, score = next(v for v in vendors if v["id"] == best[2]), "name", round(best[1], 1)

    rules: list[dict] = []
    if vendor is None:
        rules.append(hold("VENDOR_UNKNOWN", STAGE, f"'{name or 'no vendor name'}' is not in the approved vendor master"))
        return None, rules, {"matched": None}

    rules.append(ok("VENDOR_KNOWN", STAGE, f"Matched {vendor['name']} ({vendor['id']}) by {how}"))
    if how == "name" and tax_id and tax_id != _norm(vendor["tax_id"]):
        rules.append(hold("VENDOR_TAX_ID_MISMATCH", STAGE,
                          f"Name matches {vendor['name']} but tax ID {ext.get('vendor_tax_id')} differs from "
                          f"master {vendor['tax_id']}"))

    bank = (ext.get("bank_account_last4") or "").strip()
    if not bank:
        rules.append(ok("BANK_DETAILS", STAGE, "No bank details printed; payment uses the vendor master account"))
    elif bank != vendor["bank_last4"]:
        rules.append(hold("BANK_CHANGED", STAGE,
                          f"Invoice asks for payment to account ending {bank}; vendor master has {vendor['bank_last4']}",
                          invoice_bank=bank, master_bank=vendor["bank_last4"]))
    else:
        rules.append(ok("BANK_DETAILS", STAGE, f"Bank account ending {bank} matches vendor master"))
    return vendor, rules, {"matched": vendor["id"], "name": vendor["name"], "by": how, "score": score}
