"""TDD — worker/scripts/send_reminder.py (Sprint 2 Session 13ter).

4 tests subprocess (black-box) :
- JSON valide ok:true en dry-run (chemin nominal)
- JSON erreur ok:false si SMTP_PASS_ENC manquant (ConfigError)
- JSON erreur si reminder pas en status='approved'
- JSON erreur si cabinet_id incorrect (cross-mandant)

Le script sort uniquement du JSON sur stdout, les logs vont sur stderr.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "worker" / "scripts" / "send_reminder.py"
PYTHON = sys.executable  # venv python


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path) -> tuple[Path, int]:
    """Crée une DB temporaire avec un reminder approved. Retourne (db_path, rid)."""
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA journal_mode = WAL;
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
            resolved_at TEXT, resolved_by TEXT, resolution_reason TEXT,
            UNIQUE (cabinet_id, client_id, type, subject_entity_id)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cabinet_id TEXT NOT NULL,
            user_id TEXT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            before_json TEXT, after_json TEXT,
            prev_hash TEXT NOT NULL DEFAULT '',
            current_hash TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cabinet_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            anomaly_id INTEGER NOT NULL,
            level TEXT NOT NULL CHECK(level IN ('polite', 'firm', 'escalation')),
            contact_name TEXT,
            contact_email TEXT,
            needs_contact_info INTEGER NOT NULL DEFAULT 0,
            subject TEXT NOT NULL,
            body_draft TEXT NOT NULL,
            body_final TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'approved', 'sent', 'skipped', 'failed')),
            skip_reason TEXT,
            sent_at TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    anom_id = conn.execute(
        """INSERT INTO anomalies
           (cabinet_id, client_id, type, state, subject_entity_type, subject_entity_id, details_json)
           VALUES ('cab-01', 'client-A', 'vat_no_evidence', 'open', 'accounting_entry', 'entry-1', '{}')"""
    ).lastrowid
    rid = conn.execute(
        """INSERT INTO reminders
           (cabinet_id, client_id, anomaly_id, level, contact_email,
            subject, body_draft, status)
           VALUES ('cab-01', 'client-A', ?, 'polite', 'client@example.ch',
                   'Pièce manquante', 'Bonjour,\n\nVeuillez envoyer la facture.', 'approved')""",
        (anom_id,),
    ).lastrowid
    conn.commit()
    conn.close()
    return db_path, rid


def _base_env(dry_run: bool = True, pass_enc: str | None = "dummy-pass") -> dict:
    """Variables d'environnement minimales pour les tests."""
    env = {**os.environ}
    env["FIDUCIAIRE_ENCRYPTION_DISABLED"] = "true"
    env["SMTP_DRY_RUN"] = "true" if dry_run else "false"
    env["SMTP_HOST"] = "mail.test.ch"
    env["SMTP_PORT"] = "587"
    env["SMTP_USER"] = "test@cabinet.ch"
    env["SMTP_FROM"] = "test@cabinet.ch"
    if pass_enc is not None:
        env["SMTP_PASS_ENC"] = pass_enc
    else:
        env.pop("SMTP_PASS_ENC", None)
    return env


def _run_script(db_path: Path, rid: int, cabinet_id: str = "cab-01",
                env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            PYTHON, str(SCRIPT),
            "--reminder-id", str(rid),
            "--cabinet-id", cabinet_id,
            "--db", str(db_path),
        ],
        capture_output=True,
        text=True,
        env=env or _base_env(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSendReminderScript:

    def test_dry_run_outputs_ok_json(self, tmp_path):
        """Dry-run nominal : JSON ok:true, status:sent, dry_run:true."""
        db_path, rid = _make_db(tmp_path)
        result = _run_script(db_path, rid, env=_base_env(dry_run=True))

        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout.strip())
        assert data["ok"] is True
        assert data["reminder_id"] == rid
        assert data["status"] == "sent"
        assert data["dry_run"] is True
        assert data.get("sent_at") is not None

    def test_smtp_config_error_outputs_error_json(self, tmp_path):
        """SMTP_PASS_ENC absent → ConfigError → JSON ok:false, exit 1."""
        db_path, rid = _make_db(tmp_path)
        env = _base_env(pass_enc=None)  # SMTP_PASS_ENC absent
        result = _run_script(db_path, rid, env=env)

        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["ok"] is False
        assert data["reminder_id"] == rid
        assert "SMTP_PASS_ENC" in data["error"] or "config" in data["error"].lower()

    def test_not_approved_exits_error(self, tmp_path):
        """Status pending → JSON ok:false + exit 1 (sans appel SMTP)."""
        db_path, _ = _make_db(tmp_path)
        # Insérer un reminder pending séparé
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        anom_id = conn.execute(
            """INSERT INTO anomalies
               (cabinet_id, client_id, type, state, subject_entity_type, subject_entity_id, details_json)
               VALUES ('cab-01', 'client-A', 'vat_no_evidence', 'open', 'accounting_entry', 'entry-2', '{}')"""
        ).lastrowid
        pending_rid = conn.execute(
            """INSERT INTO reminders
               (cabinet_id, client_id, anomaly_id, level, subject, body_draft, status)
               VALUES ('cab-01', 'client-A', ?, 'polite', 'Objet', 'Corps', 'pending')""",
            (anom_id,),
        ).lastrowid
        conn.commit()
        conn.close()

        result = _run_script(db_path, pending_rid, env=_base_env())

        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["ok"] is False
        assert "approved" in data["error"].lower() or "pending" in data["error"].lower()

    def test_cross_cabinet_exits_error(self, tmp_path):
        """Reminder de cab-01 demandé avec cabinet-id=cab-99 → JSON ok:false, exit 1."""
        db_path, rid = _make_db(tmp_path)
        result = _run_script(db_path, rid, cabinet_id="cab-99", env=_base_env())

        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["ok"] is False
        assert "introuvable" in data["error"].lower() or "cabinet" in data["error"].lower()
