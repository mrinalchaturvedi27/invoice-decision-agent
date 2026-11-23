"""HTTP surface: upload → live stream → run detail → history → reset."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from conftest import pdf


@pytest.fixture
def client(runner):
    main.app.state.runner = runner
    with TestClient(main.app) as c:
        yield c
    main.app.state.runner = None


def _wait(client, run_id, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap = client.get(f"/api/runs/{run_id}").json()
        if snap["run"]["status"] in ("done", "error"):
            return snap
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_upload_stream_detail_history(client):
    r = client.post("/api/runs", files={"file": ("my-invoice.pdf", pdf("e1-a"), "application/pdf")})
    assert r.status_code == 201
    run_id = r.json()["run_id"]

    events = []
    with client.stream("GET", f"/api/runs/{run_id}/stream") as s:
        for line in s.iter_lines():
            if line.startswith("data: ") and line != "data: {}":
                events.append(json.loads(line[6:]))
    final = events[-1]
    assert final["run"]["decision"] == "APPROVE"
    assert [st["stage"] for st in final["steps"]] == main.STAGES
    assert final["po"]["id"] == "PO-1042" and final["po"]["open_now"] == "28000.00"
    assert final["run"]["balance_before"] == "48000.00" and final["run"]["balance_after"] == "28000.00"

    r2 = client.post("/api/runs/sample/e1-b").json()["run_id"]
    snap = _wait(client, r2)
    assert snap["run"]["deciding_rule"] == "EXCEEDS_OPEN_BALANCE"
    assert snap["run"]["balance_after"] == "28000.00"

    hist = client.get("/api/runs").json()
    assert [h["decision"] for h in hist["runs"]] == ["HOLD", "APPROVE"]
    assert hist["stats"]["APPROVE"] == 1 and hist["stats"]["HOLD"] == 1

    assert client.get(f"/api/invoices/{final['invoice']['id']}/pdf").content.startswith(b"%PDF")


def test_rejects_non_pdf(client):
    r = client.post("/api/runs", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_reset_restores_ledger(client):
    run_id = client.post("/api/runs/sample/e1-a").json()["run_id"]
    _wait(client, run_id)
    assert client.post("/api/admin/reset", json={"clear_cache": False}).json()["ok"]
    assert client.get("/api/runs").json()["runs"] == []
    run_id = client.post("/api/runs/sample/e1-a").json()["run_id"]
    snap = _wait(client, run_id)
    assert snap["run"]["balance_before"] == "48000.00"
    assert next(s for s in snap["steps"] if s["stage"] == "extract")["detail"]["cached"] is True


def test_extraction_failure_marks_run_error_and_retry_works(client, runner):
    def boom(_):
        raise RuntimeError("ANTHROPIC_API_KEY is not set on the server")
    real = runner.extractor
    runner.extractor = boom
    run_id = client.post("/api/runs/sample/e1-a").json()["run_id"]
    snap = _wait(client, run_id)
    assert snap["run"]["status"] == "error" and "ANTHROPIC_API_KEY" in snap["run"]["error"]
    assert next(s for s in snap["steps"] if s["stage"] == "extract")["status"] == "error"
    runner.extractor = real
    assert client.post(f"/api/runs/{run_id}/retry").status_code == 202
    assert _wait(client, run_id)["run"]["decision"] == "APPROVE"
