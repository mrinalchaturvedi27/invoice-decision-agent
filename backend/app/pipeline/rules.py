"""A rule result is the unit of the decision trace."""
from __future__ import annotations


def ok(rule: str, stage: str, message: str, **data) -> dict:
    return {"rule": rule, "stage": stage, "ok": True, "message": message, "data": data or None}


def hold(rule: str, stage: str, message: str, **data) -> dict:
    return {"rule": rule, "stage": stage, "ok": False, "outcome": "HOLD", "message": message, "data": data or None}


def reject(rule: str, stage: str, message: str, **data) -> dict:
    return {"rule": rule, "stage": stage, "ok": False, "outcome": "REJECT", "message": message, "data": data or None}


def skipped(rule: str, stage: str, message: str) -> dict:
    return {"rule": rule, "stage": stage, "ok": None, "message": message, "data": None}
