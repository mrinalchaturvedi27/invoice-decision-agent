import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "app.db"))
SEED_DIR = ROOT / "data" / "seed"
SAMPLES_DIR = ROOT / "data" / "samples"
FRONTEND_DIST = ROOT / "frontend" / "dist"

EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "claude-opus-5-5")
EXTRACT_EFFORT = os.environ.get("EXTRACT_EFFORT", "medium")
EXPLAIN_MODEL = os.environ.get("EXPLAIN_MODEL", "claude-opus-5-5")

# Pause between fast deterministic stages so the live timeline is readable. 0 disables.
STAGE_PACING_MS = int(os.environ.get("STAGE_PACING_MS", "250"))

# Protects POST /api/admin/reset on the hosted app. Unset = reset allowed (local dev).
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SANDBOXES = int(os.environ.get("MAX_SANDBOXES", "500"))  # one SQLite file per reviewer browser
