# Invoice Decision Agent (Zamp ASA case study · PS-1)

You upload an invoice PDF. The agent produces a reasoned **APPROVE / HOLD / REJECT** decision and posts approvals to a PO ledger. Every stage streams live into the UI.

**Design principle:** Claude *reads* the invoice and *explains* the decision; deterministic rules *decide*.

The claim we stand behind is: *given the extracted fields, the PO state, and the policy version, the decision is reproducible.* Extraction is the one part that isn't deterministic, so it is verified rather than trusted:
- quantity × unit price is checked on every line, and the totals are checked;
- every critical number is cross-checked against the PDF's own text layer;
- scans that can't be checked that way need page evidence for every critical field.

See [DECISION_POLICY.md](DECISION_POLICY.md), [PROCESS_MAP.md](PROCESS_MAP.md), [ASSUMPTIONS.md](ASSUMPTIONS.md).

## Run locally
```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install && npm run build)          # UI is served by the API
export ANTHROPIC_API_KEY=...                            # needed to read new PDFs
cd backend && ../.venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000
```
For UI development, run `npm run dev` in `frontend/`. It proxies `/api` to port 8000.

## Tests
```bash
cd backend && ../.venv/bin/pytest -q
```
Tests use an isolated SQLite file per test. They replace Claude with `FixtureExtractor`, which returns what each generated PDF actually prints (`data/samples/ground_truth.json`). What they cover:
- the E1 sequence, with the balance asserted after every invoice;
- E2, both the disguised duplicate and the byte-identical resubmission;
- E3, both the inferred PO and the ambiguous one;
- a consistent misread caught by the text-layer check;
- a PO that belongs to another vendor;
- the exact price-cap boundaries;
- retry idempotency, and parallel approvals that must not overspend a PO;
- the HTTP and SSE surface;
- the full demo order (`test_demo_sequence.py`).

## Scenarios (`data/samples/`, regenerate with `scripts/generate_data.py`)
| Scenario | What it shows |
|---|---|
| **E1** Split billing on PO-1042 ($48,000) | A $20,000 → APPROVE ($28,000 left) · B $30,000 → HOLD `EXCEEDS_OPEN_BALANCE` (still $28,000) · C $28,000 → APPROVE ($0) · D $100 → HOLD `PO_EXHAUSTED` |
| **E2** Disguised duplicate | `INV-2231` → APPROVE · resent as `2231-R` in a new layout → HOLD `SUSPECTED_DUPLICATE`, linked to the original · same file again → REJECT `DUPLICATE_OF_APPROVED` |
| **E3** Scans, no PO number | Toner → inferred PO-3101 and APPROVE · Paper fits PO-3103 and PO-3104 equally → HOLD `PO_AMBIGUOUS`, with both candidates shown |
| **E4** (stretch) | +4% price with unchanged bank → `PRICE_VARIANCE` · exact price with changed bank → `BANK_CHANGED` · $500.25 over → HOLD · exactly $500.00 → APPROVE |
| x1 | Cites another vendor's real PO → HOLD `PO_VENDOR_MISMATCH` |

**Fresh-input check:** `data/fresh/` is for a PDF that wasn't produced by the generator (for example, one typed in Google Docs and exported). No test fixture or cache covers it.

## Deploy (Render)
`render.yaml` defines a Docker web service. It mounts a 1 GB disk at `/data` for SQLite and uploads, which needs a paid instance. Set `ANTHROPIC_API_KEY` in the dashboard. `ADMIN_TOKEN` is generated automatically and protects **Reset demo ledger** on the public URL.

## Config (env)
| Variable | Default | Purpose |
|---|---|---|
| `EXTRACT_MODEL` / `EXPLAIN_MODEL` | `claude-opus-5-5` | Model used for each call. Both calls enable server-side refusal fallback. |
| `EXTRACT_EFFORT` | `medium` | Effort level for extraction |
| `STAGE_PACING_MS` | `250` | Short pause between the instant rule stages so the live timeline is readable. Set `0` to disable. |
| `DATA_DIR` | `./data` | Location of the database and uploaded PDFs |
| `ADMIN_TOKEN` | unset | Required for reset when set |
