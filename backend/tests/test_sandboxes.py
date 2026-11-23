"""Each reviewer browser gets its own demo ledger, so replaying the scenarios never collides with
someone else's run, and resetting your own sandbox needs no admin token."""
import time

import pytest
from fastapi.testclient import TestClient

from app import config, main

A, B = "a" * 32, "b" * 32


@pytest.fixture
def client(runner):
    main.app.state.runner = runner
    with TestClient(main.app) as c:
        yield c
    main.app.state.runner = None


def _run(client, ws, sample):
    run_id = client.post(f"/api/runs/sample/{sample}", headers={"X-Workspace": ws}).json()["run_id"]
    for _ in range(200):
        snap = client.get(f"/api/runs/{run_id}", headers={"X-Workspace": ws}).json()
        if snap["run"]["status"] in ("done", "error"):
            return snap
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_two_reviewers_each_get_the_advertised_outcome(client):
    for ws in (A, B):
        a = _run(client, ws, "e1-a")["run"]
        assert (a["decision"], a["balance_before"], a["balance_after"]) == ("APPROVE", "48000.00", "28000.00")
    b = _run(client, A, "e1-b")["run"]
    assert (b["decision"], b["balance_after"]) == ("HOLD", "28000.00")
    assert client.get("/api/runs", headers={"X-Workspace": A}).json()["stats"]["runs"] == 2
    assert client.get("/api/runs", headers={"X-Workspace": B}).json()["stats"]["runs"] == 1
    assert client.get("/api/runs").json()["stats"]["runs"] == 0          # default database untouched


def test_runs_and_pdfs_are_scoped_to_their_sandbox(client):
    snap = _run(client, A, "e1-a")
    rid, inv = snap["run"]["id"], snap["invoice"]["id"]
    assert client.get(f"/api/runs/{rid}", headers={"X-Workspace": B}).status_code == 404
    assert client.get(f"/api/invoices/{inv}/pdf", params={"ws": B}).status_code == 404
    assert client.get(f"/api/invoices/{inv}/pdf", params={"ws": A}).status_code == 200
    with client.stream("GET", f"/api/runs/{rid}/stream", params={"ws": A}) as s:
        assert any(l == "event: end" for l in s.iter_lines())


def test_scenario_list_shows_what_already_ran_here(client):
    _run(client, A, "e1-a")
    rows = {s["id"]: s for s in client.get("/api/samples", headers={"X-Workspace": A}).json()}
    assert [r["decision"] for r in rows["e1-a"]["runs"]] == ["APPROVE"] and rows["e1-b"]["runs"] == []
    assert all(not s["runs"] for s in client.get("/api/samples", headers={"X-Workspace": B}).json())


def test_sandbox_reset_needs_no_token_but_the_shared_default_does(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "secret")
    _run(client, A, "e1-a")
    assert client.get("/api/health", headers={"X-Workspace": A}).json()["reset_requires_token"] is False
    assert client.post("/api/admin/reset", json={}, headers={"X-Workspace": A}).status_code == 200
    assert client.get("/api/runs", headers={"X-Workspace": A}).json()["stats"]["runs"] == 0
    assert _run(client, A, "e1-a")["run"]["decision"] == "APPROVE"    # replay gives the advertised result again
    assert client.post("/api/admin/reset", json={}).status_code == 403
    assert client.post("/api/admin/reset", json={}, headers={"X-Admin-Token": "secret"}).status_code == 200


def test_bad_sandbox_ids_and_the_cap(client, monkeypatch):
    assert client.get("/api/runs", headers={"X-Workspace": "../../etc"}).status_code == 400
    assert client.get("/api/runs", headers={"X-Workspace": "short"}).status_code == 400
    client.get("/api/runs", headers={"X-Workspace": A})
    monkeypatch.setattr(config, "MAX_SANDBOXES", 1)
    assert client.get("/api/runs", headers={"X-Workspace": B}).status_code == 503
    assert client.get("/api/runs", headers={"X-Workspace": A}).status_code == 200   # existing ones keep working


def test_po_ledger_endpoint_reports_live_balances_per_sandbox(client):
    _run(client, A, "e1-a")
    pos = {p["id"]: p for p in client.get("/api/pos", headers={"X-Workspace": A}).json()}
    assert (pos["PO-1042"]["open_balance"], pos["PO-1042"]["total"]) == ("28000.00", "48000.00")
    assert pos["PO-1042"]["vendor"] == "Acme Industrial Supply Ltd"
    other = {p["id"]: p for p in client.get("/api/pos", headers={"X-Workspace": B}).json()}
    assert other["PO-1042"]["open_balance"] == "48000.00"
