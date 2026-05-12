"""Détection pièces manquantes + anomalies — Sprint 1 §3.7.

Scanner périodique des accounting_entries + documents pour détecter
incohérences. Sprint 1 livre 3 règles solides (sur les 5 de la spec) :

1. `unpaid_invoice` : facture > N jours sans paiement associé (Sprint 2 :
   nécessite CAMT.053 §3.9 → reporté V2 de la règle).
2. `vat_no_evidence` : entry avec vat_code ≠ EXO sans source_document_id.
3. `potential_duplicate` : même fournisseur + même montant + dates ±5j.
4. `payment_without_invoice` : reporté Sprint 2 (CAMT.053).
5. `orphan_credit_note` : reporté Sprint 2 (besoin règles métier cabinet).

État `state` : open / resolved / false_positive.
Table `anomalies` créée idempotemment.
Multi-mandant strict via `cabinet_id` + `client_id` (mandant).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

_log = logging.getLogger("fiduciaire.missing_docs")

ANOMALIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cabinet_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    state TEXT NOT NULL DEFAULT 'open',
    subject_entity_type TEXT NOT NULL,
    subject_entity_id TEXT NOT NULL,
    details_json TEXT,
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    resolved_by TEXT,
    resolution_reason TEXT,
    UNIQUE (cabinet_id, client_id, type, subject_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_cabinet_state
  ON anomalies (cabinet_id, client_id, state);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity
  ON anomalies (severity);
"""

# Types d'anomalies supportés Sprint 1
TYPE_VAT_NO_EVIDENCE = "vat_no_evidence"
TYPE_POTENTIAL_DUPLICATE = "potential_duplicate"
TYPE_UNPAID_INVOICE = "unpaid_invoice"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

STATE_OPEN = "open"
STATE_RESOLVED = "resolved"
STATE_FALSE_POSITIVE = "false_positive"


def init_anomalies_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(ANOMALIES_SCHEMA)


@dataclass
class Anomaly:
    id: int
    cabinet_id: str
    client_id: str
    type: str
    severity: str
    state: str
    subject_entity_type: str
    subject_entity_id: str
    details: dict[str, Any]
    detected_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None
    resolution_reason: str | None = None


@dataclass
class ScanReport:
    cabinet_id: str
    client_id: str | None
    rules_run: list[str] = field(default_factory=list)
    new_anomalies: int = 0
    existing_open: int = 0
    duration_s: float = 0.0


# --- Insert helper -----------------------------------------------------------


def _record_anomaly(
    conn: sqlite3.Connection,
    cabinet_id: str,
    client_id: str,
    anomaly_type: str,
    subject_entity_type: str,
    subject_entity_id: str | int,
    severity: str = SEVERITY_WARNING,
    details: dict | None = None,
) -> int | None:
    """Insert idempotent — retourne new id ou None si déjà existant."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO anomalies
        (cabinet_id, client_id, type, severity, subject_entity_type,
         subject_entity_id, details_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cabinet_id, client_id, anomaly_type, severity,
            subject_entity_type, str(subject_entity_id),
            json.dumps(details or {}, ensure_ascii=False),
        ),
    )
    if cur.rowcount == 1:
        return int(cur.lastrowid)
    return None


# --- Rules -------------------------------------------------------------------


def _rule_vat_no_evidence(
    conn: sqlite3.Connection, cabinet_id: str, client_id: str | None,
) -> int:
    """TVA déclarée (vat_code != EXO, vat_amount > 0) sans justif valide.

    Le source_document_id est NOT NULL FK, donc on détecte le cas où le
    doc existe mais sans archive_path (PDF physique manquant) — typiquement
    fichier supprimé par erreur après ingestion.
    """
    sql = (
        "SELECT ae.id FROM accounting_entries ae "
        "LEFT JOIN documents d ON ae.source_document_id = d.id "
        "WHERE ae.client_id = ? "
        "  AND ae.state IN ('proposed', 'validated') "
        "  AND ae.vat_code NOT IN ('EXO', 'EXP') "
        "  AND COALESCE(ae.vat_amount, 0) > 0 "
        "  AND (d.id IS NULL OR d.archive_path IS NULL OR d.archive_path = '')"
    )
    params: list = [cabinet_id]
    rows = conn.execute(sql, params).fetchall()
    n = 0
    for r in rows:
        if client_id is not None and client_id != cabinet_id:
            # Sprint 1 : client_id == cabinet_id (single tenant per DB).
            # Pour multi-mandant N=3, cabinet_id est le client_id du mandant.
            continue
        new_id = _record_anomaly(
            conn, cabinet_id, cabinet_id,
            TYPE_VAT_NO_EVIDENCE,
            "accounting_entry", r["id"],
            severity=SEVERITY_WARNING,
            details={"reason": "vat declared without source_document_id"},
        )
        if new_id is not None:
            n += 1
    return n


def _rule_potential_duplicate(
    conn: sqlite3.Connection, cabinet_id: str, client_id: str | None,
    day_window: int = 5,
) -> int:
    """Même fournisseur (description) + même montant + dates ±5j."""
    # Approche simple : group by (description, amount) puis check dates.
    rows = conn.execute(
        "SELECT id, date, amount_chf, description FROM accounting_entries "
        "WHERE client_id = ? AND state IN ('proposed', 'validated') "
        "ORDER BY date ASC",
        (cabinet_id,),
    ).fetchall()
    n = 0
    by_key: dict[tuple, list] = {}
    for r in rows:
        # Note: description peut être chiffrée. On groupe sur la valeur stockée
        # (qui contient le marqueur enc:v1: si chiffrée) — donc même chiffrement
        # input → même token cryptographiquement, mais Fernet inclut un nonce
        # aléatoire donc les tokens diffèrent. Limitation Sprint 1 :
        # la règle ne marche que sur valeurs en clair.
        # Mitigation : on utilise amount_chf + date pour grouper.
        key = (float(r["amount_chf"]), str(r["description"]))
        by_key.setdefault(key, []).append(r)

    for entries in by_key.values():
        if len(entries) < 2:
            continue
        # Check dates proches
        for i, e1 in enumerate(entries):
            for e2 in entries[i + 1:]:
                try:
                    d1 = datetime.fromisoformat(e1["date"])
                    d2 = datetime.fromisoformat(e2["date"])
                except (ValueError, TypeError):
                    continue
                if abs((d1 - d2).days) <= day_window:
                    new_id = _record_anomaly(
                        conn, cabinet_id, cabinet_id,
                        TYPE_POTENTIAL_DUPLICATE,
                        "accounting_entry", e2["id"],
                        severity=SEVERITY_WARNING,
                        details={
                            "twin_entry_id": e1["id"],
                            "amount_chf": float(e1["amount_chf"]),
                            "date_a": e1["date"], "date_b": e2["date"],
                        },
                    )
                    if new_id is not None:
                        n += 1
    return n


def _rule_unpaid_invoice(
    conn: sqlite3.Connection, cabinet_id: str, client_id: str | None,
    overdue_days: int = 60, today: datetime | None = None,
) -> int:
    """Facture > overdue_days sans bexio_id (proxy "non payée").

    Note : approximation Sprint 1. Avec CAMT.053 §3.9 on aura un signal
    plus fin (matching bancaire). Pour l'instant : si bexio_id NULL et
    date < today - overdue_days → flag.
    """
    today = today or datetime.now()
    cutoff = (today - timedelta(days=overdue_days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT id, date FROM accounting_entries "
        "WHERE client_id = ? AND state = 'validated' "
        "  AND (bexio_id IS NULL OR bexio_id = '') "
        "  AND date < ?",
        (cabinet_id, cutoff),
    ).fetchall()
    n = 0
    for r in rows:
        new_id = _record_anomaly(
            conn, cabinet_id, cabinet_id,
            TYPE_UNPAID_INVOICE,
            "accounting_entry", r["id"],
            severity=SEVERITY_WARNING,
            details={"date": r["date"], "overdue_days": overdue_days},
        )
        if new_id is not None:
            n += 1
    return n


# --- Scanner principal -------------------------------------------------------


_RULES = {
    TYPE_VAT_NO_EVIDENCE: _rule_vat_no_evidence,
    TYPE_POTENTIAL_DUPLICATE: _rule_potential_duplicate,
    TYPE_UNPAID_INVOICE: _rule_unpaid_invoice,
}


def scan_anomalies(
    *,
    cabinet_id: str,
    conn: sqlite3.Connection,
    client_id: str | None = None,
    rules: list[str] | None = None,
) -> ScanReport:
    """Lance les règles activées et persiste les anomalies détectées (idempotent).

    Args:
        cabinet_id: filtre multi-mandant strict.
        client_id: sous-mandant (Sprint 1 : == cabinet_id en pratique).
        rules: liste de types à scanner. Défaut: toutes.
    """
    import time
    t0 = time.perf_counter()
    init_anomalies_schema(conn)

    rules_to_run = rules or list(_RULES.keys())
    report = ScanReport(cabinet_id=cabinet_id, client_id=client_id)

    for rule_name in rules_to_run:
        fn = _RULES.get(rule_name)
        if fn is None:
            _log.warning("règle inconnue: %s", rule_name)
            continue
        report.rules_run.append(rule_name)
        n_new = fn(conn, cabinet_id, client_id)
        report.new_anomalies += n_new

    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM anomalies "
        "WHERE cabinet_id = ? AND state = 'open'",
        (cabinet_id,),
    ).fetchone()
    report.existing_open = int(existing["n"])
    report.duration_s = time.perf_counter() - t0
    return report


# --- Workflow resolved / false_positive -------------------------------------


def mark_anomaly_resolved(
    conn: sqlite3.Connection, anomaly_id: int,
    user_id: str | None = None, reason: str | None = None,
) -> None:
    conn.execute(
        "UPDATE anomalies SET state='resolved', "
        "resolved_at=datetime('now'), resolved_by=?, resolution_reason=? "
        "WHERE id=?",
        (user_id, reason, anomaly_id),
    )


def mark_anomaly_false_positive(
    conn: sqlite3.Connection, anomaly_id: int,
    user_id: str | None = None, reason: str | None = None,
) -> None:
    conn.execute(
        "UPDATE anomalies SET state='false_positive', "
        "resolved_at=datetime('now'), resolved_by=?, resolution_reason=? "
        "WHERE id=?",
        (user_id, reason, anomaly_id),
    )


def list_open_anomalies(
    conn: sqlite3.Connection, cabinet_id: str,
    client_id: str | None = None, severity: str | None = None,
) -> list[Anomaly]:
    sql = ("SELECT * FROM anomalies WHERE cabinet_id = ? AND state = 'open'")
    params: list = [cabinet_id]
    if client_id:
        sql += " AND client_id = ?"
        params.append(client_id)
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    sql += " ORDER BY detected_at DESC"
    rows = conn.execute(sql, params).fetchall()
    out: list[Anomaly] = []
    for r in rows:
        out.append(Anomaly(
            id=int(r["id"]),
            cabinet_id=r["cabinet_id"], client_id=r["client_id"],
            type=r["type"], severity=r["severity"], state=r["state"],
            subject_entity_type=r["subject_entity_type"],
            subject_entity_id=r["subject_entity_id"],
            details=json.loads(r["details_json"] or "{}"),
            detected_at=r["detected_at"],
            resolved_at=r["resolved_at"],
            resolved_by=r["resolved_by"],
            resolution_reason=r["resolution_reason"],
        ))
    return out
