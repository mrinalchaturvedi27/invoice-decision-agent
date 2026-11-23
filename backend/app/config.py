import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "app.db"))
FRONTEND_DIST = ROOT / "frontend" / "dist"

EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "claude-opus-5-5")
EXTRACT_EFFORT = os.environ.get("EXTRACT_EFFORT", "medium")
EXPLAIN_MODEL = os.environ.get("EXPLAIN_MODEL", "claude-opus-5-5")
