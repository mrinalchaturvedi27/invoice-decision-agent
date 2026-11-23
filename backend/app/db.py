"""SQLite storage. Plain sqlite3 so the ledger transaction (BEGIN IMMEDIATE) is explicit."""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app import config

_db_path: Path = config.DB_PATH
_upload_dir: Path = config.DATA_DIR / "uploads"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, tax_id TEXT, bank_last4 TEXT,
  currency TEXT NOT NULL, tax_rate TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS purchase_orders(
  id TEXT PRIMARY KEY, vendor_id TEXT NOT NULL, currency TEXT NOT NULL,
  status TEXT NOT NULL, total TEXT NOT NULL, description TEXT);
CREATE TABLE IF NOT EXISTS po_lines(
  id INTEGER PRIMARY KEY, po_id TEXT NOT NULL, line_no INTEGER NOT NULL, sku TEXT,
  description TEXT, qty TEXT NOT NULL, unit_price TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, filename TEXT, path TEXT NOT NULL,
  pages INTEGER, has_text_layer INTEGER, vendor_id TEXT, invoice_number TEXT, norm_number TEXT,
  invoice_date TEXT, subtotal TEXT, total TEXT, approved_run_id INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL, status TEXT NOT NULL, attempts INTEGER DEFAULT 0,
  decision TEXT, deciding_rule TEXT, deciding_message TEXT, policy_version TEXT,
  po_id TEXT, po_method TEXT, balance_before TEXT, balance_after TEXT, linked_invoice_id INTEGER,
  extraction_cached INTEGER, trace TEXT, explanation TEXT, explanation_source TEXT, error TEXT,
  started_at TEXT, decided_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS run_steps(
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, seq INTEGER NOT NULL, stage TEXT NOT NULL,
  status TEXT NOT NULL, summary TEXT, detail TEXT, started_at TEXT, finished_at TEXT, duration_ms INTEGER);
CREATE TABLE IF NOT EXISTS allocations(
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, invoice_id INTEGER NOT NULL, po_id TEXT NOT NULL,
  po_line_id INTEGER NOT NULL, qty TEXT NOT NULL, amount TEXT NOT NULL, created_at TEXT,
  UNIQUE(invoice_id, po_line_id));
CREATE TABLE IF NOT EXISTS extraction_cache(
  sha256 TEXT PRIMARY KEY, extraction TEXT NOT NULL, meta TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_steps_run ON run_steps(run_id, seq);
CREATE INDEX IF NOT EXISTS ix_alloc_po ON allocations(po_id);
"""


def configure(db_path: Path, data_dir: Path) -> None:
    global _db_path, _upload_dir
    _db_path, _upload_dir = Path(db_path), Path(data_dir) / "uploads"


def upload_dir() -> Path:
    _upload_dir.mkdir(parents=True, exist_ok=True)
    return _upload_dir


def connect() -> sqlite3.Connection:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def dumps(obj) -> str:
    return json.dumps(obj, default=lambda o: str(o) if isinstance(o, Decimal) else repr(o))


def init() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
        if "decided_at" not in cols:  # databases created before decisions were recorded with the posting
            conn.execute("ALTER TABLE runs ADD COLUMN decided_at TEXT")
    finally:
        conn.close()


def _load_seed(conn: sqlite3.Connection) -> None:
    seed = config.SEED_DIR
    with open(seed / "vendors.csv") as f:
        for r in csv.DictReader(f):
            conn.execute("INSERT INTO vendors VALUES (?,?,?,?,?,?)",
                         (r["id"], r["name"], r["tax_id"], r["bank_last4"], r["currency"], r["tax_rate"]))
    with open(seed / "purchase_orders.csv") as f:
        for r in csv.DictReader(f):
            conn.execute("INSERT INTO purchase_orders VALUES (?,?,?,?,?,?)",
                         (r["id"], r["vendor_id"], r["currency"], r["status"], r["total"], r["description"]))
    with open(seed / "po_lines.csv") as f:
        for r in csv.DictReader(f):
            conn.execute(
                "INSERT INTO po_lines(po_id, line_no, sku, description, qty, unit_price) VALUES (?,?,?,?,?,?)",
                (r["po_id"], int(r["line_no"]), r["sku"], r["description"], r["qty"], r["unit_price"]))


def seed_if_empty() -> None:
    conn = connect()
    try:
        if conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0] == 0:
            conn.execute("BEGIN IMMEDIATE")
            _load_seed(conn)
            conn.execute("COMMIT")
    finally:
        conn.close()


def reset(clear_cache: bool = False) -> None:
    """Restore the demo: seed reference data, empty ledger and history."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for t in ("allocations", "run_steps", "runs", "invoices", "po_lines", "purchase_orders", "vendors"):
            conn.execute(f"DELETE FROM {t}")
        if clear_cache:
            conn.execute("DELETE FROM extraction_cache")
        _load_seed(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
