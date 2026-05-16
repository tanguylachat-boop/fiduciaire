"""TDD — smtp_client.py (Sprint 2 Session 13bis).

7 tests couvrant :
- Dry-run : email loggué, non envoyé, status=sent
- Envoi live : smtplib.SMTP appelé avec bons paramètres
- Mot de passe jamais loggué (caplog)
- SMTP_PASS_ENC manquant → ConfigError
- Relance non-approved → ValueError
- Échec SMTP → status=failed + error_message stocké
- Audit log créé sur chaque tentative d'envoi
"""

from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from fiduciaire_worker.audit_log import init_audit_schema
from fiduciaire_worker.missing_docs_detector import (
    init_anomalies_schema,
    TYPE_VAT_NO_EVIDENCE,
)
from fiduciaire_worker.reminder_engine import (
    init_reminders_schema,
)
from fiduciaire_worker.smtp_client import (
    ConfigError,
    send_reminder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_SMTP_HOST = "mail.test.ch"
FAKE_SMTP_PORT = 587
FAKE_SMTP_USER = "relances@cabinet.ch"
FAKE_SMTP_PASS = "secret123"


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")  # No anomalies FK in test
    init_anomalies_schema(conn)
    init_audit_schema(conn)
    init_reminders_schema(conn)
    return conn


def _insert_reminder(
    conn: sqlite3.Connection,
    status: str = "approved",
    contact_email: str = "client@example.ch",
    contact_name: str = "Jean Dupont",
    subject: str = "Pièce manquante",
    body: str = "Bonjour Jean,\n\nVeuillez nous envoyer la facture.",
    cabinet_id: str = "cab-01",
    client_id: str = "client-A",
    body_final: str | None = None,
) -> int:
    # Insert anomaly first
    conn.execute(
        """INSERT INTO anomalies
           (cabinet_id, client_id, type, severity, state,
            subject_entity_type, subject_entity_id, details_json)
           VALUES (?, ?, ?, 'warning', 'open', 'accounting_entry', 'entry-1', '{}')""",
        (cabinet_id, client_id, TYPE_VAT_NO_EVIDENCE),
    )
    anom_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    cur = conn.execute(
        """INSERT INTO reminders
           (cabinet_id, client_id, anomaly_id, level, contact_name,
            contact_email, subject, body_draft, body_final, status)
           VALUES (?, ?, ?, 'polite', ?, ?, ?, ?, ?, ?)""",
        (cabinet_id, client_id, anom_id, contact_name, contact_email,
         subject, body, body_final, status),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _env_vars(monkeypatch, dry_run: bool = True, pass_enc: str | None = "dummy") -> None:
    monkeypatch.setenv("SMTP_HOST", FAKE_SMTP_HOST)
    monkeypatch.setenv("SMTP_PORT", str(FAKE_SMTP_PORT))
    monkeypatch.setenv("SMTP_USER", FAKE_SMTP_USER)
    monkeypatch.setenv("SMTP_FROM", FAKE_SMTP_USER)
    if pass_enc is not None:
        monkeypatch.setenv("SMTP_PASS_ENC", pass_enc)
    monkeypatch.setenv("SMTP_DRY_RUN", "true" if dry_run else "false")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_DISABLED", "true")
    # With ENCRYPTION_DISABLED=true, SMTP_PASS_ENC is used as-is
    if pass_enc is not None:
        monkeypatch.setenv("SMTP_PASS_ENC", FAKE_SMTP_PASS)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSendReminder:

    def test_dry_run_logs_and_marks_sent(self, monkeypatch, caplog):
        """Dry-run : email loggué, status=sent, smtplib jamais appelé."""
        conn = _make_conn()
        rid = _insert_reminder(conn)
        _env_vars(monkeypatch, dry_run=True)

        import logging
        with caplog.at_level(logging.INFO, logger="fiduciaire.smtp_client"):
            with patch("smtplib.SMTP") as mock_smtp:
                result = send_reminder(rid, conn)

        mock_smtp.assert_not_called()
        assert result is True

        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (rid,)).fetchone()
        assert row["status"] == "sent"
        assert row["sent_at"] is not None
        assert "dry_run" in caplog.text.lower() or "DRY" in caplog.text

    def test_live_send_calls_smtplib(self, monkeypatch):
        """Envoi live : smtplib.SMTP appelé, email envoyé, status=sent."""
        conn = _make_conn()
        rid = _insert_reminder(conn)
        _env_vars(monkeypatch, dry_run=False)

        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", mock_smtp_class):
            result = send_reminder(rid, conn)

        assert result is True
        mock_smtp_class.assert_called_once()
        mock_smtp_instance.sendmail.assert_called_once()

        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (rid,)).fetchone()
        assert row["status"] == "sent"

    def test_password_never_logged(self, monkeypatch, caplog):
        """Le mot de passe SMTP ne doit jamais apparaître dans les logs."""
        conn = _make_conn()
        rid = _insert_reminder(conn)
        _env_vars(monkeypatch, dry_run=True)

        import logging
        with caplog.at_level(logging.DEBUG, logger="fiduciaire"):
            with patch("smtplib.SMTP"):
                send_reminder(rid, conn)

        assert FAKE_SMTP_PASS not in caplog.text, (
            f"Mot de passe '{FAKE_SMTP_PASS}' trouvé dans les logs !"
        )

    def test_missing_smtp_pass_enc_raises_config_error(self, monkeypatch):
        """SMTP_PASS_ENC absent → ConfigError avant toute tentative."""
        conn = _make_conn()
        rid = _insert_reminder(conn)
        _env_vars(monkeypatch, dry_run=False, pass_enc=None)
        monkeypatch.delenv("SMTP_PASS_ENC", raising=False)

        with pytest.raises(ConfigError, match="SMTP_PASS_ENC"):
            send_reminder(rid, conn)

    def test_non_approved_status_raises_value_error(self, monkeypatch):
        """Relance avec status != approved → ValueError."""
        conn = _make_conn()
        rid = _insert_reminder(conn, status="pending")
        _env_vars(monkeypatch, dry_run=True)

        with pytest.raises(ValueError, match="approved"):
            send_reminder(rid, conn)

    def test_smtp_failure_marks_failed(self, monkeypatch):
        """Échec SMTP → status=failed + error_message stocké."""
        conn = _make_conn()
        rid = _insert_reminder(conn)
        _env_vars(monkeypatch, dry_run=False)

        import smtplib
        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.sendmail.side_effect = smtplib.SMTPException("Connection refused")

        with patch("smtplib.SMTP", mock_smtp_class):
            result = send_reminder(rid, conn)

        assert result is False
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (rid,)).fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] is not None
        assert "refused" in row["error_message"].lower() or "Connection" in row["error_message"]

    def test_audit_log_created_on_send(self, monkeypatch):
        """Audit log enregistré sur chaque envoi (succès ou dry-run)."""
        conn = _make_conn()
        rid = _insert_reminder(conn)
        _env_vars(monkeypatch, dry_run=True)

        with patch("smtplib.SMTP"):
            send_reminder(rid, conn)

        audit = conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'reminder' AND action = 'reminder_sent'",
        ).fetchall()
        assert len(audit) == 1
        assert int(audit[0]["entity_id"]) == rid
