# Assumptions

- PO amounts are stored pre-tax. Each vendor has one expected tax rate.
- One invoice references at most one PO. An invoice that references several POs is HOLD (`MULTI_PO`).
- The demo ledger and seeded POs use INR. A different invoice currency triggers HOLD. The app does not convert currencies.
- "Bank last-4" stands in for full remittance details. A real system would verify the full IBAN or account number out of band.
- Vendor master, POs, and invoices are generated test data, which Zamp's FAQ allows. One PDF in `data/fresh/` is produced independently of the generator, as a fresh-input check.
- Approved = scheduled for payment. Payment execution is out of scope.
- An exhausted PO accepts no further charges. Freight or late fees against a closed PO need a PO amendment, so they get HOLD.

## Not yet covered (next controls)
- **Goods receipt (three-way match).** The app checks ordered against billed, not received. With receipts, an invoice billing 100 open units when the warehouse has received 60 would be held, showing the 40-unit discrepancy. This is the next control to build after the demo.
