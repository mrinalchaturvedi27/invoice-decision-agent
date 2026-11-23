"""Orchestrates one run: every stage writes a run_steps row the UI streams live.

A *run* is one processing attempt; an *invoice* is one document (keyed by sha256). Re-executing a
run (a retry) reuses the same run and invoice, so it can neither flag itself as a duplicate nor
allocate twice.

The verdict is recorded at the decide stage: for an APPROVE in the same transaction as the ledger
posting, for HOLD/REJECT in one write. From then on it is final. A retry of a decided run resumes at
the explanation instead of re-deciding against a ledger that already contains its own posting.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from app import db, ledger
from app.money import D, fmt, s
from app.pipeline.checks import run_checks
from app.pipeline.consumption import check_consumption
from app.pipeline.duplicates import check_duplicates, normalise_number
from app.pipeline.explain import template_explanation
from app.pipeline.ingest import inspect_pdf
from app.pipeline.po_resolve import resolve_po
from app.pipeline.rules import hold, reject, skipped
from app.pipeline.vendor import check_vendor
from app.policy import POLICY_VERSION

log = logging.getLogger("runner")
STAGES = ["ingest", "extract", "vendor", "duplicates", "checks", "po", "consumption", "decide", "explain"]
MAX_LEDGER_RETRIES = 3

Extractor = Callable[[bytes], tuple[dict, dict]]
Explainer = Callable[[dict], str]


class _Step:
    def __init__(self):
        self.status, self.summary, self.detail = "pass", None, None

    def done(self, summary: str, detail=None, status: str = "pass"):
        self.status, self.summary, self.detail = status, summary, detail

    def from_rules(self, rules: list[dict], detail: dict | None = None, pass_summary: str | None = None):
        failing = [r for r in rules if r["ok"] is False]
        if failing:
            more = f" (+{len(failing) - 1} more)" if len(failing) > 1 else ""
            self.done(failing[0]["message"] + more, {"rules": rules, **(detail or {})}, "fail")
        else:
            self.done(pass_summary or (rules[0]["message"] if rules else "OK"), {"rules": rules, **(detail or {})})


class _Recorder:
    def __init__(self, conn, run_id: int, pacing_ms: int, seq: int = 0):
        self.conn, self.run_id, self.pacing, self.seq = conn, run_id, pacing_ms / 1000, seq

    @contextmanager
    def step(self, stage: str, pace: bool = True):
        self.seq += 1
        t0 = time.perf_counter()
        sid = self.conn.execute(
            "INSERT INTO run_steps(run_id, seq, stage, status, started_at) VALUES (?,?,?,?,?)",
            (self.run_id, self.seq, stage, "running", db.now())).lastrowid
        st = _Step()
        try:
            yield st
        except Exception as e:
            st.status, st.summary = "error", f"{type(e).__name__}: {e}"
            raise
        finally:
            self.conn.execute(
                "UPDATE run_steps SET status=?, summary=?, detail=?, finished_at=?, duration_ms=? WHERE id=?",
                (st.status, st.summary, db.dumps(st.detail) if st.detail is not None else None, db.now(),
                 int((time.perf_counter() - t0) * 1000), sid))
            if pace and self.pacing and st.status != "error":
                time.sleep(self.pacing)


def decide(trace: list[dict]) -> tuple[str, str | None, str]:
    """First failing rule decides; a REJECT outranks any HOLD."""
    failing = [r for r in trace if r["ok"] is False]
    first = next((r for r in failing if r["outcome"] == "REJECT"), failing[0] if failing else None)
    if first is None:
        return "APPROVE", None, "All checks passed"
    return first["outcome"], first["rule"], first["message"]


class Runner:
    def __init__(self, extractor: Extractor, explainer: Explainer | None = None, pacing_ms: int = 0):
        self.extractor, self.explainer, self.pacing_ms = extractor, explainer, pacing_ms

    # ---- submission -------------------------------------------------------------------------
    def create_run(self, pdf_bytes: bytes, filename: str) -> int:
        info = inspect_pdf(pdf_bytes)
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT id FROM invoices WHERE sha256 = ?", (info["sha256"],)).fetchone()
            if row:
                invoice_id = row["id"]
            else:
                path = db.upload_dir() / f"{info['sha256']}.pdf"
                path.write_bytes(pdf_bytes)
                invoice_id = conn.execute(
                    "INSERT INTO invoices(sha256, filename, path, pages, has_text_layer, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (info["sha256"], filename, str(path), info["pages"], int(info["has_text_layer"]), db.now())
                ).lastrowid
            run_id = conn.execute(
                "INSERT INTO runs(invoice_id, status, policy_version, started_at) VALUES (?,?,?,?)",
                (invoice_id, "queued", POLICY_VERSION, db.now())).lastrowid
            conn.execute("COMMIT")
            return run_id
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def execute(self, run_id: int) -> None:
        conn = db.connect()
        try:
            self._execute(conn, run_id)
        except Exception as e:  # recorded on the run; the UI shows it and offers a retry
            log.exception("run %s failed", run_id)
            conn.execute("UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?",
                         (f"{type(e).__name__}: {e}", db.now(), run_id))
        finally:
            conn.close()

    # ---- pipeline ---------------------------------------------------------------------------
    def _execute(self, conn, run_id: int) -> None:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        invoice_id = run["invoice_id"]
        if run["decided_at"]:  # verdict already recorded (and posted, if APPROVE): only the summary is left
            conn.execute("DELETE FROM run_steps WHERE run_id = ? AND stage = 'explain'", (run_id,))
            conn.execute("UPDATE runs SET status='running', attempts=attempts+1, error=NULL, finished_at=NULL "
                         "WHERE id=?", (run_id,))
            seq = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM run_steps WHERE run_id = ?", (run_id,)).fetchone()[0]
            self._explain_and_finish(conn, run_id, _Recorder(conn, run_id, self.pacing_ms, seq), resumed=True)
            return
        conn.execute("DELETE FROM run_steps WHERE run_id = ?", (run_id,))
        conn.execute("UPDATE runs SET status='running', attempts=attempts+1, error=NULL, decision=NULL, "
                     "deciding_rule=NULL, deciding_message=NULL, finished_at=NULL WHERE id=?", (run_id,))
        rec = _Recorder(conn, run_id, self.pacing_ms)
        invoice = dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())
        pdf = Path(invoice["path"]).read_bytes()

        with rec.step("ingest") as st:
            info = inspect_pdf(pdf)
            st.done(f"{info['pages']} page(s) · " + ("native PDF with a text layer" if info["has_text_layer"]
                                                     else "scanned image, no text layer"),
                    {"filename": invoice["filename"], "sha256": info["sha256"], "pages": info["pages"],
                     "has_text_layer": info["has_text_layer"], "text_layer_chars": len(info["text"].strip())})

        with rec.step("extract", pace=False) as st:
            cached = conn.execute("SELECT extraction, meta FROM extraction_cache WHERE sha256 = ?",
                                  (invoice["sha256"],)).fetchone()
            if cached:
                ext, meta = json.loads(cached["extraction"]), json.loads(cached["meta"] or "{}")
            else:
                ext, meta = self.extractor(pdf)
                conn.execute("INSERT OR REPLACE INTO extraction_cache VALUES (?,?,?,?)",
                             (invoice["sha256"], db.dumps(ext), db.dumps(meta), db.now()))
            st.done(f"{ext.get('vendor_name') or 'Unknown vendor'} · {ext.get('invoice_number') or 'no number'} · "
                    f"{len(ext.get('line_items') or [])} line(s) · total {ext.get('total') or '—'}"
                    + (" · from cache" if cached else ""),
                    {"cached": bool(cached), "meta": meta, "extraction": ext})
        conn.execute("UPDATE runs SET extraction_cached=? WHERE id=?", (int(bool(cached)), run_id))
        conn.execute("UPDATE invoices SET invoice_number=?, norm_number=?, invoice_date=?, subtotal=?, total=? "
                     "WHERE id=?", (ext.get("invoice_number"), normalise_number(ext.get("invoice_number")),
                                    ext.get("invoice_date"), ext.get("subtotal"), ext.get("total"), invoice_id))

        with rec.step("vendor") as st:
            vendor, vrules, vdet = check_vendor(conn, ext)
            st.from_rules(vrules, vdet)
        conn.execute("UPDATE invoices SET vendor_id=? WHERE id=?", (vendor["id"] if vendor else None, invoice_id))

        with rec.step("duplicates") as st:
            invoice = dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())
            drules, linked_invoice_id, ddet = check_duplicates(conn, run_id, invoice, ext, vendor)
            st.from_rules(drules, ddet)

        with rec.step("checks") as st:
            crules, cdet = run_checks(ext, info["text"], info["has_text_layer"])
            st.from_rules(crules, cdet, pass_summary=next(
                (r["message"] for r in crules if r["rule"] in ("TEXT_LAYER_MATCH", "SCAN_EVIDENCE")), None))

        base_trace = vrules + drules + crules
        for attempt in range(1, MAX_LEDGER_RETRIES + 1):
            with rec.step("po") as st:
                resolution, prules, pdet = resolve_po(conn, ext, vendor)
                st.from_rules(prules, pdet)
            with rec.step("consumption") as st:
                if resolution:
                    krules, cons = check_consumption(ext, vendor, resolution)
                    st.from_rules(krules, cons["detail"])
                else:
                    krules, cons = [skipped("CONSUMPTION", "consumption", "No PO resolved — nothing to compare")], None
                    st.done("Skipped — no PO resolved", {"rules": krules}, "skipped")
            trace = base_trace + prules + krules
            decision, rule, message = decide(trace)
            po_id = resolution["po_id"] if resolution else None
            before = cons["balance_before"] if cons else None
            after = before

            fields = {"decision": decision, "deciding_rule": rule, "deciding_message": message, "po_id": po_id,
                      "po_method": resolution["method"] if resolution else None,
                      "linked_invoice_id": linked_invoice_id, "trace": trace}

            with rec.step("decide") as st:
                if decision == "APPROVE":
                    result = ledger.commit_approval(conn, run_id=run_id, invoice_id=invoice_id, po_id=po_id,
                                                    allocations=cons["allocations"], snapshot=cons["snapshot"],
                                                    decision=fields)
                    if result["status"] == "stale":
                        st.done(f"Ledger changed while deciding (open balance now "
                                f"{fmt(result['open_balance'])}) — re-evaluating against fresh state",
                                {"ledger": result, "attempt": attempt}, "info")
                        continue
                    if result["status"] in ("duplicate", "suspected_duplicate"):
                        # Another run approved this document, or one it duplicates, after our duplicate stage ran.
                        # The posting transaction refused; record the verdict the duplicate stage would now give.
                        if result["status"] == "duplicate":
                            r = reject("DUPLICATE_OF_APPROVED", "decide",
                                       f"This exact file was approved by run #{result['approved_run_id']} while "
                                       f"this run was deciding", original_run_id=result["approved_run_id"])
                            linked = invoice_id
                        else:
                            o = result["original"]
                            r = hold("SUSPECTED_DUPLICATE", "decide",
                                     "Possible duplicate: " + "; ".join(result["reasons"]) +
                                     f" (approved by run #{o['approved_run_id']} while this run was deciding)",
                                     original_invoice_id=o["id"], original_run_id=o["approved_run_id"],
                                     original_number=o["invoice_number"])
                            linked = o["id"]
                            before = result["open_balance"]
                        after = before
                        trace = trace + [r]
                        fields.update(decision=r["outcome"], deciding_rule=r["rule"], deciding_message=r["message"],
                                      linked_invoice_id=linked, trace=trace, balance_before=before,
                                      balance_after=after)
                        ledger.record_decision(conn, run_id, fields)
                        st.done(f"{r['outcome']} — {r['rule']}: {r['message']}",
                                {"decision": r["outcome"], "deciding_rule": r["rule"], "ledger": result}, "fail")
                    else:
                        before, after = result["balance_before"], result["balance_after"]
                        st.done(f"APPROVE — {fmt(cons['subtotal'])} allocated to {po_id}: "
                                f"{fmt(before)} → {fmt(after)}"
                                + (" (already applied by this run)" if result["status"] == "already_applied" else ""),
                                {"decision": decision, "ledger": result, "allocations": cons["allocations"],
                                 "attempt": attempt})
                else:
                    ledger.record_decision(conn, run_id, {**fields, "balance_before": before, "balance_after": after})
                    st.done(f"{decision} — {rule}: {message}",
                            {"decision": decision, "deciding_rule": rule,
                             "failing_rules": [r["rule"] for r in trace if r["ok"] is False],
                             "ledger": "unchanged"}, "fail")
            break
        else:
            raise RuntimeError("Ledger kept changing during decision; run left undecided")

        self._explain_and_finish(conn, run_id, rec)

    # ---- after the verdict ------------------------------------------------------------------
    def _explain_and_finish(self, conn, run_id: int, rec: _Recorder, resumed: bool = False) -> None:
        ctx = explain_context(conn, run_id)
        note = " (resumed from the recorded decision)" if resumed else ""
        with rec.step("explain", pace=False) as st:
            if self.explainer is None:
                explanation, source = template_explanation(ctx), "template"
                st.done("Built from the rule trace (model explanation disabled)" + note, {"source": source})
            else:
                try:
                    explanation, source = self.explainer(ctx), "claude"
                    st.done("Written by Claude from the rule trace" + note, {"source": source})
                except Exception as e:
                    explanation, source = template_explanation(ctx), "template"
                    st.done(f"Model unavailable ({type(e).__name__}) — used a sentence built from the rule trace"
                            + note, {"source": source, "error": str(e)}, "info")
        conn.execute("UPDATE runs SET status='done', explanation=?, explanation_source=?, finished_at=? WHERE id=?",
                     (explanation, source, db.now(), run_id))


def explain_context(conn, run_id: int) -> dict:
    """Everything the summary needs, read back from the recorded decision (so a resumed run says the same)."""
    run = dict(conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())
    inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (run["invoice_id"],)).fetchone()
    vendor = conn.execute("SELECT name FROM vendors WHERE id = ?", (inv["vendor_id"],)).fetchone() \
        if inv["vendor_id"] else None
    trace = json.loads(run["trace"] or "[]")
    return {"decision": run["decision"], "deciding_rule": run["deciding_rule"],
            "deciding_message": (run["deciding_message"] or "").rstrip("."), "po_id": run["po_id"],
            "balance_before": D(run["balance_before"]), "balance_after": D(run["balance_after"]),
            "subtotal": D(inv["subtotal"]) if run["po_id"] else None, "vendor": vendor["name"] if vendor else None,
            "invoice_number": inv["invoice_number"], "policy_version": run["policy_version"],
            "other_failing_rules": [r["message"] for r in trace if r["ok"] is False
                                    and r["rule"] != run["deciding_rule"]]}
