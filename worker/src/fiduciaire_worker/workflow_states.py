"""Machine à états des écritures comptables proposées.

États :
  proposed  → validated  (humain valide)
  proposed  → rejected   (humain rejette avec raison)
  proposed  → proposed   (humain corrige des champs, état inchangé)
  validated → proposed   (re-ouverture, rare mais autorisé)
  rejected  → ∅          (terminal)

Toutes les transitions sont tracées dans `entry_state_changes`.
"""

from __future__ import annotations

import sqlite3

from .accounting_schema import (
    ENTRY_STATE_PROPOSED,
    ENTRY_STATE_REJECTED,
    ENTRY_STATE_VALIDATED,
)
from . import audit_log as _audit


_AUDIT_ACTION_FOR_STATE = {
    ENTRY_STATE_VALIDATED: _audit.ACTION_VALIDATED,
    ENTRY_STATE_REJECTED: _audit.ACTION_REJECTED,
    ENTRY_STATE_PROPOSED: _audit.ACTION_REOPENED,
}


def _safe_audit(
    conn: sqlite3.Connection,
    entry_id: int,
    from_state: str,
    to_state: str,
    user_id: str | None,
    reason: str | None,
) -> None:
    """Log audit event si table dispo. Silent skip sinon (back-compat)."""
    try:
        row = conn.execute(
            "SELECT client_id FROM accounting_entries WHERE id=?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return
        action = _AUDIT_ACTION_FOR_STATE.get(to_state, f"state_{to_state}")
        _audit.log_audit_event(
            conn, cabinet_id=row["client_id"],
            entity_type="accounting_entry", entity_id=entry_id,
            action=action, user_id=user_id,
            before={"state": from_state},
            after={"state": to_state, "reason": reason},
        )
    except sqlite3.OperationalError:
        # Table audit_log pas initialisée → silent skip
        pass

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ENTRY_STATE_PROPOSED: {
        ENTRY_STATE_VALIDATED,
        ENTRY_STATE_REJECTED,
        ENTRY_STATE_PROPOSED,
    },
    ENTRY_STATE_VALIDATED: {ENTRY_STATE_PROPOSED},
    ENTRY_STATE_REJECTED: set(),  # terminal
}


class InvalidTransition(Exception):
    pass


def transition(
    conn: sqlite3.Connection,
    entry_id: int,
    to_state: str,
    user_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Déclenche une transition d'état + log dans entry_state_changes.

    Lève InvalidTransition si la cible n'est pas autorisée depuis l'état courant.
    """
    row = conn.execute(
        "SELECT state FROM accounting_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    if row is None:
        raise InvalidTransition(f"entry {entry_id} introuvable")
    from_state = row["state"]

    allowed = ALLOWED_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise InvalidTransition(
            f"transition {from_state} → {to_state} non autorisée "
            f"(autorisées depuis {from_state}: {sorted(allowed) or 'aucune'})"
        )

    conn.execute(
        "UPDATE accounting_entries SET state = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (to_state, entry_id),
    )
    conn.execute(
        "INSERT INTO entry_state_changes "
        "(entry_id, from_state, to_state, user_id, reason) VALUES (?, ?, ?, ?, ?)",
        (entry_id, from_state, to_state, user_id, reason),
    )
    _safe_audit(conn, entry_id, from_state, to_state, user_id, reason)


def history(conn: sqlite3.Connection, entry_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT from_state, to_state, user_id, reason, changed_at "
        "FROM entry_state_changes WHERE entry_id = ? ORDER BY id ASC",
        (entry_id,),
    ).fetchall()
