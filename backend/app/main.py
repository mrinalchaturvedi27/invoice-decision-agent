from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, db, queries
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
        app.state.runner = Runner(extractor=ClaudeExtractor(), explainer=ClaudeExplainer(),
                                  pacing_ms=config.STAGE_PACING_MS)
    yield


app = FastAPI(title="Invoice Decision Agent", lifespan=lifespan)


def J(obj, status: int = 200) -> Response:
    return Response(content=db.dumps(obj), media_type="application/json", status_code=status)


def _start(request: Request, pdf_bytes: bytes, filename: str) -> Response:
    if len(pdf_bytes) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "PDF is larger than 10 MB")
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(415, "Only PDF invoices are accepted")
    runner: Runner = request.app.state.runner
    try:
        run_id = runner.create_run(pdf_bytes, filename)
    except Exception as e:
        raise HTTPException(422, f"Could not open the PDF: {e}")
    threading.Thread(target=runner.execute, args=(run_id,), daemon=True).start()
    return J({"run_id": run_id}, 201)


@app.get("/api/health")
def health() -> Response:
    import os
    return J({"status": "ok", "policy_version": POLICY_VERSION, "extract_model": config.EXTRACT_MODEL,
              "model_credentials": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
              "stages": STAGES, "reset_requires_token": bool(config.ADMIN_TOKEN)})


@app.get("/api/samples")
def samples() -> Response:
    return J(json.loads((config.SAMPLES_DIR / "manifest.json").read_text()))


@app.get("/api/samples/{sample_id}/pdf")
def sample_pdf(sample_id: str):
    m = next((s for s in json.loads((config.SAMPLES_DIR / "manifest.json").read_text()) if s["id"] == sample_id), None)
    if m is None:
        raise HTTPException(404, "Unknown sample")
    return FileResponse(config.SAMPLES_DIR / m["file"], media_type="application/pdf", filename=m["file"])


@app.post("/api/runs")
async def create_run(request: Request, file: UploadFile = File(...)) -> Response:
    data = await file.read()
    return _start(request, data, Path(file.filename or "upload.pdf").name)


@app.post("/api/runs/sample/{sample_id}")
def create_sample_run(request: Request, sample_id: str) -> Response:
    m = next((s for s in json.loads((config.SAMPLES_DIR / "manifest.json").read_text()) if s["id"] == sample_id), None)
    if m is None:
        raise HTTPException(404, "Unknown sample")
    return _start(request, (config.SAMPLES_DIR / m["file"]).read_bytes(), m["file"])


@app.post("/api/runs/{run_id}/retry")
def retry_run(request: Request, run_id: int) -> Response:
    conn = db.connect()
    try:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "Unknown run")
    if row["status"] != "error":
        raise HTTPException(409, "Only failed runs can be retried")
    threading.Thread(target=request.app.state.runner.execute, args=(run_id,), daemon=True).start()
    return J({"run_id": run_id}, 202)


@app.get("/api/runs")
def list_runs(decision: str | None = None) -> Response:
    conn = db.connect()
    try:
        return J({"runs": queries.list_runs(conn, decision), "stats": queries.stats(conn)})
    finally:
        conn.close()


@app.get("/api/runs/{run_id}")
def get_run(run_id: int) -> Response:
    conn = db.connect()
    try:
        snap = queries.run_snapshot(conn, run_id)
    finally:
        conn.close()
    if snap is None:
        raise HTTPException(404, "Unknown run")
    return J(snap)


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: int):
    """Server-sent events: the full run snapshot whenever it changes, until the run finishes."""
    def gen():
        last, deadline = None, time.time() + 600
        while time.time() < deadline:
            conn = db.connect()
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
def invoice_pdf(invoice_id: int):
    conn = db.connect()
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
def reset(body: ResetBody, x_admin_token: str | None = Header(default=None)) -> Response:
    if config.ADMIN_TOKEN and x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(403, "Reset needs the admin token")
    db.reset(clear_cache=body.clear_cache)
    return J({"ok": True, "cache_cleared": body.clear_cache})


if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
