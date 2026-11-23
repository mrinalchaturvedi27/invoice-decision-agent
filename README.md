# Invoice Decision Agent

[Open the live demo](https://invoice-decision-agent-ok4z.onrender.com/). Use the reviewer passcode to start a run.

A Zamp AI Solutions Analyst case study for PS-1. Upload an invoice PDF and get an **Approve**, **Hold**, or **Reject** decision against seeded vendor and purchase order (PO) records in INR. The app streams each check as it runs and keeps the PDF, rule trace, and PO balance in History. Held and rejected invoices include a next step for accounts payable (AP).

## Run locally

Use Python 3.13 and Node.js 22. Run these commands from the repository root.

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
export ANTHROPIC_API_KEY=your_key_here
(cd backend && ../.venv/bin/uvicorn app.main:app --port 8000)
```

Open [localhost:8000](http://localhost:8000). Use the prepared samples or upload a synthetic invoice.

## Try the demo

Start with **E1·A**, then run **E1·B**. Each browser starts with a fresh ledger. To replay the sequence, go to **History** and select **Reset my sandbox**.

| Scenario | Expected result |
| --- | --- |
| E1 · Split billing | A ₹20,000 invoice is approved against a ₹48,000 PO. The next ₹30,000 invoice is held because only ₹28,000 remains. |
| E2 · Duplicate | The original is approved. A reformatted copy with a changed invoice number is held and linked to the original. An exact resubmission is rejected. |
| E3 · Scan with no PO number | The toner invoice has one clear match and is approved. The paper invoice fits two POs equally and is held with both candidates shown. |
| E4 · Price and bank details | Separate samples test an excessive price increase, changed bank details, and the exact price tolerance boundary. |

## How it decides

Claude extracts fields from native and scanned PDFs. Python checks the invoice math, vendor, duplicate history, and PO line quantities and prices. An approval records the decision and updates the SQLite ledger in one transaction. Claude summarizes the stored result, and the deciding rule supplies the next step for AP.

The FastAPI backend serves the React UI and streams run updates via server-sent events. See the [process map](PROCESS_MAP.md), [decision policy](DECISION_POLICY.md), and [assumptions](ASSUMPTIONS.md) for the workflow, thresholds, and scope.

## Verify

```sh
(cd backend && ../.venv/bin/pytest -q)
```

Tests use fixture extractions and isolated databases. With an API key, run `.venv/bin/python scripts/rehearse.py` from the repository root to check live extraction against the sample PDFs. To test another layout, upload the [independently authored invoice](data/fresh/crestline-chairs-chrome.pdf).

The INR demo uses a fresh SQLite ledger at `data/inr/app.db`. Previous USD demo files remain in their original locations.

## Deploy on Render

[render.yaml](render.yaml) defines a free Docker service. SQLite and uploads use ephemeral storage at `/data`. Set `ANTHROPIC_API_KEY` and `REVIEWER_PASSCODE` in Render. Share the passcode with reviewers so they can start runs. `MODEL_CALLS_PER_DAY` caps live Claude calls across all sandboxes and defaults to 300 per rolling 24 hours.

Use synthetic invoices on the hosted demo. Anyone with a sandbox ID can read its runs and PDFs.
