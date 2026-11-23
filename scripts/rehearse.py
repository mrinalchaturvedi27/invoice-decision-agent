"""First keyed rehearsal: UNCACHED extraction, inspected field by field — not just the final decision.

Usage:
  .venv/bin/python scripts/rehearse.py                        # default: e1-a e1-b e3-a e3-b
  .venv/bin/python scripts/rehearse.py e2-disguised x1        # any sample ids
  .venv/bin/python scripts/rehearse.py data/fresh/mine.pdf    # an independently authored PDF
  .venv/bin/python scripts/rehearse.py --fixture              # dry run of this script (no model call)

Generated samples are compared with what the PDF actually prints (data/samples/ground_truth.json).
Never touches the app database or the extraction cache.
"""
import hashlib
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.money import D  # noqa: E402
from app.pipeline.checks import normalise_field, required_evidence, run_checks  # noqa: E402
from app.pipeline.ingest import inspect_pdf  # noqa: E402

SAMPLES = ROOT / "data" / "samples"
MANIFEST = {m["id"]: m for m in json.loads((SAMPLES / "manifest.json").read_text())}
TRUTH = json.loads((SAMPLES / "ground_truth.json").read_text())
HEADER = ["vendor_name", "vendor_tax_id", "bank_account_last4", "invoice_number", "invoice_date", "currency",
          "po_references", "subtotal", "tax", "total", "tax_treatment"]


def same(a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return [str(x).strip().upper() for x in a or []] == [str(x).strip().upper() for x in b or []]
    da, db = D(a), D(b)
    if da is not None and db is not None and not any(c.isalpha() for c in str(a) + str(b)):
        return da == db
    return (str(a).strip().upper() if a is not None else None) == (str(b).strip().upper() if b is not None else None)


def compare(ext: dict, truth: dict) -> list[str]:
    diffs = [f"{f}: read {ext.get(f)!r}, printed {truth.get(f)!r}" for f in HEADER if not same(ext.get(f), truth.get(f))]
    el, tl = ext.get("line_items") or [], truth["line_items"]
    if len(el) != len(tl):
        diffs.append(f"line count: read {len(el)}, printed {len(tl)}")
    for i, (e, t) in enumerate(zip(el, tl)):
        for f in ("sku", "quantity", "unit_price", "amount"):
            if not same(e.get(f), t.get(f)):
                diffs.append(f"line {i + 1} {f}: read {e.get(f)!r}, printed {t.get(f)!r}")
    return diffs


def main(args: list[str]) -> int:
    fixture = "--fixture" in args
    targets = [a for a in args if a != "--fixture"] or ["e1-a", "e1-b", "e3-a", "e3-b"]
    if fixture:
        extractor = lambda b: (json.loads(json.dumps(TRUTH[hashlib.sha256(b).hexdigest()])), {"model": "fixture"})
    else:
        from app.pipeline.extract import ClaudeExtractor
        extractor = ClaudeExtractor()

    problems = 0
    for t in targets:
        path = SAMPLES / MANIFEST[t]["file"] if t in MANIFEST else Path(t)
        pdf = path.read_bytes()
        info = inspect_pdf(pdf)
        t0 = time.perf_counter()
        try:
            ext, meta = extractor(pdf)
        except Exception as e:
            print(f"\n✗ {t}: extraction failed — {type(e).__name__}: {e}")
            problems += 1
            continue
        secs = time.perf_counter() - t0
        kind = "native" if info["has_text_layer"] else "scan"
        print(f"\n=== {t} ({kind}) · {secs:.1f}s · {meta.get('model')} · req {meta.get('request_id', '-')}")

        truth = TRUTH.get(info["sha256"])
        if truth:
            diffs = compare(ext, truth)
            print("  fields : " + ("all match what is printed" if not diffs else f"{len(diffs)} MISMATCH"))
            for d in diffs:
                print(f"           - {d}")
            problems += len(diffs)
        else:
            print("  fields : (independent PDF — no ground truth; check against the document)")
            print("  " + json.dumps({k: ext.get(k) for k in HEADER}, indent=None))
            for i, l in enumerate(ext.get("line_items") or []):
                print(f"           line {i + 1}: {l}")

        have = {normalise_field(e.get("field")) for e in ext.get("evidence") or [] if (e.get("snippet") or "").strip()}
        missing = [f for f in required_evidence(ext) if f not in have]
        print(f"  evidence: {len(required_evidence(ext)) - len(missing)}/{len(required_evidence(ext))} critical fields"
              + (f" · missing {missing}" if missing else ""))
        if ext.get("unreadable_fields"):
            print(f"  unreadable (model-reported): {ext['unreadable_fields']}")
        rules, _ = run_checks(ext, info["text"], info["has_text_layer"])
        failing = [r for r in rules if r["ok"] is False]
        print("  checks : " + ("pass" if not failing else "; ".join(f"{r['rule']}: {r['message']}" for r in failing)))
        problems += len(failing) if truth else 0

    print(f"\n{'OK' if not problems else f'{problems} issue(s) to look at'} — {len(targets)} document(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
