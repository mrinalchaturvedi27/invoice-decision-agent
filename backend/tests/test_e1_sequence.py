"""E1 — split billing. Ordered sequence against an isolated seed; balance asserted after every invoice."""
from decimal import Decimal
from hashlib import sha256

import pytest

from app import db, queries
from conftest import open_balance, pdf, submit


def test_milestone_partial_bill_then_overclaim(runner):
    """The first acceptance test: approve ₹20,000 of ₹48,000, then hold a ₹30,000 claim; ₹28,000 survives."""
    assert open_balance("PO-1042") == Decimal("48000.00")

    a = submit(runner, "e1-a")
    assert (a["decision"], a["deciding_rule"]) == ("APPROVE", None)
    assert "₹20,000.00 pre-tax allocated" in a["explanation"]
    assert (Decimal(a["balance_before"]), Decimal(a["balance_after"])) == (Decimal("48000"), Decimal("28000"))
    assert open_balance("PO-1042") == Decimal("28000")

    b = submit(runner, "e1-b")
    assert (b["decision"], b["deciding_rule"]) == ("HOLD", "EXCEEDS_OPEN_BALANCE")
    assert (Decimal(b["balance_before"]), Decimal(b["balance_after"])) == (Decimal("28000"), Decimal("28000"))
    assert open_balance("PO-1042") == Decimal("28000")


def test_full_split_billing_sequence(runner):
    expected = [("e1-a", "APPROVE", None, "28000"),
                ("e1-b", "HOLD", "EXCEEDS_OPEN_BALANCE", "28000"),
                ("e1-c", "APPROVE", None, "0"),
                ("e1-d", "HOLD", "PO_EXHAUSTED", "0")]
    for sample, decision, rule, balance in expected:
        r = submit(runner, sample)
        assert (r["decision"], r["deciding_rule"]) == (decision, rule), (sample, r["deciding_message"])
        assert open_balance("PO-1042") == Decimal(balance), sample


def test_overclaim_records_every_failing_rule(runner):
    submit(runner, "e1-a")
    b = submit(runner, "e1-b")
    failing = [t["rule"] for t in b["trace"] if t["ok"] is False]
    # 600 units also exceeds the 560 still open; recorded, but the balance ceiling decides.
    assert failing == ["EXCEEDS_OPEN_BALANCE", "QTY_EXCEEDS_OPEN"]
    assert "Claims ₹30,000.00 pre-tax but only ₹28,000.00 is open" in b["deciding_message"]


def test_partial_bill_far_below_balance_is_not_flagged(runner):
    """A legitimate partial bill is ₹28,000 away from the open balance; that must not count as a variance."""
    a = submit(runner, "e1-a")
    assert a["decision"] == "APPROVE"
    assert not [t for t in a["trace"] if t["ok"] is False]


@pytest.mark.parametrize("sample, po_id, balance", [
    ("e1-a", "PO-1042", "48000.00"),
    ("e3-a", "PO-3101", "3070.00"),
])
def test_foreign_currency_invoice_cannot_post_to_inr_ledger(runner, sample, po_id, balance):
    document = pdf(sample)
    extraction, _ = runner.extractor(document)
    runner.extractor.overrides[sha256(document).hexdigest()] = {**extraction, "currency": "USD"}

    run = submit(runner, sample)

    assert (run["decision"], run["deciding_rule"]) == ("HOLD", "CURRENCY_MISMATCH")
    assert open_balance(po_id) == Decimal(balance)
    assert "USD" in run["deciding_message"] and "INR" in run["deciding_message"]
    conn = db.connect()
    try:
        assert queries.list_runs(conn)[0]["currency"] == "USD"
    finally:
        conn.close()
