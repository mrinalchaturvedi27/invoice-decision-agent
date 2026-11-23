"""Mapping invoice lines to PO lines: an exact SKU wins; a description-only match that ties is held.

A PO can carry two lines with the same description (two filter grades, both "Air filter"). Billing FILT-B
must consume FILT-B's quantity, never whichever line happens to come first.
"""
import hashlib
import io
from decimal import Decimal

import pytest
from reportlab.pdfgen import canvas

from app import db, ledger
from app.pipeline.po_resolve import map_lines
from conftest import get_run, open_balance

PO = "PO-5001"


@pytest.fixture
def filters_po(runner):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO purchase_orders VALUES (?,?,?,?,?,?)",
                     (PO, "V-ACME", "INR", "open", "8000.00", "HVAC filters"))
        for no, sku in ((1, "FILT-A"), (2, "FILT-B")):
            conn.execute("INSERT INTO po_lines(po_id, line_no, sku, description, qty, unit_price) VALUES (?,?,?,?,?,?)",
                         (PO, no, sku, "Air filter", "100", "40.00"))
        ids = {r["sku"]: r["id"] for r in conn.execute("SELECT id, sku FROM po_lines WHERE po_id = ?", (PO,))}
    finally:
        conn.close()
    return ids


def _invoice(runner, number: str, sku: str | None) -> dict:
    """A real PDF (so the text-layer check runs) plus the extraction Claude would return for it."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    y = 800
    for line in ["Acme Industrial Supply Ltd   Tax ID US-84-1234567", f"Invoice {number}   Date 2026-11-20",
                 f"PO number {PO}", f"{sku or ''} Air filter   30   40.00   1,200.00",
                 "Subtotal 1,200.00", "Tax 8% 96.00", "Total due (INR) 1,296.00", "Remit to account ending 4821"]:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    pdf = buf.getvalue()
    row = f"{sku or ''} Air filter 30 40.00 1,200.00".strip()
    ext = {"vendor_name": "Acme Industrial Supply Ltd", "vendor_tax_id": "US-84-1234567", "bank_account_last4": "4821",
           "invoice_number": number, "invoice_date": "2026-11-20", "due_date": None, "currency": "INR",
           "po_references": [PO],
           "line_items": [{"sku": sku, "description": "Air filter", "quantity": "30", "unit_price": "40.00",
                           "amount": "1200.00"}],
           "subtotal": "1200.00", "tax": "96.00", "total": "1296.00", "tax_treatment": "separate",
           "evidence": [{"field": f, "page": 1, "snippet": s} for f, s in [
               ("invoice_number", number), ("po_references", PO), ("subtotal", "1,200.00"), ("tax", "96.00"),
               ("total", "1,296.00"), ("line_items[0].quantity", row), ("line_items[0].unit_price", row),
               ("line_items[0].amount", row)]],
           "unreadable_fields": [], "notes": None}
    runner.extractor.overrides[hashlib.sha256(pdf).hexdigest()] = ext
    run_id = runner.create_run(pdf, f"{number}.pdf")
    runner.execute(run_id)
    return get_run(run_id)


def _open_qty(line_id: int) -> Decimal:
    conn = db.connect()
    try:
        return ledger.open_state(conn, PO)["lines"][line_id]["open_qty"]
    finally:
        conn.close()


def test_exact_sku_wins_over_an_identical_description(runner, filters_po):
    run = _invoice(runner, "INV-F-1", "FILT-B")
    assert run["decision"] == "APPROVE", run["deciding_message"]
    assert _open_qty(filters_po["FILT-B"]) == 70          # the billed line was consumed
    assert _open_qty(filters_po["FILT-A"]) == 100         # the other "Air filter" line is untouched
    conn = db.connect()
    try:
        allocs = conn.execute("SELECT po_line_id, qty FROM allocations WHERE run_id = ?", (run["id"],)).fetchall()
    finally:
        conn.close()
    assert [(a["po_line_id"], a["qty"]) for a in allocs] == [(filters_po["FILT-B"], "30")]


def test_description_only_tie_is_held_with_both_candidates(runner, filters_po):
    run = _invoice(runner, "INV-F-2", None)
    assert (run["decision"], run["deciding_rule"]) == ("HOLD", "LINE_AMBIGUOUS"), run["deciding_message"]
    rule = next(r for r in run["trace"] if r["rule"] == "LINE_AMBIGUOUS")
    cands = rule["data"]["lines"][0]["candidates"]
    assert {c["sku"] for c in cands} == {"FILT-A", "FILT-B"}
    assert "FILT-A" in run["deciding_message"] and "FILT-B" in run["deciding_message"]
    assert open_balance(PO) == Decimal("8000.00")         # ledger untouched
    assert _open_qty(filters_po["FILT-A"]) == _open_qty(filters_po["FILT-B"]) == 100


def test_sku_match_wins_even_when_listed_second_and_description_differs():
    po_lines = {1: {"id": 1, "line_no": 1, "sku": "FILT-A", "description": "Air filter, pleated"},
                2: {"id": 2, "line_no": 2, "sku": "FILT-B", "description": "Filter"}}
    m = map_lines([{"sku": "filt-b", "description": "Air filter, pleated"}], po_lines)[0]
    assert (m["po_line_id"], m["method"]) == (2, "sku")


def test_unknown_sku_falls_back_to_a_unique_description():
    po_lines = {1: {"id": 1, "line_no": 1, "sku": "WID-100", "description": "Industrial widget, steel"},
                2: {"id": 2, "line_no": 2, "sku": "BRK-9", "description": "Mounting bracket"}}
    m = map_lines([{"sku": "VENDOR-778", "description": "Industrial widget, steel"}], po_lines)[0]
    assert (m["po_line_id"], m["method"]) == (1, "description")
