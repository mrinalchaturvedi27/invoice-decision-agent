from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import EXTRACT_MODEL, FRONTEND_DIST
from app.policy import POLICY_VERSION

app = FastAPI(title="Invoice Decision Agent")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "policy_version": POLICY_VERSION, "extract_model": EXTRACT_MODEL}


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
