"""Paid Claude usage on a public link is bounded without user accounts by MODEL_CALLS_PER_DAY:
a server-wide cap on live model calls across every sandbox (cache hits are free).
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import budget, config, main
from conftest import get_run, open_balance, submit

WS = {"X-Workspace": "c" * 32}


@pytest.fixture
def client(runner):
    main.app.state.runner = runner
    with TestClient(main.app) as c:
        yield c
    main.app.state.runner = None


def _wait(client, run_id, headers):
    for _ in range(200):
        snap = client.get(f"/api/runs/{run_id}", headers=headers).json()
        if snap["run"]["status"] in ("done", "error"):
            return snap
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_runs_start_without_any_passcode(client):
    assert "passcode_required" not in client.get("/api/health", headers=WS).json()
    r = client.post("/api/runs/sample/e1-a", headers=WS)
    assert r.status_code == 201
    assert _wait(client, r.json()["run_id"], WS)["run"]["decision"] == "APPROVE"


def test_daily_cap_stops_live_extraction_without_touching_the_ledger(runner, monkeypatch):
    monkeypatch.setattr(config, "MODEL_CALLS_PER_DAY", 1)
    runner.extractor = budget.Budgeted(runner.extractor, "extract")
    a = submit(runner, "e1-a")
    assert a["decision"] == "APPROVE"
    b = submit(runner, "e1-b")
    assert b["status"] == "error" and "budget" in b["error"].lower() and b["decision"] is None
    assert open_balance("PO-1042") == 28000
    assert budget.usage() == {"used": 1, "limit": 1}


def test_cache_hits_are_free_and_explanations_fall_back_when_capped(runner, monkeypatch):
    monkeypatch.setattr(config, "MODEL_CALLS_PER_DAY", 1)
    runner.extractor = budget.Budgeted(runner.extractor, "extract")
    runner.explainer = budget.Budgeted(lambda ctx: "from the model", "explain")
    a = submit(runner, "e1-a")                  # extraction takes the only call; the summary is capped
    assert a["decision"] == "APPROVE" and a["explanation_source"] == "template"
    again = submit(runner, "e1-a")              # same file: extraction from cache, no model call needed
    assert again["status"] == "done" and again["extraction_cached"] == 1
    assert again["decision"] == "REJECT"        # byte-identical resubmission of an approved invoice
    assert budget.usage()["used"] == 1


def test_window_is_rolling(runner, monkeypatch):
    monkeypatch.setattr(config, "MODEL_CALLS_PER_DAY", 1)
    budget.take("extract")
    with pytest.raises(budget.BudgetExceeded):
        budget.take("extract")
    real = time.time
    monkeypatch.setattr(budget.time, "time", lambda: real() + 86_401)
    budget.take("extract")                      # a day later the old call has aged out
