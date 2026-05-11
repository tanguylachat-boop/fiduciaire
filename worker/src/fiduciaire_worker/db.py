"""SQLite layer — schéma + helpers (cf docs/pipeline.md §Schéma SQLite).

Idempotent : `init_schema` peut être rappelé sans effet de bord.
Idempotence ingestion : `insert_document` utilise INSERT OR IGNORE sur sha256.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT UNIQUE NOT NULL,
  original_filename TEXT NOT NULL,
  archive_path TEXT NOT NULL,
  ocr_text TEXT,
  ocr_engine TEXT,
  classification_json TEXT,
  type TEXT,
  client_slug TEXT,
  doc_date TEXT,
  montant_chf REAL,
  status TEXT NOT NULL,
  needs_review_reason TEXT,
  final_path TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  action TEXT NOT NULL,
  payload_json TEXT,
  duration_ms INTEGER,
  ok INTEGER NOT NULL DEFAULT 1,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_actions_document ON actions(document_id);

-- Sprint 1 §3.1 — IMAP fetch metadata (cf docs/specs/imap-fetch.md)

CREATE TABLE IF NOT EXISTS email_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cabinet_id TEXT NOT NULL,
  folder TEXT NOT NULL,
  uid INTEGER NOT NULL,
  uidvalidity INTEGER NOT NULL,
  message_id TEXT NOT NULL,
  date_received TEXT,
  from_addr TEXT,
  to_addr TEXT,
  subject TEXT,
  body_excerpt TEXT,
  encryption_status TEXT NOT NULL DEFAULT 'plain',
  size_bytes INTEGER,
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (cabinet_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_email_messages_cabinet_uid
  ON email_messages (cabinet_id, folder, uid);

CREATE TABLE IF NOT EXISTS email_attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES email_messages(id),
  filename TEXT,
  content_type TEXT,
  size_bytes INTEGER,
  content_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  document_id INTEGER REFERENCES documents(id),
  reason TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (email_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS idx_email_attachments_email
  ON email_attachments (email_id);
CREATE INDEX IF NOT EXISTS idx_email_attachments_doc
  ON email_attachments (document_id);

CREATE TABLE IF NOT EXISTS email_fetch_state (
  cabinet_id TEXT NOT NULL,
  folder TEXT NOT NULL,
  uidvalidity INTEGER,
  last_uid_seen INTEGER NOT NULL DEFAULT 0,
  last_fetch_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_fetch_status TEXT NOT NULL DEFAULT 'ok',
  PRIMARY KEY (cabinet_id, folder)
);
"""

# Constantes statuts email_attachments
EMAIL_ATT_STATUS_PENDING = "pending"
EMAIL_ATT_STATUS_PROCESSED = "processed"
EMAIL_ATT_STATUS_FAILED = "failed"
EMAIL_ATT_STATUS_UNSUPPORTED = "unsupported"
EMAIL_ATT_STATUS_ENCRYPTED_SKIPPED = "encrypted_skipped"
EMAIL_ATT_STATUS_OVERSIZED = "oversized"
EMAIL_ATT_STATUS_EMPTY = "empty"

# Statuts chiffrement email
EMAIL_ENC_PLAIN = "plain"
EMAIL_ENC_PGP = "pgp"
EMAIL_ENC_SMIME = "smime"

STATUS_INGESTED = "ingested"
STATUS_CLASSIFIED = "classified"
STATUS_ROUTED = "routed"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_FAILED = "failed"
STATUS_DUPLICATE = "duplicate"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def insert_document(
    conn: sqlite3.Connection,
    sha256: str,
    original_filename: str,
    archive_path: str,
) -> tuple[int, bool]:
    """Insert idempotent. Retourne (doc_id, is_new)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO documents (sha256, original_filename, archive_path, status) "
        "VALUES (?, ?, ?, ?)",
        (sha256, original_filename, archive_path, STATUS_INGESTED),
    )
    if cur.rowcount == 1:
        return int(cur.lastrowid), True
    row = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
    return int(row["id"]), False


def update_document(conn: sqlite3.Connection, doc_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields_serialized = {
        k: (json.dumps(v, ensure_ascii=False) if k == "classification_json" and not isinstance(v, str) else v)
        for k, v in fields.items()
    }
    set_clause = ", ".join(f"{k} = ?" for k in fields_serialized) + ", updated_at = datetime('now')"
    values = list(fields_serialized.values()) + [doc_id]
    conn.execute(f"UPDATE documents SET {set_clause} WHERE id = ?", values)


def log_action(
    conn: sqlite3.Connection,
    doc_id: int,
    action: str,
    payload: dict | None = None,
    duration_ms: int | None = None,
    ok: bool = True,
    error: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO actions (document_id, action, payload_json, duration_ms, ok, error) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            doc_id,
            action,
            json.dumps(payload, ensure_ascii=False) if payload else None,
            duration_ms,
            1 if ok else 0,
            error,
        ),
    )


def get_document(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
