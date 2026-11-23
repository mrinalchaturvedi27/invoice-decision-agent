"""Stage: duplicate detection. Only approved invoices create payment risk, so only they can
trigger REJECT/HOLD; earlier non-approved submissions are linked for context."""
from __future__ import annotations

import re
import sqlite3
from datetime import date

from app.money import D, fmt
from app.pipeline.rules import hold, ok, reject
from app.policy import DUPLICATE_DATE_WINDOW_DAYS, LEDGER_CURRENCY

STAGE = "duplicates"


def normalise_number(number: str | None) -> str | None:
    """'INV-2231' and '2231-R' both become '2231'."""
    if not number:
        return None
    s = re.sub(r"[^A-Z0-9]", "", number.upper())
    s = re.sub(r"^(INVOICE|INV|NO|BILL)", "", s)
    s = re.sub(r"(?<=\d)(R|REV\d*|COPY|DUP|RESEND)$", "", s)
    return s.lstrip("0") or s


def _days_apart(a: str | None, b: str | None) -> int | None:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return None


def find_approved_match(conn: sqlite3.Connection, invoice: dict) -> tuple[dict, list[str]] | None:
    """An *approved* invoice from the same vendor that this one looks like (same normalised number, or same
    total in the same currency within the date window). Used again inside the posting transaction."""
    if not invoice.get("vendor_id"):
        return None
    norm, total, inv_date = invoice.get("norm_number"), D(invoice.get("total")), invoice.get("invoice_date")
    currency = invoice.get("currency") or LEDGER_CURRENCY
    for o in conn.execute("SELECT * FROM invoices WHERE vendor_id = ? AND id != ? AND approved_run_id IS NOT NULL "
                          "ORDER BY id", (invoice["vendor_id"], invoice["id"])):
        o, reasons = dict(o), []
        if norm and o["norm_number"] == norm:
            reasons.append(f"invoice number '{invoice.get('invoice_number')}' normalises to the same '{norm}' "
                           f"as approved '{o['invoice_number']}'")
        days = _days_apart(inv_date, o["invoice_date"])
        if (currency == (o["currency"] or LEDGER_CURRENCY) and total is not None and D(o["total"]) == total
                and days is not None and days <= DUPLICATE_DATE_WINDOW_DAYS):
            reasons.append(f"same total {fmt(total, currency)} within {days} days of approved '{o['invoice_number']}'")
        if reasons:
            return o, reasons
    return None


def check_duplicates(conn: sqlite3.Connection, run_id: int, invoice: dict, ext: dict,
                     vendor: dict | None) -> tuple[list[dict], int | None, dict]:
    rules: list[dict] = []
    # Byte-identical file already approved by a *different* run (a retry of this run is not a duplicate).
    if invoice["approved_run_id"] and invoice["approved_run_id"] != run_id:
        rules.append(reject("DUPLICATE_OF_APPROVED", STAGE,
                            f"This exact file was already approved in run #{invoice['approved_run_id']}",
                            original_run_id=invoice["approved_run_id"]))
        return rules, invoice["id"], {"match": "byte-identical", "original_invoice_id": invoice["id"]}

    if vendor is None:
        rules.append(ok("NO_DUPLICATE", STAGE, "Vendor unknown; only the file-hash check applies"))
        return rules, None, {}

    match = find_approved_match(conn, invoice)
    if match:
        o, reasons = match
        rules.append(hold("SUSPECTED_DUPLICATE", STAGE, "Possible duplicate: " + "; ".join(reasons),
                          original_invoice_id=o["id"], original_run_id=o["approved_run_id"],
                          original_number=o["invoice_number"]))
        return rules, o["id"], {"match": "near", "original_invoice_id": o["id"], "reasons": reasons}

    norm = invoice["norm_number"]
    others = conn.execute("SELECT id, invoice_number, norm_number FROM invoices WHERE vendor_id = ? AND id != ?",
                          (vendor["id"], invoice["id"])).fetchall()
    related = [{"invoice_id": o["id"], "invoice_number": o["invoice_number"]} for o in others
               if norm and o["norm_number"] == norm]
    rules.append(ok("NO_DUPLICATE", STAGE, "No approved invoice matches this one",
                    related_unapproved=related or None))
    return rules, None, {"related_unapproved": related}
