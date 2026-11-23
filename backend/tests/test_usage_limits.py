"""Paid Claude usage on a shared link is bounded two ways, without user accounts:
- REVIEWER_PASSCODE: starting a run (anything that can call the model) needs the passcode;
- MODEL_CALLS_PER_DAY: a server-wide cap on live model calls across every sandbox (cache hits are free).
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


def test_passcode_guards_everything_that_can_call_the_model(client, monkeypatch):
    monkeypatch.setattr(config, "REVIEWER_PASSCODE", "zamp-review")
    assert client.get("/api/health", headers=WS).json()["passcode_required"] is True
    assert client.post("/api/runs/sample/e1-a", headers=WS).status_code == 401
    assert client.post("/api/runs/sample/e1-a", headers={**WS, "X-Reviewer-Passcode": "nope"}).status_code == 401
    assert client.post("/api/runs", headers=WS,
                       files={"file": ("x.pdf", b"%PDF-1.4 x", "application/pdf")}).status_code == 401
    assert client.post("/api/runs/1/retry", headers=WS).status_code == 401
    ok = {**WS, "X-Reviewer-Passcode": "zamp-review"}
    r = client.post("/api/runs/sample/e1-a", headers=ok)
    assert r.status_code == 201
    assert _wait(client, r.json()["run_id"], WS)["run"]["decision"] == "APPROVE"   # reading needs no passcode
    assert client.get("/api/runs", headers=WS).status_code == 200


def test_no_passcode_configured_means_open(client):
    assert client.get("/api/health", headers=WS).json()["passcode_required"] is False
    assert client.post("/api/runs/sample/e1-a", headers=WS).status_code == 201


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
