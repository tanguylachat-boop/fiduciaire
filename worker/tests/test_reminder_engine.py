"""TDD — reminder_engine.py (Sprint 2 Session 13bis).

8 tests couvrant :
- Génération relance polite (0 précédents)
- Génération relance firm (1 envoyée ≥ 7 jours)
- Génération relance escalation (2+ envoyées ≥ 7 jours)
- Idempotence : pas de doublon si pending existant
- Contact manquant → needs_contact_info=True
- Anomalie résolue → skippée silencieusement
- Cross-mandant : isolation stricte
- Audit log créé pour chaque relance générée
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from fiduciaire_worker.audit_log import init_audit_schema
from fiduciaire_worker.missing_docs_detector import (
    ANOMALIES_SCHEMA,
    TYPE_VAT_NO_EVIDENCE,
    init_anomalies_schema,
)
from fiduciaire_worker.reminder_engine import (
    REMINDERS_SCHEMA,
    generate_reminders,
    init_reminders_schema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_anomalies_schema(conn)
    init_audit_schema(conn)
    init_reminders_schema(conn)
    return conn


def _insert_anomaly(
    conn: sqlite3.Connection,
    cabinet_id: str,
    client_id: str,
    state: str = "open",
    anom_type: str = TYPE_VAT_NO_EVIDENCE,
    subject_entity_id: str = "entry-42",
) -> int:
    details = {"vat_code": "8.1", "amount": 150.0, "vendor": "Fournitures SA"}
    cur = conn.execute(
        """INSERT INTO anomalies
           (cabinet_id, client_id, type, severity, state,
            subject_entity_type, subject_entity_id, details_json)
           VALUES (?, ?, ?, 'warning', ?, 'accounting_entry', ?, ?)""",
        (cabinet_id, client_id, anom_type, state, subject_entity_id,
         json.dumps(details)),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _insert_sent_reminder(
    conn: sqlite3.Connection,
    cabinet_id: str,
    client_id: str,
    anomaly_id: int,
    level: str,
    days_ago: int,
) -> None:
    sent_at = (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        """INSERT INTO reminders
           (cabinet_id, client_id, anomaly_id, level, subject,
            body_draft, status, sent_at)
           VALUES (?, ?, ?, ?, 'Objet test', 'Corps test', 'sent', ?)""",
        (cabinet_id, client_id, anomaly_id, level, sent_at),
    )
    conn.commit()


_LLM_RESPONSE = json.dumps({
    "subject": "Pièce manquante — Facture Fournitures SA",
    "body": "Bonjour,\n\nNous attendons la facture.",
})


def _mock_llm(prompt: str) -> str:
    return _LLM_RESPONSE


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateReminders:

    def test_polite_on_first_reminder(self):
        """Anomalie sans relance précédente → niveau polite."""
        conn = _make_conn()
        anom_id = _insert_anomaly(conn, "cab-01", "client-A")

        ids = generate_reminders("cab-01", "client-A", conn, llm_caller=_mock_llm)

        assert len(ids) == 1
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (ids[0],)
        ).fetchone()
        assert row["level"] == "polite"
        assert row["status"] == "pending"
        assert row["anomaly_id"] == anom_id

    def test_firm_after_one_sent_7_days_ago(self):
        """1 relance polite envoyée il y a 7 jours → niveau firm."""
        conn = _make_conn()
        anom_id = _insert_anomaly(conn, "cab-01", "client-A")
        _insert_sent_reminder(conn, "cab-01", "client-A", anom_id, "polite", days_ago=7)

        ids = generate_reminders("cab-01", "client-A", conn, llm_caller=_mock_llm)

        assert len(ids) == 1
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (ids[0],)
        ).fetchone()
        assert row["level"] == "firm"

    def test_escalation_after_two_sent(self):
        """2 relances envoyées, dernière ≥ 7 jours → niveau escalation."""
        conn = _make_conn()
        anom_id = _insert_anomaly(conn, "cab-01", "client-A")
        _insert_sent_reminder(conn, "cab-01", "client-A", anom_id, "polite", days_ago=14)
        _insert_sent_reminder(conn, "cab-01", "client-A", anom_id, "firm", days_ago=7)

        ids = generate_reminders("cab-01", "client-A", conn, llm_caller=_mock_llm)

        assert len(ids) == 1
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (ids[0],)
        ).fetchone()
        assert row["level"] == "escalation"

    def test_idempotent_no_duplicate_if_pending_exists(self):
        """Ne crée pas de 2ème relance si une pending existe déjà pour l'anomalie."""
        conn = _make_conn()
        anom_id = _insert_anomaly(conn, "cab-01", "client-A")
        # Insérer manuellement une relance pending existante
        conn.execute(
            """INSERT INTO reminders
               (cabinet_id, client_id, anomaly_id, level, subject,
                body_draft, status)
               VALUES (?, ?, ?, 'polite', 'Objet', 'Corps', 'pending')""",
            ("cab-01", "client-A", anom_id),
        )
        conn.commit()

        ids = generate_reminders("cab-01", "client-A", conn, llm_caller=_mock_llm)

        assert ids == [], "Aucun nouvel ID attendu — relance pending déjà en place"
        count = conn.execute(
            "SELECT COUNT(*) FROM reminders WHERE anomaly_id = ?", (anom_id,)
        ).fetchone()[0]
        assert count == 1

    def test_resolved_anomaly_skipped(self):
        """Anomalie résolue → aucune relance générée."""
        conn = _make_conn()
        _insert_anomaly(conn, "cab-01", "client-A", state="resolved")

        ids = generate_reminders("cab-01", "client-A", conn, llm_caller=_mock_llm)

        assert ids == []

    def test_missing_contact_sets_needs_contact_info(self):
        """Quand le contact est introuvable → needs_contact_info=1, contact_email NULL."""
        conn = _make_conn()
        _insert_anomaly(conn, "cab-01", "client-no-contact")

        ids = generate_reminders(
            "cab-01", "client-no-contact", conn, llm_caller=_mock_llm
        )

        assert len(ids) == 1
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (ids[0],)
        ).fetchone()
        assert row["needs_contact_info"] == 1
        assert row["contact_email"] is None

    def test_cross_mandant_isolation(self):
        """Relances cabinet-A ne voient pas les relances de cabinet-B."""
        conn = _make_conn()
        anom_a = _insert_anomaly(conn, "cab-A", "client-1", subject_entity_id="entry-10")
        anom_b = _insert_anomaly(conn, "cab-B", "client-1", subject_entity_id="entry-10")
        # cabinet-B a déjà 2 relances envoyées
        _insert_sent_reminder(conn, "cab-B", "client-1", anom_b, "polite", days_ago=14)
        _insert_sent_reminder(conn, "cab-B", "client-1", anom_b, "firm", days_ago=7)

        ids_a = generate_reminders("cab-A", "client-1", conn, llm_caller=_mock_llm)

        assert len(ids_a) == 1
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (ids_a[0],)
        ).fetchone()
        assert row["level"] == "polite", "cabinet-A ne doit pas hériter du niveau de cabinet-B"
        assert row["cabinet_id"] == "cab-A"

    def test_audit_log_created_for_each_reminder(self):
        """Chaque relance créée génère 1 entrée audit (action=reminder_created)."""
        conn = _make_conn()
        _insert_anomaly(conn, "cab-01", "client-A", subject_entity_id="entry-1")
        _insert_anomaly(conn, "cab-01", "client-A", subject_entity_id="entry-2")

        ids = generate_reminders("cab-01", "client-A", conn, llm_caller=_mock_llm)

        assert len(ids) == 2
        audit_rows = conn.execute(
            "SELECT * FROM audit_log WHERE cabinet_id = ? AND action = 'reminder_created'",
            ("cab-01",),
        ).fetchall()
        assert len(audit_rows) == 2
