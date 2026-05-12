"""Schéma SQLite Sprint 0a — étend db.py sans casser le POC.

Tables ajoutées :
- bexio_sync                  : cache lecture Bexio (accounts, contacts, manual_entries)
- bexio_sync_runs             : journal des syncs Bexio
- vendor_account_history      : heuristique fournisseur → compte
- accounting_entries          : écritures proposées par entry_proposer
- entry_state_changes         : audit des transitions d'état

Multi-mandant first-class : toutes les tables ont un `client_id` indexé.
Idempotent : `init_accounting_schema` peut être rappelé sans effet de bord.
"""

from __future__ import annotations

import sqlite3

ACCOUNTING_SCHEMA = """
CREATE TABLE IF NOT EXISTS bexio_sync (
    client_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (client_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_bexio_sync_type
  ON bexio_sync(client_id, entity_type);

CREATE TABLE IF NOT EXISTS bexio_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    accounts_count INTEGER,
    contacts_count INTEGER,
    entries_count INTEGER,
    ok INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS vendor_account_history (
    client_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    vendor_name TEXT NOT NULL,
    account TEXT NOT NULL,
    vat_code TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (client_id, vendor_id, account, vat_code)
);

CREATE INDEX IF NOT EXISTS idx_vah_lookup
  ON vendor_account_history(client_id, vendor_name);

CREATE TABLE IF NOT EXISTS accounting_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    source_document_id INTEGER NOT NULL REFERENCES documents(id),
    date TEXT NOT NULL,
    debit_account TEXT NOT NULL,
    credit_account TEXT NOT NULL,
    amount_chf REAL NOT NULL,
    vat_code TEXT NOT NULL,
    vat_amount REAL,
    description TEXT NOT NULL,
    confidence_account REAL NOT NULL,
    confidence_vat REAL NOT NULL,
    reasoning TEXT,
    sources_json TEXT,
    state TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entries_client_state
  ON accounting_entries(client_id, state);

CREATE INDEX IF NOT EXISTS idx_entries_source_doc
  ON accounting_entries(source_document_id);

CREATE TABLE IF NOT EXISTS entry_state_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES accounting_entries(id),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    user_id TEXT,
    reason TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_state_changes_entry
  ON entry_state_changes(entry_id);

-- Sprint 1 §3.2 — Bexio push log (cf docs/specs/bexio-push.md)

CREATE TABLE IF NOT EXISTS bexio_push_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    entry_id INTEGER NOT NULL REFERENCES accounting_entries(id),
    attempt INTEGER NOT NULL DEFAULT 1,
    http_status INTEGER,
    bexio_id TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    response_excerpt TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bexio_push_log_client_entry
  ON bexio_push_log(client_id, entry_id);
"""

ENTRY_STATE_PROPOSED = "proposed"
ENTRY_STATE_VALIDATED = "validated"
ENTRY_STATE_REJECTED = "rejected"


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, definition: str,
) -> bool:
    """ALTER TABLE ADD COLUMN idempotent. Retourne True si ajout effectué."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols = {row[1] for row in rows}
    if column in cols:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def init_accounting_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(ACCOUNTING_SCHEMA)
    # Migrations idempotentes : colonnes ajoutées après la baseline initiale.
    _add_column_if_missing(conn, "accounting_entries", "bexio_id", "TEXT")
    _add_column_if_missing(conn, "accounting_entries", "bexio_pushed_at", "TEXT")
    # Sprint 1 §3.6 — audit trail immutable (auto-init pour que les hooks
    # dans workflow_states/entry_proposer/bexio_push trouvent toujours la table).
    from . import audit_log
    audit_log.init_audit_schema(conn)
