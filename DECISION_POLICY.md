# Decision Policy — v1

Every decision stores `policy_version = "v1"`. Thresholds live in `backend/app/policy.py`.

**The claim:** given the extracted fields, the PO/ledger state, and the policy version, the decision is
reproducible. Determinism starts *after* extraction, so the checks in §1 exist to catch extraction error.

Outcomes:
- **APPROVE** — allocate against the PO.
- **HOLD** — route to a human with a named reason; ledger untouched.
- **REJECT** — the only reject case is §4; ledger untouched.

## 1. Extraction checks (the model reads; rules verify)
| Check | Rule | On failure |
|---|---|---|
| Line arithmetic | qty × unit price = line amount (±0.01) for every line | HOLD `LINE_MATH` |
| Totals | Σ lines = subtotal; subtotal + tax = total (±0.01) | HOLD `TOTAL_MATH` |
| Text-layer presence (native PDFs) | Every critical value (invoice no., PO ref, qty, unit price, line amounts, subtotal, tax, total) appears *somewhere* in the PDF's own text layer (`pypdf`, independent of the model). Presence only: a real number assigned to the wrong row still passes, which the §3 per-line PO comparison then has to catch | HOLD `NOT_IN_TEXT_LAYER` |
| Scan legibility | The model reports any critical field as unreadable | HOLD `UNREADABLE_FIELD` |
| Scan evidence | Each decision-critical field has its **own** non-empty page-evidence entry: invoice no., PO ref (if printed), subtotal, tax (if charged), total, and quantity, unit price, and amount for every line. Evidence for one field never vouches for another. The model reports evidence from the same read as the values, so this checks completeness, not truth | HOLD `MISSING_EVIDENCE` |
| Missing essentials | No invoice number or no total | HOLD `MISSING_FIELD` |
| Tax basis | Tax treatment must be `separate` or `none`; `inclusive` or `unclear` prevents a like-for-like comparison | HOLD `TAX_BASIS` |

## 2. PO resolution (verify after lookup)
**Explicit reference:**
- The PO must exist.
- It must belong to the invoicing vendor (else HOLD `PO_VENDOR_MISMATCH`, a fraud flag).
- The currency must match.
- The status must be `open`.
- Every invoice line must map to a PO line by SKU or description (else HOLD `LINE_UNMAPPED`, which also covers bundled lines).

**No reference:**
- Score each open PO for the vendor (amount fit, line similarity).
- Accept the top candidate only if its score is ≥ **0.80** and its lead over the runner-up is ≥ **0.15**.
- Otherwise HOLD `PO_AMBIGUOUS`, listing the candidates with their scores.

## 3. Consumption (the open balance is a ceiling)
All comparisons are **pre-tax**. An invoice must pass **every** check below. For example, a full $48,000 bill at +1% is within the price tolerance ($480 ≤ $500) but exceeds the open balance by $480, so it is held. Both controls exist for that reason.
- **Price:** for each line, variance = (invoice unit price − PO unit price) × billed qty.
  - Allowed variance = min(2% × PO unit price × billed qty, $500).
  - Over the allowance → HOLD `PRICE_VARIANCE`.
- **Quantity:** billed qty ≤ open qty on the PO line (else HOLD `QTY_EXCEEDS_OPEN`).
- **Amount:** subtotal ≤ the PO's open pre-tax balance (else HOLD `EXCEEDS_OPEN_BALANCE`). There is zero tolerance above the ceiling.
- **Exhausted PO:** open balance = 0 → HOLD `PO_EXHAUSTED`. No further charges of any size.
- **Tax:** tax ÷ subtotal must be within ±0.5 percentage points of the vendor's expected rate (else HOLD `TAX_RATE`).
- **Bank details:** the invoice's bank last-4 ≠ the vendor master → HOLD `BANK_CHANGED`.
- **Persistence:** an approval is written in one `BEGIN IMMEDIATE` transaction.
  - The transaction re-reads the open balance and quantities, writes the line allocations, and records before/after balances.
  - If state changed since the decision was computed, it re-decides on fresh state.

## 4. Runs, invoices, retries, duplicates
- A **run** is one processing attempt. An **invoice** is one document, keyed by its SHA-256.
- Retrying a step inside a run reuses that run and invoice. The duplicate check always excludes the invoice's own record.
- **REJECT `DUPLICATE_OF_APPROVED`:** the byte-identical file of an invoice that was already approved.
- **HOLD `SUSPECTED_DUPLICATE`**, linked to the earlier invoice:
  - same vendor and the same normalised invoice number, or
  - same vendor, same total, and an invoice date within 14 days.

## Evaluation order
1. Duplicates
2. Extraction checks
3. PO resolution
4. Consumption

The first failing rule becomes the **deciding rule** shown to the reviewer. All other rule results are still recorded in the trace.
