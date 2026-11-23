"""The decision, its balance snapshot, and the ledger posting are one atomic fact.

1. Two different documents that are business duplicates of each other can't both be approved, even
   when both pass the duplicate stage before either posts: the posting transaction re-checks.
2. Once a decision is recorded, a retry resumes from it (finishing the explanation) instead of
   re-deciding against a ledger that already contains its own allocation.
"""
import threading
from decimal import Decimal

import pytest

from app import db, ledger
from app.pipeline import runner as runner_mod
from conftest import MANIFEST, allocations_total, get_run, open_balance, pdf, submit


def _race_to_ledger(monkeypatch, parties: int):
    """Hold every run at the ledger door until all of them have passed the duplicate stage."""
    barrier, real = threading.Barrier(parties, timeout=10), ledger.commit_approval
    seen: set[int] = set()

    def gated(conn, **kw):
        if kw["run_id"] not in seen:           # only the first attempt waits; re-decisions go straight in
            seen.add(kw["run_id"])
            barrier.wait()
        return real(conn, **kw)

    monkeypatch.setattr(ledger, "commit_approval", gated)


def test_concurrent_disguised_duplicate_cannot_also_be_approved(runner, monkeypatch):
    _race_to_ledger(monkeypatch, 2)
    ids = [runner.create_run(pdf(s), MANIFEST[s]["file"]) for s in ("e2-original", "e2-disguised")]
    threads = [threading.Thread(target=runner.execute, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    runs = [get_run(i) for i in ids]

    assert sorted(r["decision"] for r in runs) == ["APPROVE", "HOLD"], [r["deciding_message"] for r in runs]
    winner = next(r for r in runs if r["decision"] == "APPROVE")
    held = next(r for r in runs if r["decision"] == "HOLD")
    assert held["deciding_rule"] == "SUSPECTED_DUPLICATE"
    assert held["linked_invoice_id"] == winner["invoice_id"]
    assert held["balance_before"] == held["balance_after"] == "6000.00"
    assert open_balance("PO-2050") == Decimal("6000")
    assert allocations_total("PO-2050") == Decimal("6000")


def test_retry_after_failure_past_the_ledger_keeps_the_recorded_approval(runner, monkeypatch):
    submit(runner, "e1-a")
    submit(runner, "e1-b")                        # held; PO-1042 still ₹28,000

    real, calls = runner_mod.template_explanation, {"n": 0}

    def crash_once(ctx):                          # the process dies after the ledger write, before finishing
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated crash after posting")
        return real(ctx)

    monkeypatch.setattr(runner_mod, "template_explanation", crash_once)
    c = submit(runner, "e1-c")
    assert c["status"] == "error"
    assert c["decision"] == "APPROVE"             # the verdict was recorded with the posting
    assert (c["balance_before"], c["balance_after"]) == ("28000.00", "0.00")
    assert open_balance("PO-1042") == Decimal("0")

    runner.execute(c["id"])                       # retry
    again = get_run(c["id"])
    assert again["status"] == "done" and again["attempts"] == 2
    assert again["decision"] == "APPROVE" and again["deciding_rule"] is None
    assert (again["balance_before"], again["balance_after"]) == ("28000.00", "0.00")
    assert again["explanation"]
    assert allocations_total("PO-1042") == Decimal("48000")
    conn = db.connect()
    try:
        stages = [r["stage"] for r in conn.execute("SELECT stage FROM run_steps WHERE run_id=? ORDER BY seq", (c["id"],))]
    finally:
        conn.close()
    assert stages.count("decide") == 1 and stages[-1] == "explain"   # resumed, not re-decided


def test_verdict_is_visible_while_the_summary_is_written(runner):
    seen = {}

    def explainer(ctx):
        seen.update(get_run(run_id))
        return "summary"

    runner.explainer = explainer
    run_id = runner.create_run(pdf("e1-a"), "e1-a.pdf")
    runner.execute(run_id)
    assert seen["status"] == "running" and seen["decision"] == "APPROVE"
    assert seen["balance_after"] == "28000.00" and seen["explanation"] is None
    assert get_run(run_id)["explanation"] == "summary"


@pytest.mark.parametrize("sample", ["e1-b", "e2-disguised"])
def test_hold_decisions_are_also_recorded_before_the_summary(runner, sample):
    if sample == "e2-disguised":
        submit(runner, "e2-original")
    else:
        submit(runner, "e1-a")
    seen = {}
    runner.explainer = lambda ctx: (seen.update(get_run(run_id)), "summary")[1]
    run_id = runner.create_run(pdf(sample), MANIFEST[sample]["file"])
    runner.execute(run_id)
    assert seen["decision"] == "HOLD" and seen["explanation"] is None
