import hashlib
import io

from pypdf import PdfReader


def inspect_pdf(pdf_bytes: bytes) -> dict:
    """sha256, page count and the PDF's own text layer (empty for scans)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    return {
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "pages": len(reader.pages),
        "text": text,
        "has_text_layer": len(text.strip()) >= 20,
    }
