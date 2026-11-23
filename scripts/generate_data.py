"""Generate the procurement seed data and the sample invoice PDFs.

Writes:
  data/seed/{vendors,purchase_orders,po_lines}.csv   the "procurement system"
  data/samples/*.pdf                                 invoices (native and simulated scans)
  data/samples/manifest.json                         demo order, labels, expected outcomes
  data/samples/ground_truth.json                     what each PDF prints, keyed by sha256 —
                                                     used ONLY by tests as a stand-in for Claude

Usage: .venv/bin/python scripts/generate_data.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
SEED, SAMPLES = ROOT / "data" / "seed", ROOT / "data" / "samples"
BUYER = ["Meridian Manufacturing Corp", "400 Harbor Road", "Oakland, CA 94607"]

VENDORS = [
    dict(id="V-ACME", name="Acme Industrial Supply Ltd", tax_id="US-84-1234567", bank_last4="4821",
         currency="INR", tax_rate="0.08", address="1200 Foundry Ave, Gary, IN 46402"),
    dict(id="V-BOLT", name="Boltline Fasteners Inc", tax_id="US-27-5550199", bank_last4="3307",
         currency="INR", tax_rate="0.05", address="88 Rivet Street, Toledo, OH 43604"),
    dict(id="V-CREST", name="Crestline Office Supply Co", tax_id="US-61-7781204", bank_last4="1196",
         currency="INR", tax_rate="0.06", address="5 Market Plaza, Sacramento, CA 95814"),
    dict(id="V-NORD", name="Nordvik Pump Systems AS", tax_id="NO-912345678", bank_last4="6630",
         currency="INR", tax_rate="0", address="Industriveien 14, 4021 Stavanger, Norway"),
]
V = {v["id"]: v for v in VENDORS}

POS = [
    ("PO-1042", "V-ACME", "Steel widgets, Q4 build", [("WID-100", "Industrial widget, steel", 960, "50.00")]),
    ("PO-2050", "V-BOLT", "Fasteners, line 3 retrofit",
     [("BLT-M8", "Hex bolt M8 x 40, zinc", 1000, "6.00"), ("NUT-M8", "Hex nut M8, zinc", 2000, "3.00")]),
    ("PO-3101", "V-CREST", "Printer consumables",
     [("TN-450", "Toner cartridge, black", 20, "89.00"), ("TN-451", "Toner cartridge, colour", 10, "129.00")]),
    ("PO-3102", "V-CREST", "Office furniture", [("CH-200", "Ergonomic office chair", 12, "310.00")]),
    ("PO-3103", "V-CREST", "Paper, Oakland site", [("PP-A4", "Printer paper A4, box of 5 reams", 100, "42.00")]),
    ("PO-3104", "V-CREST", "Paper, Fremont site", [("PP-A4", "Printer paper A4, box of 5 reams", 100, "42.00")]),
    ("PO-4001", "V-NORD", "Cooling loop pumps", [("PMP-75", "Centrifugal pump 7.5 kW", 40, "1200.00")]),
]

WID = ("WID-100", "Industrial widget, steel")
BOLT, NUT = ("BLT-M8", "Hex bolt M8 x 40, zinc"), ("NUT-M8", "Hex nut M8, zinc")
TNK, TNC = ("TN-450", "Toner cartridge, black"), ("TN-451", "Toner cartridge, colour")
PAPER, CHAIR, PUMP = ("PP-A4", "Printer paper A4, box of 5 reams"), ("CH-200", "Ergonomic office chair"), \
    ("PMP-75", "Centrifugal pump 7.5 kW")

# Order = demo order. Each runs against the ledger state left by the ones before it.
INVOICES = [
    dict(id="e1-a", group="E1 · Split billing on PO-1042 (₹48,000)", label="A · bills ₹20,000 of the PO",
         vendor="V-ACME", number="INV-1042-A", date="2026-11-02", po="PO-1042", style="classic",
         lines=[(*WID, 400, "50.00")], expect=("APPROVE", None)),
    dict(id="e1-b", group="E1 · Split billing on PO-1042 (₹48,000)", label="B · claims ₹30,000 — exceeds the ₹28,000 left",
         vendor="V-ACME", number="INV-1042-B", date="2026-11-09", po="PO-1042", style="classic",
         lines=[(*WID, 600, "50.00")], expect=("HOLD", "EXCEEDS_OPEN_BALANCE")),
    dict(id="e1-c", group="E1 · Split billing on PO-1042 (₹48,000)", label="C · bills the remaining ₹28,000",
         vendor="V-ACME", number="INV-1042-C", date="2026-11-16", po="PO-1042", style="classic",
         lines=[(*WID, 560, "50.00")], expect=("APPROVE", None)),
    dict(id="e1-d", group="E1 · Split billing on PO-1042 (₹48,000)", label="D · ₹100 against the exhausted PO",
         vendor="V-ACME", number="INV-1042-D", date="2026-11-20", po="PO-1042", style="classic",
         lines=[(*WID, 2, "50.00")], expect=("HOLD", "PO_EXHAUSTED")),
    dict(id="e2-original", group="E2 · Disguised duplicate (PO-2050)", label="Original INV-2231",
         vendor="V-BOLT", number="INV-2231", date="2026-11-05", po="PO-2050", style="modern",
         lines=[(*BOLT, 500, "6.00"), (*NUT, 1000, "3.00")], expect=("APPROVE", None)),
    dict(id="e2-disguised", group="E2 · Disguised duplicate (PO-2050)", label="Resent as '2231-R', new layout",
         vendor="V-BOLT", number="2231-R", date="2026-11-05", po="PO-2050", style="minimal",
         lines=[(*BOLT, 500, "6.00"), (*NUT, 1000, "3.00")], expect=("HOLD", "SUSPECTED_DUPLICATE")),
    dict(id="e2-resubmit", group="E2 · Disguised duplicate (PO-2050)", label="Original file uploaded again (byte-identical)",
         same_file_as="e2-original", expect=("REJECT", "DUPLICATE_OF_APPROVED")),
    dict(id="e3-a", group="E3 · Scanned, no PO reference", label="Toner scan — one PO fits",
         vendor="V-CREST", number="CR-77812", date="2026-11-12", po=None, style="crest", scan=True,
         lines=[(*TNK, 20, "89.00"), (*TNC, 10, "129.00")], expect=("APPROVE", None)),
    dict(id="e3-b", group="E3 · Scanned, no PO reference", label="Paper scan — two POs fit equally",
         vendor="V-CREST", number="CR-77840", date="2026-11-14", po=None, style="crest", scan=True,
         lines=[(*PAPER, 60, "42.00")], expect=("HOLD", "PO_AMBIGUOUS")),
    dict(id="e4-a", group="E4 · Price and bank controls (PO-4001)", label="+4% unit price, bank unchanged",
         vendor="V-NORD", number="NV-5501", date="2026-11-03", po="PO-4001", style="nordic",
         lines=[(*PUMP, 10, "1248.00")], expect=("HOLD", "PRICE_VARIANCE")),
    dict(id="e4-b", group="E4 · Price and bank controls (PO-4001)", label="Exact price, bank details changed",
         vendor="V-NORD", number="NV-5502", date="2026-11-06", po="PO-4001", style="nordic", bank="9917",
         lines=[(*PUMP, 10, "1200.00")], expect=("HOLD", "BANK_CHANGED")),
    dict(id="e4-d", group="E4 · Price and bank controls (PO-4001)", label="Variance ₹500.25 — one step over the ₹500 cap",
         vendor="V-NORD", number="NV-5503", date="2026-11-10", po="PO-4001", style="nordic",
         lines=[(*PUMP, 25, "1220.01")], expect=("HOLD", "PRICE_VARIANCE")),
    dict(id="e4-c", group="E4 · Price and bank controls (PO-4001)", label="Variance exactly ₹500.00 — at the cap",
         vendor="V-NORD", number="NV-5504", date="2026-11-13", po="PO-4001", style="nordic",
         lines=[(*PUMP, 25, "1220.00")], expect=("APPROVE", None)),
    dict(id="x1", group="Other controls", label="Cites another vendor's PO (PO-1042)",
         vendor="V-CREST", number="CR-77901", date="2026-11-18", po="PO-1042", style="crest",
         lines=[(*CHAIR, 2, "310.00")], expect=("HOLD", "PO_VENDOR_MISMATCH")),
]

STYLES = {
    "classic": dict(font="Helvetica", bold="Helvetica-Bold", band=None, title="INVOICE", num_label="Invoice No.",
                    date_label="Invoice date", accent=colors.black),
    "modern": dict(font="Helvetica", bold="Helvetica-Bold", band=colors.HexColor("#1f3a5f"), title="TAX INVOICE",
                   num_label="Invoice #", date_label="Date", accent=colors.HexColor("#1f3a5f")),
    "minimal": dict(font="Times-Roman", bold="Times-Bold", band=None, title="Bill", num_label="Reference",
                    date_label="Issued", accent=colors.HexColor("#555555")),
    "crest": dict(font="Courier", bold="Courier-Bold", band=None, title="INVOICE", num_label="Invoice",
                  date_label="Date", accent=colors.black),
    "nordic": dict(font="Helvetica", bold="Helvetica-Bold", band=colors.HexColor("#0b6e4f"), title="Invoice",
                   num_label="Invoice no.", date_label="Invoice date", accent=colors.HexColor("#0b6e4f")),
}


def money(d: Decimal) -> str:
    return f"{d:,.2f}"


def compute(inv: dict) -> dict:
    vendor = V[inv["vendor"]]
    lines = []
    for sku, desc, qty, price in inv["lines"]:
        amount = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
        lines.append(dict(sku=sku, description=desc, quantity=str(qty), unit_price=price, amount=str(amount)))
    subtotal = sum(Decimal(l["amount"]) for l in lines)
    rate = Decimal(vendor["tax_rate"])
    tax = (subtotal * rate).quantize(Decimal("0.01")) if rate else None
    total = subtotal + (tax or 0)
    y, m, d = inv["date"].split("-")
    due = f"{y}-{int(m) + 1:02d}-{d}" if int(m) < 12 else f"{int(y) + 1}-01-{d}"
    return dict(lines=lines, subtotal=subtotal, tax=tax, total=total, rate=rate, due=due,
                bank=inv.get("bank", vendor["bank_last4"]))


def draw(path: Path, inv: dict, c_: dict) -> None:
    st, vendor = STYLES[inv["style"]], V[inv["vendor"]]
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    w, h = A4
    top = h - 50
    if st["band"]:
        c.setFillColor(st["band"]); c.rect(0, h - 95, w, 95, stroke=0, fill=1); c.setFillColor(colors.white)
    else:
        c.setFillColor(colors.black)
    c.setFont(st["bold"], 17); c.drawString(50, top - 5, vendor["name"])
    c.setFont(st["font"], 9)
    c.drawString(50, top - 22, vendor["address"])
    c.drawString(50, top - 34, f"Tax ID: {vendor['tax_id']}")
    c.setFont(st["bold"], 15); c.drawRightString(w - 50, top - 5, st["title"])
    c.setFillColor(colors.black)

    y = h - 130
    c.setFont(st["bold"], 9); c.drawString(50, y, "Bill to")
    c.setFont(st["font"], 9)
    for i, line in enumerate(BUYER):
        c.drawString(50, y - 13 - 12 * i, line)
    meta = [(st["num_label"], inv["number"]), (st["date_label"], inv["date"]), ("Due date", c_["due"])]
    if inv["po"]:
        meta.append(("PO number", inv["po"]))
    meta.append(("Currency", "INR"))
    for i, (k, v) in enumerate(meta):
        c.setFont(st["bold"], 9); c.drawString(340, y - 13 * i, k)
        c.setFont(st["font"], 9); c.drawString(430, y - 13 * i, v)

    y = h - 230
    c.setStrokeColor(st["accent"]); c.setLineWidth(1); c.line(50, y + 14, w - 50, y + 14)
    cols = [(50, "Item"), (125, "Description"), (350, "Qty"), (415, "Unit price"), (w - 50, "Amount")]
    c.setFont(st["bold"], 9)
    for x, t in cols:
        (c.drawRightString if t in ("Amount",) else c.drawString)(x, y, t)
    c.line(50, y - 6, w - 50, y - 6)
    c.setFont(st["font"], 9)
    for l in c_["lines"]:
        y -= 20
        c.drawString(50, y, l["sku"]); c.drawString(125, y, l["description"])
        c.drawString(350, y, l["quantity"]); c.drawString(415, y, money(Decimal(l["unit_price"])))
        c.drawRightString(w - 50, y, money(Decimal(l["amount"])))
    y -= 14; c.line(330, y, w - 50, y)
    rows = [("Subtotal", money(c_["subtotal"]))]
    if c_["tax"] is not None:
        rows.append((f"Sales tax ({c_['rate'] * 100:.0f}%)", money(c_["tax"])))
    else:
        rows.append(("Tax", "Exempt — export sale"))
    rows.append(("Total due (INR)", money(c_["total"])))
    for i, (k, v) in enumerate(rows):
        yy = y - 18 - 16 * i
        c.setFont(st["bold"] if i == len(rows) - 1 else st["font"], 10)
        c.drawString(350, yy, k); c.drawRightString(w - 50, yy, v)

    c.setFont(st["font"], 8)
    c.drawString(50, 110, "Remit to:")
    c.drawString(50, 98, f"{vendor['name']}  ·  Account ending {c_['bank']}  ·  Net 30")
    c.drawString(50, 86, "Please quote the invoice number with your payment.")
    c.save()


def scanify(src: Path, dst: Path, seed: int) -> None:
    img = pdfium.PdfDocument(str(src))[0].render(scale=150 / 72).to_pil().convert("L")
    rnd = random.Random(seed)
    img = img.rotate(rnd.uniform(0.8, 1.8), expand=True, fillcolor=250, resample=Image.BICUBIC)
    px = img.load()
    for _ in range(img.width * img.height // 70):
        px[rnd.randrange(img.width), rnd.randrange(img.height)] = rnd.randrange(110, 245)
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    img.save(dst, "PDF", resolution=150)


def ground_truth(inv: dict, c_: dict) -> dict:
    ev = [dict(field="invoice_number", page=1, snippet=inv["number"]),
          dict(field="subtotal", page=1, snippet=f"Subtotal {money(c_['subtotal'])}"),
          dict(field="total", page=1, snippet=f"Total due (INR) {money(c_['total'])}")]
    if inv["po"]:
        ev.append(dict(field="po_references", page=1, snippet=f"PO number {inv['po']}"))
    if c_["tax"] is not None:
        ev.append(dict(field="tax", page=1, snippet=money(c_["tax"])))
    for i, l in enumerate(c_["lines"]):
        row = f"{l['sku']} {l['description']} {l['quantity']} {money(Decimal(l['unit_price']))} {money(Decimal(l['amount']))}"
        for f in ("quantity", "unit_price", "amount"):
            ev.append(dict(field=f"line_items[{i}].{f}", page=1, snippet=row))
    vendor = V[inv["vendor"]]
    return dict(
        vendor_name=vendor["name"], vendor_tax_id=vendor["tax_id"], bank_account_last4=c_["bank"],
        invoice_number=inv["number"], invoice_date=inv["date"], due_date=c_["due"], currency="INR",
        po_references=[inv["po"]] if inv["po"] else [], line_items=c_["lines"],
        subtotal=str(c_["subtotal"]), tax=None if c_["tax"] is None else str(c_["tax"]), total=str(c_["total"]),
        tax_treatment="separate" if c_["tax"] is not None else "none",
        evidence=ev, unreadable_fields=[], notes=None)


def write_seed() -> None:
    SEED.mkdir(parents=True, exist_ok=True)
    with open(SEED / "vendors.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "name", "tax_id", "bank_last4", "currency", "tax_rate"])
        for v in VENDORS:
            w.writerow([v["id"], v["name"], v["tax_id"], v["bank_last4"], v["currency"], v["tax_rate"]])
    with open(SEED / "purchase_orders.csv", "w", newline="") as f, open(SEED / "po_lines.csv", "w", newline="") as g:
        w, wl = csv.writer(f, lineterminator="\n"), csv.writer(g)
        w.writerow(["id", "vendor_id", "currency", "status", "total", "description"])
        wl.writerow(["po_id", "line_no", "sku", "description", "qty", "unit_price"])
        for po_id, vid, desc, lines in POS:
            total = sum(Decimal(q) * Decimal(p) for _, _, q, p in lines)
            w.writerow([po_id, vid, "INR", "open", f"{total:.2f}", desc])
            for n, (sku, d, q, p) in enumerate(lines, 1):
                wl.writerow([po_id, n, sku, d, q, p])


def main() -> None:
    write_seed()
    SAMPLES.mkdir(parents=True, exist_ok=True)
    for old in SAMPLES.glob("*.pdf"):
        old.unlink()
    truth, manifest = {}, []
    for n, inv in enumerate(INVOICES):
        if "same_file_as" in inv:
            file = f"{inv['same_file_as']}.pdf"
        else:
            c_ = compute(inv)
            file = f"{inv['id']}.pdf"
            if inv.get("scan"):
                tmp = SAMPLES / f"_{inv['id']}_native.pdf"
                draw(tmp, inv, c_); scanify(tmp, SAMPLES / file, seed=n); tmp.unlink()
            else:
                draw(SAMPLES / file, inv, c_)
            sha = hashlib.sha256((SAMPLES / file).read_bytes()).hexdigest()
            truth[sha] = ground_truth(inv, c_)
        manifest.append(dict(id=inv["id"], file=file, group=inv["group"], label=inv["label"],
                             scan=bool(inv.get("scan")), expected_decision=inv["expect"][0],
                             expected_rule=inv["expect"][1]))
    (SAMPLES / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (SAMPLES / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    print(f"seed: {len(VENDORS)} vendors, {len(POS)} POs · samples: {len(truth)} PDFs, {len(manifest)} demo steps")


if __name__ == "__main__":
    main()
