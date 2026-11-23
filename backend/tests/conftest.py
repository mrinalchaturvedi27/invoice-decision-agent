import json
from decimal import Decimal
from pathlib import Path

import pytest

from app import config, db, ledger
from app.pipeline.runner import Runner

SAMPLES = config.SAMPLES_DIR
MANIFEST = {m["id"]: m for m in json.loads((SAMPLES / "manifest.json").read_text())}
TRUTH = json.loads((SAMPLES / "ground_truth.json").read_text())


class FixtureExtractor:
    """Stands in for Claude in tests: returns what the generated PDF actually prints.
    `overrides` lets a test simulate a model misread for a given sha256."""

    def __init__(self):
        self.calls = 0
        self.overrides: dict[str, dict] = {}

    def __call__(self, pdf_bytes: bytes):
        import hashlib
        self.calls += 1
        sha = hashlib.sha256(pdf_bytes).hexdigest()
        ext = self.overrides.get(sha) or TRUTH[sha]
        return json.loads(json.dumps(ext)), {"model": "fixture"}


@pytest.fixture
def runner(tmp_path):
    db.configure(tmp_path / "app.db", tmp_path)
    db.init()
    db.seed_if_empty()
    return Runner(extractor=FixtureExtractor(), explainer=None, pacing_ms=0)


def pdf(sample_id: str) -> bytes:
    return (SAMPLES / MANIFEST[sample_id]["file"]).read_bytes()


def submit(runner: Runner, sample_id: str) -> dict:
    run_id = runner.create_run(pdf(sample_id), MANIFEST[sample_id]["file"])
    runner.execute(run_id)
    return get_run(run_id)


def get_run(run_id: int) -> dict:
    conn = db.connect()
    try:
        r = dict(conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())
        r["trace"] = json.loads(r["trace"]) if r["trace"] else []
        return r
    finally:
        conn.close()


def open_balance(po_id: str) -> Decimal:
    conn = db.connect()
    try:
        return ledger.open_state(conn, po_id)["open_balance"]
    finally:
        conn.close()


def allocations_total(po_id: str) -> Decimal:
    conn = db.connect()
    try:
        return sum((Decimal(r["amount"]) for r in conn.execute(
            "SELECT amount FROM allocations WHERE po_id = ?", (po_id,))), Decimal(0))
    finally:
        conn.close()
