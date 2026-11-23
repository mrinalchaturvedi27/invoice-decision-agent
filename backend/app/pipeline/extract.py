"""Stage 2: structured extraction from an invoice PDF with Claude.

The model transcribes; it never computes or corrects. Every downstream rule treats this
output as a claim to be verified (see DECISION_POLICY.md §1).
"""
from __future__ import annotations

import base64
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field

from app.config import EXTRACT_EFFORT, EXTRACT_MODEL

MoneyStr = Optional[str]  # decimal string as printed, without symbols or thousands separators


class Evidence(BaseModel):
    field: str = Field(description="Exact field name, e.g. 'total', 'po_references' or 'line_items[0].unit_price'")
    page: int = Field(description="1-indexed page number")
    snippet: str = Field(description="Verbatim text from the page that this value was read from")


class LineItem(BaseModel):
    description: str
    sku: Optional[str] = None
    quantity: MoneyStr = None
    unit_price: MoneyStr = None
    amount: MoneyStr = None


class InvoiceExtraction(BaseModel):
    vendor_name: Optional[str]
    vendor_tax_id: Optional[str]
    bank_account_last4: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[str] = Field(description="YYYY-MM-DD, or null")
    due_date: Optional[str] = Field(description="YYYY-MM-DD, or null")
    currency: Optional[str] = Field(description="ISO 4217 code, or null if not determinable")
    po_references: list[str]
    line_items: list[LineItem]
    subtotal: MoneyStr
    tax: MoneyStr
    total: MoneyStr
    tax_treatment: Literal["separate", "inclusive", "none", "unclear"]
    evidence: list[Evidence]
    unreadable_fields: list[str] = Field(
        description="Fields that are present on the page but cannot be read with confidence"
    )
    notes: Optional[str]


SYSTEM = """You extract data from vendor invoices for an accounts-payable control system.

Rules:
- Transcribe values exactly as printed. Never compute, infer, round, or correct a value.
- Money and quantities: decimal strings without currency symbols or thousands separators ("20000.00").
- Currency: use the printed ISO code or an unambiguous symbol. The ₹ symbol means INR.
- If a value is absent from the document, return null. If it is present but you cannot read it
  with confidence, return null AND list the field name in unreadable_fields.
- po_references: only PO numbers explicitly printed on the invoice; empty list if none.
- tax_treatment: "separate" if tax is a distinct amount, "inclusive" if prices include tax with no
  separate amount, "none" if no tax applies, "unclear" otherwise.
- evidence: one entry per field, using exactly these field names: invoice_number, po_references, subtotal,
  tax, total, and for each line i: line_items[i].quantity, line_items[i].unit_price, line_items[i].amount.
  Give the page and the verbatim snippet you read that value from. Omit an entry only if you did not
  read that value from the page.
- notes: anything an AP reviewer should know (bundled lines, handwritten edits, credit notes)."""


class ClaudeExtractor:
    """Runner-facing extractor: returns (extraction dict, meta)."""

    def __call__(self, pdf_bytes: bytes) -> tuple[dict, dict]:
        import os
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise RuntimeError("ANTHROPIC_API_KEY is not set on the server, so the invoice can't be read")
        result, meta = extract_invoice(pdf_bytes)
        return result.model_dump(), meta


def extract_invoice(pdf_bytes: bytes, client: anthropic.Anthropic | None = None) -> tuple[InvoiceExtraction, dict]:
    """Returns (extraction, meta). meta carries model, request id and usage for the run trace."""
    client = client or anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=EXTRACT_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": EXTRACT_EFFORT},
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
                    },
                },
                {"type": "text", "text": "Extract this invoice."},
            ],
        }],
        output_format=InvoiceExtraction,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Extraction refused: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Extraction truncated at max_tokens")
    meta = {
        "model": response.model,
        "request_id": response._request_id,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return response.parsed_output, meta
