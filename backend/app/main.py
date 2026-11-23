from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import budget, config, db, ledger, queries
from app.pipeline.explain import ClaudeExplainer
from app.pipeline.extract import ClaudeExtractor
from app.pipeline.runner import STAGES, Runner
from app.policy import POLICY_VERSION

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    db.seed_if_empty()
    if getattr(app.state, "runner", None) is None:
        app.state.runner = Runner(extractor=budget.Budgeted(ClaudeExtractor(), "extract"),
                                  explainer=budget.Budgeted(ClaudeExplainer(), "explain"),
                                  pacing_ms=config.STAGE_PACING_MS)
    yield


app = FastAPI(title="Invoice Decision Agent", lifespan=lifespan)


def sandbox(x_workspace: str | None = Header(default=None), ws: str | None = None) -> Path:
    """The caller's sandbox database. Browsers send a random id (header, or ?ws= where a header can't be set:
    EventSource, iframes). No id → the default database."""
    try:
        return db.sandbox_path(x_workspace or ws)
    except ValueError:
        raise HTTPException(400, "Invalid sandbox id")
    except db.SandboxLimit:
        raise HTTPException(503, "Too many sandboxes on this server; ask the admin to clear old ones")


def J(obj, status: int = 200) -> Response:
    return Response(content=db.dumps(obj), media_type="application/json", status_code=status)


def _in_sandbox(path: Path, fn, *args) -> None:
    with db.use(path):
        fn(*args)


@lru_cache
def _manifest() -> list[dict]:
    items = json.loads((config.SAMPLES_DIR / "manifest.json").read_text())
    for m in items:
        m["sha256"] = hashlib.sha256((config.SAMPLES_DIR / m["file"]).read_bytes()).hexdigest()
    return items


def _sample(sample_id: str) -> dict:
    m = next((s for s in _manifest() if s["id"] == sample_id), None)
    if m is None:
        raise HTTPException(404, "Unknown sample")
    return m


def _start(request: Request, sb: Path, pdf_bytes: bytes, filename: str) -> Response:
    if len(pdf_bytes) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "PDF is larger than 10 MB")
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(415, "Only PDF invoices are accepted")
    runner: Runner = request.app.state.runner
    try:
        with db.use(sb):
            run_id = runner.create_run(pdf_bytes, filename)
    except Exception as e:
        raise HTTPException(422, f"Could not open the PDF: {e}")
    threading.Thread(target=_in_sandbox, args=(sb, runner.execute, run_id), daemon=True).start()
    return J({"run_id": run_id}, 201)


@app.get("/api/health")
def health(sb: Path = Depends(sandbox)) -> Response:
    return J({"status": "ok", "policy_version": POLICY_VERSION, "extract_model": config.EXTRACT_MODEL,
              "model_credentials": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
              "stages": STAGES, "sandbox": sb != db.default_path(),
              "model_calls": budget.usage(),
              "reset_requires_token": bool(config.ADMIN_TOKEN) and sb == db.default_path()})


@app.get("/api/samples")
def samples(sb: Path = Depends(sandbox)) -> Response:
    """The prepared scenarios, each with the runs it already has in this sandbox (oldest first)."""
    conn = db.connect(sb)
    try:
        rows = conn.execute("SELECT r.id, r.status, r.decision, r.deciding_rule, i.sha256 FROM runs r "
                            "JOIN invoices i ON i.id = r.invoice_id ORDER BY r.id").fetchall()
    finally:
        conn.close()
    by_sha: dict[str, list[dict]] = {}
    for r in rows:
        by_sha.setdefault(r["sha256"], []).append(
            {"id": r["id"], "status": r["status"], "decision": r["decision"], "deciding_rule": r["deciding_rule"]})
    return J([{**{k: v for k, v in m.items() if k != "sha256"}, "runs": by_sha.get(m["sha256"], [])}
              for m in _manifest()])


@app.get("/api/pos")
def list_pos(sb: Path = Depends(sandbox)) -> Response:
    """Every PO in this sandbox with its live open balance (the ledger strip in the UI)."""
    conn = db.connect(sb)
    try:
        out = []
        for r in conn.execute("SELECT p.id, p.description, p.status, v.name AS vendor FROM purchase_orders p "
                              "JOIN vendors v ON v.id = p.vendor_id ORDER BY p.id").fetchall():
            st = ledger.open_state(conn, r["id"])
            out.append({"id": r["id"], "vendor": r["vendor"], "description": r["description"], "status": r["status"],
                        "total": st["total"], "open_balance": st["open_balance"]})
        return J(out)
    finally:
        conn.close()


@app.get("/api/samples/{sample_id}/pdf")
def sample_pdf(sample_id: str):
    m = _sample(sample_id)
    return FileResponse(config.SAMPLES_DIR / m["file"], media_type="application/pdf", filename=m["file"])


@app.post("/api/runs")
async def create_run(request: Request, file: UploadFile = File(...), sb: Path = Depends(sandbox)) -> Response:
    data = await file.read()
    return _start(request, sb, data, Path(file.filename or "upload.pdf").name)


@app.post("/api/runs/sample/{sample_id}")
def create_sample_run(request: Request, sample_id: str, sb: Path = Depends(sandbox)) -> Response:
    m = _sample(sample_id)
    return _start(request, sb, (config.SAMPLES_DIR / m["file"]).read_bytes(), m["file"])


@app.post("/api/runs/{run_id}/retry")
def retry_run(request: Request, run_id: int, sb: Path = Depends(sandbox)) -> Response:
    conn = db.connect(sb)
    try:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        # Claim the run atomically so two retry clicks can't execute it twice at once.
        claimed = row is not None and conn.execute(
            "UPDATE runs SET status='queued' WHERE id = ? AND status = 'error'", (run_id,)).rowcount == 1
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "Unknown run")
    if not claimed:
        raise HTTPException(409, "Only failed runs can be retried")
    threading.Thread(target=_in_sandbox, args=(sb, request.app.state.runner.execute, run_id), daemon=True).start()
    return J({"run_id": run_id}, 202)


@app.get("/api/runs")
def list_runs(decision: str | None = None, sb: Path = Depends(sandbox)) -> Response:
    conn = db.connect(sb)
    try:
        return J({"runs": queries.list_runs(conn, decision), "stats": queries.stats(conn)})
    finally:
        conn.close()


@app.get("/api/runs/{run_id}")
def get_run(run_id: int, sb: Path = Depends(sandbox)) -> Response:
    conn = db.connect(sb)
    try:
        snap = queries.run_snapshot(conn, run_id)
    finally:
        conn.close()
    if snap is None:
        raise HTTPException(404, "Unknown run")
    return J(snap)


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: int, sb: Path = Depends(sandbox)):
    """Server-sent events: the full run snapshot whenever it changes, until the run finishes."""
    def gen():
        last, deadline = None, time.time() + 600
        while time.time() < deadline:
            conn = db.connect(sb)
            try:
                snap = queries.run_snapshot(conn, run_id)
            finally:
                conn.close()
            if snap is None:
                yield "event: error\ndata: {\"detail\": \"Unknown run\"}\n\n"
                return
            payload = db.dumps(snap)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if snap["run"]["status"] in ("done", "error"):
                yield "event: end\ndata: {}\n\n"
                return
            time.sleep(0.25)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, sb: Path = Depends(sandbox)):
    conn = db.connect(sb)
    try:
        row = conn.execute("SELECT path, filename FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    finally:
        conn.close()
    if row is None or not Path(row["path"]).exists():
        raise HTTPException(404, "Unknown invoice")
    return FileResponse(row["path"], media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{row["filename"]}"'})


class ResetBody(BaseModel):
    clear_cache: bool = False


@app.post("/api/admin/reset")
def reset(body: ResetBody, sb: Path = Depends(sandbox), x_admin_token: str | None = Header(default=None)) -> Response:
    """A sandbox belongs to one browser, so its owner can reset it freely. The default database is shared
    and needs the admin token when one is configured."""
    if sb == db.default_path() and config.ADMIN_TOKEN and x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(403, "Reset needs the admin token")
    with db.use(sb):
        db.reset(clear_cache=body.clear_cache)
    return J({"ok": True, "cache_cleared": body.clear_cache, "sandbox": sb != db.default_path()})


if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
