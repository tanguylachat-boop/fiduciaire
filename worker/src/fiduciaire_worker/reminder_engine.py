"""Moteur de relances clients — Sprint 2 §reminder.

Lit les anomalies ouvertes, détermine le niveau d'escalade (polite/firm/
escalation), génère un brouillon via Ollama (LLM local), stocke en DB
avec status=pending. Jamais d'envoi automatique.

Multi-mandant strict : cabinet_id + client_id sur chaque requête.
Idempotence : skip si relance pending existe déjà pour l'anomalie.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

from fiduciaire_worker.audit_log import init_audit_schema, log_audit_event
from fiduciaire_worker.missing_docs_detector import (
    STATE_OPEN,
    Anomaly,
    init_anomalies_schema,
    list_open_anomalies,
)

_log = logging.getLogger("fiduciaire.reminder_engine")

TEMPLATES_DIR = Path(__file__).parent / "templates" / "reminders"

LEVEL_POLITE = "polite"
LEVEL_FIRM = "firm"
LEVEL_ESCALATION = "escalation"

REMINDERS_SCHEMA = """
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

CREATE INDEX IF NOT EXISTS idx_reminders_cabinet_client
    ON reminders (cabinet_id, client_id, status);
CREATE INDEX IF NOT EXISTS idx_reminders_anomaly
    ON reminders (anomaly_id, status);
"""

_ESCALATION_DELAY_DAYS = 7

_OLLAMA_ENDPOINT = "http://localhost:11434"
_OLLAMA_MODEL = "mistral-small"
_OLLAMA_TIMEOUT_S = 30


def init_reminders_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(REMINDERS_SCHEMA)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sent_reminders_for_anomaly(
    conn: sqlite3.Connection, cabinet_id: str, anomaly_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM reminders
           WHERE cabinet_id = ? AND anomaly_id = ?
             AND status = 'sent'
           ORDER BY sent_at ASC""",
        (cabinet_id, anomaly_id),
    ).fetchall()


def _has_pending_reminder(
    conn: sqlite3.Connection, cabinet_id: str, anomaly_id: int
) -> bool:
    row = conn.execute(
        """SELECT 1 FROM reminders
           WHERE cabinet_id = ? AND anomaly_id = ? AND status = 'pending'
           LIMIT 1""",
        (cabinet_id, anomaly_id),
    ).fetchone()
    return row is not None


def _determine_level(
    conn: sqlite3.Connection, cabinet_id: str, anomaly_id: int
) -> str | None:
    """Retourne le niveau ou None si trop tôt pour relancer."""
    sent = _sent_reminders_for_anomaly(conn, cabinet_id, anomaly_id)
    if not sent:
        return LEVEL_POLITE

    last_sent_at_str = sent[-1]["sent_at"]
    last_sent_at = datetime.fromisoformat(last_sent_at_str).replace(
        tzinfo=timezone.utc
    )
    elapsed = datetime.now(timezone.utc) - last_sent_at

    if elapsed < timedelta(days=_ESCALATION_DELAY_DAYS):
        return None  # Trop tôt

    if len(sent) == 1:
        return LEVEL_FIRM
    return LEVEL_ESCALATION


def _find_contact(
    conn: sqlite3.Connection, cabinet_id: str, client_id: str
) -> tuple[str | None, str | None]:
    """Retourne (contact_name, contact_email) ou (None, None) si introuvable."""
    row = conn.execute(
        """SELECT contact_name, contact_email FROM bexio_sync
           WHERE cabinet_id = ? AND client_id = ?
           LIMIT 1""",
        (cabinet_id, client_id),
    ).fetchone()
    if row:
        return row["contact_name"], row["contact_email"]
    return None, None


def _render_template(level: str, vars_: dict[str, str]) -> str:
    template_file = TEMPLATES_DIR / f"{level}_fr.md"
    text = template_file.read_text(encoding="utf-8")
    for key, value in vars_.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def _build_anomaly_context(anomaly: Anomaly) -> str:
    details = anomaly.details or {}
    vendor = details.get("vendor", anomaly.subject_entity_id)
    amount = details.get("amount")
    vat = details.get("vat_code")
    parts = [f"Document manquant pour {vendor}"]
    if amount:
        parts.append(f"montant {amount:.2f} CHF")
    if vat:
        parts.append(f"TVA {vat}%")
    return " — ".join(parts) + "."


def _type_to_label(anom_type: str) -> str:
    mapping = {
        "vat_no_evidence": "justificatif TVA",
        "payment_without_invoice": "facture fournisseur",
        "unpaid_invoice_overdue": "facture impayée",
        "potential_duplicate": "doublon potentiel",
    }
    return mapping.get(anom_type, anom_type)


def _call_ollama(prompt: str) -> str:
    payload = {
        "model": _OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 512},
    }
    r = httpx.post(
        f"{_OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=_OLLAMA_TIMEOUT_S
    )
    r.raise_for_status()
    return r.json().get("response", "")


def _generate_draft(
    template_text: str,
    llm_caller: Callable[[str], str] | None,
) -> tuple[str, str]:
    """Retourne (subject, body_draft)."""
    caller = llm_caller or _call_ollama

    # Extraire la ligne Objet: du template comme sujet par défaut
    default_subject = ""
    default_body_lines = []
    for line in template_text.splitlines():
        if line.startswith("Objet:"):
            default_subject = line.removeprefix("Objet:").strip()
        else:
            default_body_lines.append(line)
    default_body = "\n".join(default_body_lines).strip()

    prompt = (
        "Tu es un assistant fiduciaire suisse. "
        "Améliore légèrement ce brouillon d'email professionnel en gardant le même sens. "
        "Retourne UNIQUEMENT un JSON avec les clés 'subject' et 'body'. "
        "Ne change pas le sens ou le ton.\n\n"
        f"BROUILLON:\n{template_text}"
    )

    try:
        raw = caller(prompt)
        data = json.loads(raw)
        subject = data.get("subject", default_subject) or default_subject
        body = data.get("body", default_body) or default_body
        return subject, body
    except (json.JSONDecodeError, Exception) as exc:
        _log.warning("LLM draft generation failed, using template fallback: %s", exc)
        return default_subject, default_body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_reminders(
    cabinet_id: str,
    client_id: str,
    conn: sqlite3.Connection,
    llm_caller: Callable[[str], str] | None = None,
) -> list[int]:
    """Génère des relances pending pour toutes les anomalies ouvertes.

    Retourne la liste des reminder IDs créés.
    Idempotent : skip si relance pending déjà présente pour l'anomalie.
    """
    anomalies = list_open_anomalies(conn, cabinet_id, client_id=client_id)
    if not anomalies:
        return []

    # Tenter de lire les contacts une fois pour le mandant
    contact_name: str | None = None
    contact_email: str | None = None
    needs_contact_info = True
    try:
        contact_name, contact_email = _find_contact(conn, cabinet_id, client_id)
        if contact_name or contact_email:
            needs_contact_info = False
    except Exception:
        pass

    created_ids: list[int] = []

    for anomaly in anomalies:
        if _has_pending_reminder(conn, cabinet_id, anomaly.id):
            _log.debug(
                "Skipping anomaly %d — pending reminder already exists", anomaly.id
            )
            continue

        level = _determine_level(conn, cabinet_id, anomaly.id)
        if level is None:
            _log.debug(
                "Skipping anomaly %d — escalation delay not elapsed", anomaly.id
            )
            continue

        # Construire les variables template
        vars_ = {
            "contact_name": contact_name or "Madame, Monsieur",
            "document_type": _type_to_label(anomaly.type),
            "vendor_or_client_name": anomaly.subject_entity_id,
            "anomaly_context": _build_anomaly_context(anomaly),
            "cabinet_signature": "Votre fiduciaire",
        }

        template_text = _render_template(level, vars_)
        subject, body_draft = _generate_draft(template_text, llm_caller)

        cur = conn.execute(
            """INSERT INTO reminders
               (cabinet_id, client_id, anomaly_id, level,
                contact_name, contact_email, needs_contact_info,
                subject, body_draft, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                cabinet_id, client_id, anomaly.id, level,
                contact_name, contact_email,
                1 if needs_contact_info else 0,
                subject, body_draft,
            ),
        )
        reminder_id = cur.lastrowid
        conn.commit()

        log_audit_event(
            conn,
            cabinet_id=cabinet_id,
            entity_type="reminder",
            entity_id=reminder_id,
            action="reminder_created",
            after={
                "anomaly_id": anomaly.id,
                "level": level,
                "client_id": client_id,
            },
        )

        created_ids.append(reminder_id)
        _log.info(
            "Created reminder %d (level=%s) for anomaly %d / cabinet=%s client=%s",
            reminder_id, level, anomaly.id, cabinet_id, client_id,
        )

    return created_ids
