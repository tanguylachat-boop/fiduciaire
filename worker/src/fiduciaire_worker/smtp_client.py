"""Client SMTP pour envoi des relances clients — Sprint 2 §smtp.

Lit les relances approuvées en DB, envoie via SMTP standard (Infomaniak,
Swisscom, etc.). Mot de passe chiffré Fernet (SMTP_PASS_ENC).
SMTP_DRY_RUN=true par défaut : log sans envoyer.

Jamais de mot de passe en clair dans les logs.
"""

from __future__ import annotations

import logging
import os
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.mime.text import MIMEText

from fiduciaire_worker.audit_log import log_audit_event
from fiduciaire_worker.encryption import decrypt_column_value

_log = logging.getLogger("fiduciaire.smtp_client")


class ConfigError(Exception):
    """Configuration SMTP manquante ou invalide."""


def _get_smtp_config() -> dict[str, str | int]:
    """Lit et valide la configuration SMTP depuis les variables d'environnement."""
    host = os.environ.get("SMTP_HOST", "")
    port_str = os.environ.get("SMTP_PORT", "587")
    user = os.environ.get("SMTP_USER", "")
    from_addr = os.environ.get("SMTP_FROM", user)
    pass_enc = os.environ.get("SMTP_PASS_ENC")

    if not pass_enc:
        raise ConfigError(
            "SMTP_PASS_ENC manquant — configurez le mot de passe SMTP chiffré Fernet"
        )
    if not host:
        raise ConfigError("SMTP_HOST manquant")
    if not user:
        raise ConfigError("SMTP_USER manquant")

    try:
        port = int(port_str)
    except ValueError:
        raise ConfigError(f"SMTP_PORT invalide : {port_str!r}")

    return {
        "host": host,
        "port": port,
        "user": user,
        "from_addr": from_addr,
        "pass_enc": pass_enc,
    }


def _decrypt_smtp_pass(pass_enc: str, cabinet_id: str) -> str:
    """Déchiffre le mot de passe SMTP. Ne le logue jamais."""
    decrypted = decrypt_column_value(pass_enc, cabinet_id)
    if not decrypted:
        raise ConfigError("Impossible de déchiffrer SMTP_PASS_ENC")
    return decrypted


def _is_dry_run() -> bool:
    return os.environ.get("SMTP_DRY_RUN", "true").lower() in ("true", "1", "yes")


def _build_mime_message(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
) -> MIMEText:
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    return msg


def send_reminder(
    reminder_id: int,
    conn: sqlite3.Connection,
    dry_run: bool | None = None,
) -> bool:
    """Envoie la relance approuvée via SMTP.

    Args:
        reminder_id: ID de la relance en DB (status doit être 'approved').
        conn: Connexion SQLite (reminders + audit schemas initialisés).
        dry_run: Override SMTP_DRY_RUN si fourni explicitement.

    Returns:
        True si envoi réussi (ou dry-run), False si échec.

    Raises:
        ValueError: si la relance n'est pas en status 'approved'.
        ConfigError: si la configuration SMTP est incomplète.
    """
    row = conn.execute(
        "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Relance {reminder_id} introuvable")

    if row["status"] != "approved":
        raise ValueError(
            f"La relance {reminder_id} n'est pas en status 'approved' "
            f"(status actuel : {row['status']!r})"
        )

    cabinet_id: str = row["cabinet_id"]
    cfg = _get_smtp_config()  # Peut lever ConfigError

    use_dry_run = _is_dry_run() if dry_run is None else dry_run

    body = row["body_final"] or row["body_draft"]
    subject = row["subject"]
    to_email = row["contact_email"] or ""
    from_addr = str(cfg["from_addr"])

    if not to_email:
        _log.warning(
            "Reminder %d has no contact_email — cannot send (needs_contact_info=%s)",
            reminder_id, row["needs_contact_info"],
        )

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    if use_dry_run:
        _log.info(
            "[DRY RUN] reminder=%d to=%s subject=%r (not sent)",
            reminder_id, to_email, subject,
        )
        conn.execute(
            "UPDATE reminders SET status='sent', sent_at=? WHERE id=?",
            (now_str, reminder_id),
        )
        conn.commit()
        log_audit_event(
            conn,
            cabinet_id=cabinet_id,
            entity_type="reminder",
            entity_id=reminder_id,
            action="reminder_sent",
            after={"dry_run": True, "to": to_email, "subject": subject},
        )
        return True

    # Envoi live
    smtp_pass = _decrypt_smtp_pass(str(cfg["pass_enc"]), cabinet_id)
    msg = _build_mime_message(from_addr, to_email, subject, body)

    try:
        with smtplib.SMTP(str(cfg["host"]), int(cfg["port"])) as server:
            server.starttls()
            server.login(str(cfg["user"]), smtp_pass)
            server.sendmail(from_addr, [to_email], msg.as_string())

        conn.execute(
            "UPDATE reminders SET status='sent', sent_at=? WHERE id=?",
            (now_str, reminder_id),
        )
        conn.commit()
        log_audit_event(
            conn,
            cabinet_id=cabinet_id,
            entity_type="reminder",
            entity_id=reminder_id,
            action="reminder_sent",
            after={"dry_run": False, "to": to_email, "subject": subject},
        )
        _log.info("Reminder %d sent to %s", reminder_id, to_email)
        return True

    except smtplib.SMTPException as exc:
        error_msg = str(exc)
        _log.error("SMTP error for reminder %d: %s", reminder_id, error_msg)
        conn.execute(
            "UPDATE reminders SET status='failed', error_message=? WHERE id=?",
            (error_msg, reminder_id),
        )
        conn.commit()
        log_audit_event(
            conn,
            cabinet_id=cabinet_id,
            entity_type="reminder",
            entity_id=reminder_id,
            action="reminder_send_failed",
            after={"error": error_msg},
        )
        return False
