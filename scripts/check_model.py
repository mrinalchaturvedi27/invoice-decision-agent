"""Day-1 de-risk: one UNCACHED extraction on a native PDF and on an image-only (scanned) PDF.

Usage:  .venv/bin/python scripts/check_model.py
Needs:  ANTHROPIC_API_KEY in the environment.
"""
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import pypdfium2 as pdfium  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.pipeline.extract import extract_invoice  # noqa: E402

OUT = ROOT / "data" / "check"
LINES = [("WID-100", "Industrial widget, steel", 400, "50.00")]


def make_native(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 16); c.drawString(50, h - 60, "Acme Industrial Supply Ltd")
    c.setFont("Helvetica", 10)
    c.drawString(50, h - 78, "Tax ID: US-84-1234567   Bank acct ending 4821")
    c.drawString(380, h - 60, "INVOICE  INV-1042-A")
    c.drawString(380, h - 76, "Date: 2026-11-20   Due: 2026-12-20")
    c.drawString(380, h - 92, "PO: PO-1042   Currency: USD")
    y = h - 140
    c.setFont("Helvetica-Bold", 10)
    for x, t in [(50, "SKU"), (120, "Description"), (330, "Qty"), (380, "Unit price"), (470, "Amount")]:
        c.drawString(x, y, t)
    c.setFont("Helvetica", 10)
    subtotal = 0
    for sku, desc, qty, price in LINES:
        y -= 18
        amt = qty * float(price); subtotal += amt
        for x, t in [(50, sku), (120, desc), (330, str(qty)), (380, price), (470, f"{amt:,.2f}")]:
            c.drawString(x, y, t)
    tax = round(subtotal * 0.08, 2)
    for i, (k, v) in enumerate([("Subtotal", subtotal), ("Tax (8%)", tax), ("Total", subtotal + tax)]):
        c.drawString(380, y - 40 - 16 * i, k); c.drawString(470, y - 40 - 16 * i, f"{v:,.2f}")
    c.save()


def make_scanned(native: Path, path: Path) -> None:
    page = pdfium.PdfDocument(str(native))[0]
    img = page.render(scale=150 / 72).to_pil().convert("L")
    img = img.rotate(1.3, expand=True, fillcolor=255, resample=Image.BICUBIC)
    rnd = random.Random(7)
    px = img.load()
    for _ in range(img.width * img.height // 60):
        px[rnd.randrange(img.width), rnd.randrange(img.height)] = rnd.randrange(120, 255)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img.save(path, "PDF", resolution=150)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    native, scanned = OUT / "native.pdf", OUT / "scanned.pdf"
    make_native(native); make_scanned(native, scanned)
    for p in (native, scanned):
        t0 = time.time()
        result, meta = extract_invoice(p.read_bytes())
        print(f"\n=== {p.name}  ({time.time() - t0:.1f}s, {meta['model']}, {meta['request_id']}, "
              f"in={meta['input_tokens']} out={meta['output_tokens']})")
        print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    main()
