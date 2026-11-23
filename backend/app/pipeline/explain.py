"""Stage: plain-English summary for the AP team. The decision is already made; this only explains it.
If the model call fails, a sentence built from the stored rule trace is used instead."""
from __future__ import annotations

import os

import anthropic

from app.config import EXPLAIN_MODEL
from app.db import dumps
from app.money import fmt


def template_explanation(ctx: dict) -> str:
    d, po = ctx["decision"], ctx.get("po_id")
    if d == "APPROVE":
        return (f"Approved: {fmt(ctx['subtotal'])} pre-tax allocated to {po}. "
                f"Open balance {fmt(ctx['balance_before'])} → {fmt(ctx['balance_after'])}.")
    tail = " Ledger unchanged" + (f"; {po} still has {fmt(ctx['balance_before'])} open." if po and
                                  ctx.get("balance_before") is not None else ".")
    return f"{'Held for review' if d == 'HOLD' else 'Rejected'}: {ctx['deciding_message'].rstrip('.')}.{tail}"


SYSTEM = """You write short decision notes for an accounts-payable manager.
You are given an invoice decision that has ALREADY been made by deterministic rules, plus the rule trace.
Write 2-3 plain sentences: what was decided, the specific reason with the exact figures, and the effect on
the PO balance. If the decision is HOLD or REJECT, end with one line starting "Next step:" saying what a
person should do. Use only facts in the input. Do not soften, second-guess, or change the decision.
No markdown, no bullet points."""


class ClaudeExplainer:
    def __call__(self, ctx: dict) -> str:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise RuntimeError("no Anthropic credentials configured")
        client = anthropic.Anthropic(max_retries=1, timeout=60)
        response = client.beta.messages.create(
            model=EXPLAIN_MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[{"role": "user", "content": dumps(ctx)}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("explanation refused")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise RuntimeError("empty explanation")
        return text
