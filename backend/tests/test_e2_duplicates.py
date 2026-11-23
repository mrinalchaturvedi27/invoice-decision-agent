"""E2 — disguised duplicate and byte-identical resubmission. Neither touches the ledger."""
from decimal import Decimal

from conftest import allocations_total, open_balance, submit


def test_disguised_duplicate_held_and_linked(runner):
    orig = submit(runner, "e2-original")
    assert orig["decision"] == "APPROVE"
    assert open_balance("PO-2050") == Decimal("6000")

    dup = submit(runner, "e2-disguised")
    assert (dup["decision"], dup["deciding_rule"]) == ("HOLD", "SUSPECTED_DUPLICATE")
    assert dup["linked_invoice_id"] == orig["invoice_id"]
    assert "'2231-R' normalises to the same '2231'" in dup["deciding_message"]
    assert open_balance("PO-2050") == Decimal("6000")


def test_byte_identical_resubmission_rejected(runner):
    orig = submit(runner, "e2-original")
    again = submit(runner, "e2-resubmit")
    assert again["invoice_id"] == orig["invoice_id"]          # same document, new run
    assert (again["decision"], again["deciding_rule"]) == ("REJECT", "DUPLICATE_OF_APPROVED")
    assert allocations_total("PO-2050") == Decimal("6000")    # paid once


def test_duplicate_of_a_held_invoice_is_not_blocked(runner):
    """Only approved invoices create payment risk; a resubmission of a held one is re-evaluated."""
    submit(runner, "e1-a")
    held = submit(runner, "e1-b")
    assert held["decision"] == "HOLD"
    again = submit(runner, "e1-b")
    assert again["deciding_rule"] == "EXCEEDS_OPEN_BALANCE"   # same reason, not a duplicate flag
