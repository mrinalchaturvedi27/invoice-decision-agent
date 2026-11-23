# Invoice Decision Agent (Zamp ASA case study · PS-1)

You upload an invoice PDF. The agent produces a reasoned **APPROVE / HOLD / REJECT** decision and posts approvals to a PO ledger. Every stage streams live into the UI.

**Design principle:** Claude *reads* the invoice and *explains* the decision; deterministic rules *decide*.

The claim we stand behind is: *given the extracted fields, the PO state, and the policy version, the decision is reproducible.* Extraction is the one part that isn't deterministic, so it is verified rather than trusted:
- quantity × unit price is checked on every line, and the totals are checked;
- each critical number must appear somewhere in the PDF's own text layer;
- the billed quantities and prices are then compared line by line with the PO, which catches a real number put on the wrong row;
- scans have no text layer, so each decision-critical field needs its own page-evidence entry. That evidence comes from the same model read, so on scans the PO comparison is the independent check.

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
- two copies of one invoice racing to the ledger, giving one APPROVE and one HOLD linked to the winner;
- a crash after posting, where the retry resumes from the recorded decision instead of re-deciding;
- sandbox isolation and reset;
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

## Sandboxes: who can see what (hosted demo)
- **Each browser gets its own sandbox ledger.** That is a separate SQLite file seeded with the same vendors and POs, keyed by a random 128-bit ID the page keeps in localStorage. Every reviewer starts from the seed, so E1·A always shows the advertised $48,000 → $28,000, whatever other reviewers have run.
- The scenario list shows which steps have already run in your sandbox, with their actual results, and marks the next step. **History → Reset my sandbox** restores the seed without an admin token. **New sandbox** starts a fresh one and leaves the old one as it was.
- **This is isolation, not access control.** There are no accounts, so anyone holding a sandbox ID can read that sandbox's runs and PDFs. The upload panel says this, so use synthetic invoices only. Confidential uploads would need real authentication in front of `/api/*`.
- Requests that send no sandbox ID (curl, scripts) use the default database. Its reset needs `ADMIN_TOKEN`. The server caps sandboxes at `MAX_SANDBOXES` (500).

## First keyed rehearsal
```bash
export ANTHROPIC_API_KEY=...
.venv/bin/python scripts/rehearse.py                       # E1·A, E1·B, both scans: uncached, field by field
.venv/bin/python scripts/rehearse.py data/fresh/mine.pdf   # plus an independently authored PDF
```
For each generated sample, the script makes a live extraction call and compares it field by field with what the PDF actually prints. It reports latency, mismatched values, and missing evidence even when the final decision would match. For a fresh PDF it prints the extraction and the verification rules it would face. It never touches the app database.

**Result on 2026-11-23 (`claude-opus-5-5`, no cache):**
- All 13 generated PDFs matched every printed field, with full evidence coverage on both scans. Each took 4.6–9.4 s.
- Through the app, on a fresh ledger with an empty cache, all 14 demo steps reached their expected decision. Every explanation was written by Claude.
- `data/fresh/crestline-chairs-chrome.pdf` was handwritten in HTML and printed by Chrome, so it went through neither the generator nor reportlab. Uploaded, it was approved against PO-3102, taking the balance from $3,720.00 to $1,240.00, in 9.8 s.

## Deploy (Render)
`render.yaml` defines a Docker web service. It mounts a 1 GB disk at `/data` for SQLite and uploads, which needs a paid instance. Set `ANTHROPIC_API_KEY` in the dashboard. `ADMIN_TOKEN` is generated automatically and protects **Reset demo ledger** on the public URL.

**Local container check (2026-11-23).** The image was run the way Render runs it: `PORT=10000`, an admin token, a volume mounted at `/data`, and a live key.
- E1·A was approved, taking PO-1042 from $48,000 to $28,000.
- E1·B was held, leaving $28,000.
- The fresh Chrome-printed PDF was approved.
- The live stream ended cleanly.
- Reset was refused (403) with no token or the wrong one, and a file that wasn't a PDF was refused (415).
- Runs and balances were still there after a container restart.

## Config (env)
| Variable | Default | Purpose |
|---|---|---|
| `EXTRACT_MODEL` / `EXPLAIN_MODEL` | `claude-opus-5-5` | Model used for each call. Both calls enable server-side refusal fallback. |
| `EXTRACT_EFFORT` | `medium` | Effort level for extraction |
| `STAGE_PACING_MS` | `250` | Short pause between the instant rule stages so the live timeline is readable. Set `0` to disable. |
| `DATA_DIR` | `./data` | Location of the database and uploaded PDFs |
| `ADMIN_TOKEN` | unset | When set, required to reset the default (non-sandbox) database |
| `MAX_SANDBOXES` | `500` | Cap on per-browser sandbox databases |
