# Decision Policy — v2

Every decision stores `policy_version = "v2"`. Thresholds live in `backend/app/policy.py`.

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
- Every invoice line must map to exactly one PO line:
  - An **exact SKU match decides**, even when another PO line has the same description (two "Air filter" lines, FILT-A and FILT-B).
  - Without a SKU match, the description must reach a similarity of 0.80.
  - If another PO line scores within 0.05 of the best, the line is ambiguous: HOLD `LINE_AMBIGUOUS`, listing the candidate PO lines. It is never guessed, because a guess would consume the wrong line's quantity.
  - No match → HOLD `LINE_UNMAPPED`, which also covers bundled lines.

**No reference:**
- Score each open PO for the vendor (amount fit, line similarity).
- Accept the top candidate only if its score is ≥ **0.80** and its lead over the runner-up is ≥ **0.15**.
- Otherwise HOLD `PO_AMBIGUOUS`, listing the candidates with their scores.

## 3. Consumption (the open balance is a ceiling)
All comparisons are **pre-tax**. An invoice must pass **every** check below. For example, a full ₹48,000 bill at +1% is within the price tolerance (₹480 ≤ ₹500) but exceeds the open balance by ₹480, so it is held. Both controls exist for that reason.
- **Price:** for each line, variance = (invoice unit price − PO unit price) × billed qty.
  - Allowed variance = min(2% × PO unit price × billed qty, ₹500).
  - Over the allowance → HOLD `PRICE_VARIANCE`.
- **Quantity:** billed qty ≤ open qty on the PO line (else HOLD `QTY_EXCEEDS_OPEN`).
- **Amount:** subtotal ≤ the PO's open pre-tax balance (else HOLD `EXCEEDS_OPEN_BALANCE`). There is zero tolerance above the ceiling.
- **Exhausted PO:** open balance = 0 → HOLD `PO_EXHAUSTED`. No further charges of any size.
- **Tax:** tax ÷ subtotal must be within ±0.5 percentage points of the vendor's expected rate (else HOLD `TAX_RATE`).
- **Bank details:** the invoice's bank last-4 ≠ the vendor master → HOLD `BANK_CHANGED`.
- **Persistence:** an approval is written in one `BEGIN IMMEDIATE` transaction. Inside it, the ledger:
  - re-checks duplicates: the byte-identical file and the §4 business-duplicate rules, against invoices approved since the duplicate stage looked. Two copies of one invoice racing each other give one APPROVE and one HOLD `SUSPECTED_DUPLICATE` linked to the winner;
  - re-reads the open balance and quantities. If they changed since the decision was computed, it re-decides on fresh state;
  - writes the line allocations **and the run's decision with its before/after balances**. A posting never exists without its recorded verdict.

## 4. Runs, invoices, retries, duplicates
- A **run** is one processing attempt. An **invoice** is one document, keyed by its SHA-256.
- Retrying a step inside a run reuses that run and invoice. The duplicate check always excludes the invoice's own record.
- **A recorded decision is final.** HOLD and REJECT are recorded in one write at the decide stage, before the summary is written, and APPROVE is recorded in the posting transaction. A retry of a decided run resumes at the explanation and never re-decides. The run detail shows the verdict while the summary is being written.
- **REJECT `DUPLICATE_OF_APPROVED`:** the byte-identical file of an invoice that was already approved.
- **HOLD `SUSPECTED_DUPLICATE`**, linked to the earlier invoice:
  - same vendor and the same normalised invoice number, or
  - same vendor, same total in the same currency, and an invoice date within 14 days.

## Evaluation order
1. Duplicates
2. Extraction checks
3. PO resolution
4. Consumption

The first failing rule becomes the **deciding rule** shown to the reviewer. All other rule results are still recorded in the trace.

## Next step for the reviewer
Every HOLD and REJECT carries one instruction for AP, chosen by the deciding rule from the data recorded with it (`backend/app/pipeline/next_steps.py`). It is as reproducible as the decision; the model's summary does not write it. For example:
- `EXCEEDS_OPEN_BALANCE`: "Request a corrected invoice or an approved PO amendment."
- `PO_AMBIGUOUS`: "Confirm whether this invoice belongs to PO-3103 or PO-3104." It names only the POs within the required lead of the best fit.
- `SUSPECTED_DUPLICATE`: compare with the named approved invoice and its run.
