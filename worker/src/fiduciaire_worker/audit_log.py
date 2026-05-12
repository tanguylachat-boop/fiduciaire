"""Audit trail immutable — Sprint 1 §3.6.

Table `audit_log` append-only avec chaînage hash : chaque ligne contient
le hash de la précédente + hash de soi-même. Toute modification ultérieure
casse la chaîne, détectable via `verify_audit_chain`.

Hash : SHA-256(prev_hash || cabinet_id || user_id || timestamp || entity_type
      || entity_id || action || before_json || after_json).

Pour le contrôle fiscal CH (10 ans rétention), la chain offre une trace
immutable des décisions humaines (validation, push, rejet).

Hooks intégrés (cf §3.6 brief) :
- `workflow_states.transition` → action `validated`/`rejected`/`reopened`
- `bexio_push.push_validated_entries` → action `pushed` (sur succès live)
- `entry_proposer.propose_entry` → action `proposed`
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("fiduciaire.audit_log")

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cabinet_id TEXT NOT NULL,
    user_id TEXT,
    timestamp TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    prev_hash TEXT NOT NULL,
    current_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_cabinet_ts
  ON audit_log (cabinet_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_entity
  ON audit_log (entity_type, entity_id);
"""

# Constantes actions standardisées
ACTION_PROPOSED = "proposed"
ACTION_VALIDATED = "validated"
ACTION_REJECTED = "rejected"
ACTION_REOPENED = "reopened"
ACTION_PUSHED = "bexio_pushed"
ACTION_PUSH_FAILED = "bexio_push_failed"

# Genesis hash (pas de prev → chain root)
GENESIS_HASH = "0" * 64


@dataclass
class AuditEvent:
    id: int
    cabinet_id: str
    user_id: str | None
    timestamp: str
    entity_type: str
    entity_id: str
    action: str
    before_json: str | None
    after_json: str | None
    prev_hash: str
    current_hash: str


@dataclass
class ChainVerificationResult:
    cabinet_id: str
    total_events: int
    is_valid: bool
    first_invalid_id: int | None = None
    first_invalid_reason: str | None = None


def init_audit_schema(conn: sqlite3.Connection) -> None:
    """Idempotent : crée la table audit_log + indexes si absent."""
    conn.executescript(AUDIT_SCHEMA)


# --- Hash logic --------------------------------------------------------------


def _compute_hash(
    prev_hash: str,
    cabinet_id: str,
    user_id: str | None,
    timestamp: str,
    entity_type: str,
    entity_id: str,
    action: str,
    before_json: str | None,
    after_json: str | None,
) -> str:
    """Compute SHA-256 of canonical concatenation. Stable across runs."""
    parts = [
        prev_hash,
        cabinet_id,
        user_id or "",
        timestamp,
        entity_type,
        str(entity_id),
        action,
        before_json or "",
        after_json or "",
    ]
    # Séparateur explicite pour éviter ambiguïté (foo+bar vs fo+obar)
    blob = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _last_hash_for_cabinet(
    conn: sqlite3.Connection, cabinet_id: str,
) -> str:
    """Retourne le current_hash du dernier event du cabinet, ou GENESIS si vide."""
    row = conn.execute(
        "SELECT current_hash FROM audit_log WHERE cabinet_id=? "
        "ORDER BY id DESC LIMIT 1",
        (cabinet_id,),
    ).fetchone()
    return row["current_hash"] if row else GENESIS_HASH


# --- Append API --------------------------------------------------------------


def log_audit_event(
    conn: sqlite3.Connection,
    *,
    cabinet_id: str,
    entity_type: str,
    entity_id: str | int,
    action: str,
    user_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> int:
    """Append 1 ligne immutable à la chain. Retourne l'id généré.

    Args:
        conn: connexion SQLite (audit schema initialisé).
        cabinet_id: multi-mandant strict.
        entity_type: ex. 'accounting_entry', 'email_message', 'bexio_push'.
        entity_id: ID local de l'entité (str ou int converti).
        action: ex. 'proposed', 'validated', 'bexio_pushed'.
        user_id: optionnel (None pour automatique / système).
        before: snapshot avant l'action (sera JSON-encodé).
        after: snapshot après l'action (sera JSON-encodé).
        timestamp: ISO 8601, défaut: `datetime.now(timezone.utc).isoformat()`.
    """
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    before_json = (
        json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None
    )
    after_json = (
        json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None
    )
    prev_hash = _last_hash_for_cabinet(conn, cabinet_id)
    current_hash = _compute_hash(
        prev_hash, cabinet_id, user_id, ts,
        entity_type, str(entity_id), action,
        before_json, after_json,
    )
    cur = conn.execute(
        """INSERT INTO audit_log
        (cabinet_id, user_id, timestamp, entity_type, entity_id, action,
         before_json, after_json, prev_hash, current_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cabinet_id, user_id, ts, entity_type, str(entity_id), action,
            before_json, after_json, prev_hash, current_hash,
        ),
    )
    return int(cur.lastrowid)


# --- Verification ------------------------------------------------------------


def verify_audit_chain(
    conn: sqlite3.Connection, cabinet_id: str,
) -> ChainVerificationResult:
    """Recompute chaque hash et vérifie la chain depuis le genesis.

    Détecte :
    - prev_hash incohérent (rupture de chain)
    - current_hash recalculé != current_hash stocké (tampering champs)
    """
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE cabinet_id=? ORDER BY id ASC",
        (cabinet_id,),
    ).fetchall()

    result = ChainVerificationResult(
        cabinet_id=cabinet_id, total_events=len(rows), is_valid=True,
    )

    expected_prev = GENESIS_HASH
    for row in rows:
        # Check prev_hash matches
        if row["prev_hash"] != expected_prev:
            result.is_valid = False
            result.first_invalid_id = int(row["id"])
            result.first_invalid_reason = (
                f"prev_hash mismatch: expected {expected_prev[:8]}..., "
                f"got {row['prev_hash'][:8]}..."
            )
            return result
        # Recompute current_hash
        recomputed = _compute_hash(
            row["prev_hash"], row["cabinet_id"], row["user_id"],
            row["timestamp"], row["entity_type"], row["entity_id"],
            row["action"], row["before_json"], row["after_json"],
        )
        if recomputed != row["current_hash"]:
            result.is_valid = False
            result.first_invalid_id = int(row["id"])
            result.first_invalid_reason = (
                f"current_hash mismatch: row data altered"
            )
            return result
        expected_prev = row["current_hash"]

    return result


# --- Query API ---------------------------------------------------------------


def get_events_for_entity(
    conn: sqlite3.Connection,
    cabinet_id: str,
    entity_type: str,
    entity_id: str | int,
) -> list[AuditEvent]:
    """Liste les events pour une entité (ordre chronologique)."""
    rows = conn.execute(
        """SELECT * FROM audit_log
        WHERE cabinet_id=? AND entity_type=? AND entity_id=?
        ORDER BY id ASC""",
        (cabinet_id, entity_type, str(entity_id)),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def list_events(
    conn: sqlite3.Connection,
    cabinet_id: str,
    since: str | None = None,
    until: str | None = None,
    entity_type: str | None = None,
    action: str | None = None,
    limit: int = 1000,
) -> list[AuditEvent]:
    """Recherche d'events avec filtres optionnels."""
    sql = "SELECT * FROM audit_log WHERE cabinet_id=?"
    params: list[Any] = [cabinet_id]
    if since:
        sql += " AND timestamp >= ?"
        params.append(since)
    if until:
        sql += " AND timestamp <= ?"
        params.append(until)
    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)
    if action:
        sql += " AND action = ?"
        params.append(action)
    sql += " ORDER BY id ASC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_event(r) for r in rows]


def _row_to_event(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(
        id=int(row["id"]),
        cabinet_id=row["cabinet_id"],
        user_id=row["user_id"],
        timestamp=row["timestamp"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        action=row["action"],
        before_json=row["before_json"],
        after_json=row["after_json"],
        prev_hash=row["prev_hash"],
        current_hash=row["current_hash"],
    )


# --- Export pour contrôle fiscal --------------------------------------------


def export_audit_text(
    conn: sqlite3.Connection,
    cabinet_id: str,
    since: str | None = None,
    until: str | None = None,
    out_path: Path | None = None,
) -> Path:
    """Génère un export texte de l'audit trail (pour contrôle fiscal CH).

    Format : 1 ligne par event, fichier `.txt` avec entête + footer hash.
    Pas de PDF Sprint 1 (dépendance lourde, à reporter Sprint 2 si besoin).
    """
    events = list_events(conn, cabinet_id, since=since, until=until)
    if out_path is None:
        out_path = Path(f"audit-{cabinet_id}-{since or 'all'}.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    chain_verif = verify_audit_chain(conn, cabinet_id)

    lines: list[str] = []
    lines.append(f"=== AUDIT TRAIL — {cabinet_id} ===")
    lines.append(f"Period       : {since or 'genesis'} → {until or 'now'}")
    lines.append(f"Total events : {len(events)}")
    lines.append(f"Chain status : {'VALID' if chain_verif.is_valid else 'BROKEN'}")
    if not chain_verif.is_valid:
        lines.append(
            f"  ⚠️  First invalid id={chain_verif.first_invalid_id} "
            f"reason={chain_verif.first_invalid_reason}"
        )
    lines.append("")
    lines.append("-" * 80)

    for e in events:
        lines.append(f"[{e.timestamp}] id={e.id} user={e.user_id or 'system'}")
        lines.append(f"  {e.entity_type}#{e.entity_id} → {e.action}")
        if e.before_json:
            lines.append(f"  before: {e.before_json[:200]}")
        if e.after_json:
            lines.append(f"  after:  {e.after_json[:200]}")
        lines.append(f"  hash:   {e.current_hash[:16]}... (prev: {e.prev_hash[:16]}...)")
        lines.append("")

    lines.append("-" * 80)
    last_hash = events[-1].current_hash if events else GENESIS_HASH
    lines.append(f"Final chain hash: {last_hash}")
    lines.append("=== END AUDIT TRAIL ===")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
