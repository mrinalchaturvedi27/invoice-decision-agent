"""Server-wide cap on paid model calls over a rolling 24 hours, shared by every sandbox.

Only live calls count: an extraction served from the cache never reaches the model. When the cap is hit,
extraction fails the run before any decision (ledger untouched, retry later) and the explanation falls
back to the sentence built from the rule trace."""
from __future__ import annotations

import time

from app import config, db

WINDOW_SECONDS = 24 * 60 * 60


class BudgetExceeded(RuntimeError):
    pass


def take(kind: str) -> None:
    """Reserve one model call, or raise BudgetExceeded. Counted in the default database for all sandboxes."""
    conn = db.connect(db.default_path())
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            now = time.time()
            conn.execute("DELETE FROM model_calls WHERE ts < ?", (now - WINDOW_SECONDS,))
            used = conn.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0]
            if used >= config.MODEL_CALLS_PER_DAY:
                conn.execute("ROLLBACK")
                raise BudgetExceeded(f"Daily model-call budget reached ({used}/{config.MODEL_CALLS_PER_DAY} in the "
                                     f"last 24 h). Nothing was decided; retry later.")
            conn.execute("INSERT INTO model_calls(kind, ts) VALUES (?, ?)", (kind, now))
            conn.execute("COMMIT")
        except BudgetExceeded:
            raise
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def usage() -> dict:
    conn = db.connect(db.default_path())
    try:
        used = conn.execute("SELECT COUNT(*) FROM model_calls WHERE ts >= ?",
                            (time.time() - WINDOW_SECONDS,)).fetchone()[0]
    finally:
        conn.close()
    return {"used": used, "limit": config.MODEL_CALLS_PER_DAY}


class Budgeted:
    """Wraps the extractor or explainer so every live call is counted against the cap first."""

    def __init__(self, inner, kind: str):
        self.inner, self.kind = inner, kind

    def __call__(self, *args):
        take(self.kind)
        return self.inner(*args)
