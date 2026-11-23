# Process Map

```
 PDF upload
    │
 1. INGEST ─────────── sha256, page count, text layer? (native | scanned)
    │
 2. EXTRACT (Claude) ─ structured fields + page evidence      [cache by sha256, labelled in UI]
    │
 3. DUPLICATES ─────── byte-identical approved? → REJECT
    │                  same vendor+number / vendor+total+≤14d? → HOLD (link original)
 4. EXTRACTION CHECKS  line math, totals, text-layer cross-check, legibility, tax basis → HOLD
    │
 5. PO RESOLVE ─────── explicit ref: exists, owner, currency, open, lines map
    │                  no ref: best candidate ≥0.80 and lead ≥0.15, else HOLD with candidates
 6. CONSUMPTION ────── unit price vs PO line, qty vs open qty, subtotal vs open balance (ceiling),
    │                  exhausted PO, tax rate, bank details
 7. DECIDE ─────────── first failing rule = deciding rule; else APPROVE
    │                  APPROVE → one transaction: re-check balance, write allocations
 8. EXPLAIN (Claude) ─ AP-manager summary from the rule trace; fallback = template sentence
    │
 Decision + trace + balance before/after → History
```

Every stage writes a `run_steps` row (status, duration, inputs, outputs) and streams it to the run view over SSE.

**Decision points a human sees:**
- **HOLD:** always shows the deciding rule, the evidence, and what would clear it.
- **REJECT:** only for a byte-identical resubmission of an invoice that was already approved.
