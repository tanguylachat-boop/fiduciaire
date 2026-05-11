"""Orchestrateur IMAP fetch — Phase B.

Wire `email_parser` + `imap_client` + `pipeline.process_document` end-to-end :
poll une boîte IMAP cabinet, dedup Message-ID, persiste email_messages /
email_attachments en DB, route chaque PJ supportée vers le pipeline existant.

Multi-mandant first-class : toutes les opérations filtrent par `cabinet_id`,
zéro fuite cross-mandant. Idempotent : 2× le même fetch ne crée pas de
doublons. Mode dry-run : aucune écriture DB, aucun appel pipeline,
aucun mark_seen — pour audit/debug avant prod.

Cf docs/specs/imap-fetch.md §3.2 data flow Phase B.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import db
from .config import Config
from .email_parser import (
    ParsedAttachment,
    ParsedEmail,
    is_supported_pipeline,
    parse_email_bytes,
)
from .imap_client import ImapClient, ImapCredentials

_log = logging.getLogger("fiduciaire.imap_fetch")

MAX_ATTACHMENT_SIZE_DEFAULT = 50 * 1024 * 1024  # 50 MB

# Statuts MessageOutcome
MSG_STATUS_INGESTED = "ingested"
MSG_STATUS_DUPLICATE = "duplicate"
MSG_STATUS_FILTERED_SENDER = "filtered_sender"
MSG_STATUS_PGP = "pgp"
MSG_STATUS_SMIME = "smime"
MSG_STATUS_NO_ATTACHMENT = "no_attachment"

_EMAIL_FROM_RE = re.compile(r"<([^>]+)>")

ProcessDocumentFn = Callable[..., Any]
"""Signature: (source: Path, config: Config, conn: sqlite3.Connection,
delete_inbox: bool = False) -> PipelineOutcome. Injectable pour tests."""

ImapFactory = Callable[..., Any]
"""Signature factory imaplib.IMAP4_SSL. Injectable pour tests."""


# --- Dataclasses --------------------------------------------------------------


@dataclass
class ImapFetchFilters:
    """Filtres optionnels appliqués par cabinet.

    sender_allowlist:
        - `None` (défaut) : aucun filtre, tout passe.
        - `[]` (liste vide) : explicit deny-all (rare, utile pour pause).
        - `["foo@bar.com", "@swisscom.ch"]` : exact email OU domain wildcard.
    """
    sender_allowlist: list[str] | None = None

    def matches_sender(self, from_addr: str | None) -> bool:
        if self.sender_allowlist is None:
            return True
        if not from_addr:
            return False
        # Extrait l'email depuis "Foo <foo@bar.com>" ou retourne tel quel.
        m = _EMAIL_FROM_RE.search(from_addr)
        addr = (m.group(1) if m else from_addr).strip().lower()
        for allow in self.sender_allowlist:
            allow_lc = allow.strip().lower()
            if not allow_lc:
                continue
            if allow_lc.startswith("@"):
                if addr.endswith(allow_lc):
                    return True
            elif addr == allow_lc:
                return True
        return False


@dataclass
class MessageOutcome:
    """Résultat de traitement d'un email."""
    uid: int
    message_id: str
    status: str  # MSG_STATUS_*
    encryption_status: str
    email_id: int | None = None  # row id email_messages, None si dry-run/filtered
    from_addr: str | None = None
    subject: str | None = None
    attachments_processed: int = 0
    attachments_unsupported: int = 0
    attachments_failed: int = 0
    attachments_oversized: int = 0
    attachments_empty: int = 0
    attachments_encrypted_skipped: int = 0
    error: str | None = None


@dataclass
class ImapFetchSummary:
    """Bilan d'un run de fetch."""
    cabinet_id: str
    folder: str
    uidvalidity: int
    new_messages: int = 0
    duplicates: int = 0
    filtered_sender: int = 0
    pgp_skipped: int = 0
    smime_skipped: int = 0
    no_attachment: int = 0
    attachments_total: int = 0
    attachments_processed: int = 0
    attachments_unsupported: int = 0
    attachments_failed: int = 0
    attachments_oversized: int = 0
    attachments_empty: int = 0
    last_uid_seen: int = 0
    dry_run: bool = False
    duration_s: float = 0.0
    by_message: list[MessageOutcome] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# --- DB helpers internes ------------------------------------------------------


def _load_fetch_state(
    conn: sqlite3.Connection, cabinet_id: str, folder: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM email_fetch_state WHERE cabinet_id=? AND folder=?",
        (cabinet_id, folder),
    ).fetchone()


def _upsert_fetch_state(
    conn: sqlite3.Connection,
    cabinet_id: str,
    folder: str,
    uidvalidity: int,
    last_uid_seen: int,
    status: str = "ok",
) -> None:
    conn.execute(
        """
        INSERT INTO email_fetch_state
          (cabinet_id, folder, uidvalidity, last_uid_seen, last_fetch_status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(cabinet_id, folder) DO UPDATE SET
          uidvalidity=excluded.uidvalidity,
          last_uid_seen=excluded.last_uid_seen,
          last_fetch_at=datetime('now'),
          last_fetch_status=excluded.last_fetch_status
        """,
        (cabinet_id, folder, uidvalidity, last_uid_seen, status),
    )


def _existing_email_id(
    conn: sqlite3.Connection, cabinet_id: str, message_id: str,
) -> int | None:
    row = conn.execute(
        "SELECT id FROM email_messages WHERE cabinet_id=? AND message_id=?",
        (cabinet_id, message_id),
    ).fetchone()
    return int(row["id"]) if row else None


def _insert_email_message(
    conn: sqlite3.Connection,
    cabinet_id: str,
    folder: str,
    uid: int,
    uidvalidity: int,
    parsed: ParsedEmail,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO email_messages
          (cabinet_id, folder, uid, uidvalidity, message_id, date_received,
           from_addr, to_addr, subject, body_excerpt, encryption_status,
           size_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cabinet_id, folder, uid, uidvalidity, parsed.message_id,
            parsed.date_received, parsed.from_addr, parsed.to_addr,
            parsed.subject, parsed.body_excerpt, parsed.encryption_status,
            parsed.size_bytes,
        ),
    )
    return int(cur.lastrowid)


def _insert_email_attachment(
    conn: sqlite3.Connection,
    email_id: int,
    att: ParsedAttachment,
    status: str,
    document_id: int | None = None,
    reason: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO email_attachments
          (email_id, filename, content_type, size_bytes, content_sha256,
           status, document_id, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            email_id, att.filename, att.content_type, att.size_bytes,
            att.content_sha256, status, document_id, reason,
        ),
    )


# --- Helpers staging ---------------------------------------------------------


def _save_staging(
    att: ParsedAttachment, staging_dir: Path,
) -> Path:
    """Sauve l'attachment dans staging_dir/<sha256>.<ext>.

    Le pipeline déduplique sur sha256 dans `archive/` — on peut donc
    réutiliser le sha comme nom de fichier staging.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(att.filename or "unnamed").suffix or ".bin"
    path = staging_dir / f"{att.content_sha256}{suffix}"
    if not path.exists():
        path.write_bytes(att.raw_bytes)
    return path


def _cleanup_staging(path: Path) -> None:
    """Best-effort, ne raise pas."""
    try:
        if path.exists():
            path.unlink()
    except Exception as exc:  # pragma: no cover — defensive
        _log.debug("staging cleanup failed for %s: %s", path, exc)


# --- Core orchestrator -------------------------------------------------------


def fetch_emails(
    *,
    cabinet_id: str,
    creds: ImapCredentials,
    conn: sqlite3.Connection,
    config: Config,
    folder: str = "INBOX",
    limit: int | None = None,
    dry_run: bool = False,
    mark_seen: bool = False,
    filters: ImapFetchFilters | None = None,
    staging_dir: Path | None = None,
    max_attachment_size_bytes: int = MAX_ATTACHMENT_SIZE_DEFAULT,
    imap_factory: ImapFactory | None = None,
    process_document_fn: ProcessDocumentFn | None = None,
) -> ImapFetchSummary:
    """Poll IMAP cabinet + ingère pièces jointes via le pipeline existant.

    Voir docstring module + docs/specs/imap-fetch.md §3.2.
    """
    t0 = time.perf_counter()
    filters = filters or ImapFetchFilters()
    staging_dir = staging_dir or Path("data") / "imap-staging" / cabinet_id

    if process_document_fn is None:
        from .pipeline import process_document as _default_pipeline
        process_document_fn = _default_pipeline

    client = ImapClient(
        host=creds.host, port=creds.port, imap_factory=imap_factory,
    )
    client.connect(creds.user, creds.password)

    summary = ImapFetchSummary(
        cabinet_id=cabinet_id, folder=folder, uidvalidity=0, dry_run=dry_run,
    )

    try:
        uidvalidity, _exists = client.select_folder(folder)
        summary.uidvalidity = uidvalidity

        state_row = _load_fetch_state(conn, cabinet_id, folder)
        if state_row is None:
            last_uid_seen = 0
            full_rescan = False
        else:
            last_uid_seen = int(state_row["last_uid_seen"])
            full_rescan = state_row["uidvalidity"] != uidvalidity

        if full_rescan:
            _log.info(
                "UIDVALIDITY changed (%s → %s) for cabinet=%s folder=%s: full rescan",
                state_row["uidvalidity"] if state_row else None,
                uidvalidity, cabinet_id, folder,
            )
            uids = client.fetch_uids_above(0)
        else:
            uids = client.fetch_uids_above(last_uid_seen)

        if limit is not None:
            uids = uids[:limit]

        new_last_uid = last_uid_seen
        for uid in uids:
            outcome = _process_one(
                uid=uid,
                client=client,
                conn=conn,
                config=config,
                cabinet_id=cabinet_id,
                folder=folder,
                uidvalidity=uidvalidity,
                filters=filters,
                staging_dir=staging_dir,
                max_attachment_size_bytes=max_attachment_size_bytes,
                process_document_fn=process_document_fn,
                dry_run=dry_run,
            )
            summary.by_message.append(outcome)
            _accumulate(summary, outcome)

            if mark_seen and not dry_run and outcome.status in (
                MSG_STATUS_INGESTED, MSG_STATUS_NO_ATTACHMENT,
                MSG_STATUS_PGP, MSG_STATUS_SMIME, MSG_STATUS_DUPLICATE,
            ):
                try:
                    client.mark_seen(uid)
                except Exception as exc:
                    _log.warning("mark_seen failed for uid=%d: %s", uid, exc)
                    summary.errors.append(f"mark_seen uid={uid}: {exc}")

            if uid > new_last_uid:
                new_last_uid = uid

        # Persist fetch_state sauf dry_run
        if not dry_run:
            _upsert_fetch_state(
                conn, cabinet_id, folder, uidvalidity, new_last_uid, "ok",
            )
        summary.last_uid_seen = new_last_uid

    finally:
        client.close()

    summary.duration_s = time.perf_counter() - t0
    return summary


def _process_one(
    *,
    uid: int,
    client: ImapClient,
    conn: sqlite3.Connection,
    config: Config,
    cabinet_id: str,
    folder: str,
    uidvalidity: int,
    filters: ImapFetchFilters,
    staging_dir: Path,
    max_attachment_size_bytes: int,
    process_document_fn: ProcessDocumentFn,
    dry_run: bool,
) -> MessageOutcome:
    """Traite 1 message UID → MessageOutcome."""
    fetched = client.fetch_message(uid)
    parsed = parse_email_bytes(fetched.raw_bytes)

    outcome = MessageOutcome(
        uid=uid, message_id=parsed.message_id,
        status=MSG_STATUS_INGESTED,
        encryption_status=parsed.encryption_status,
        from_addr=parsed.from_addr, subject=parsed.subject,
    )

    # Filter sender allowlist
    if not filters.matches_sender(parsed.from_addr):
        outcome.status = MSG_STATUS_FILTERED_SENDER
        return outcome

    # Dedup Message-ID
    existing_id = _existing_email_id(conn, cabinet_id, parsed.message_id)
    if existing_id is not None:
        outcome.status = MSG_STATUS_DUPLICATE
        outcome.email_id = existing_id
        return outcome

    # PGP / SMIME : persiste l'email metadata mais 0 attachment
    if parsed.encryption_status == "pgp":
        if not dry_run:
            outcome.email_id = _insert_email_message(
                conn, cabinet_id, folder, uid, uidvalidity, parsed,
            )
        outcome.status = MSG_STATUS_PGP
        outcome.attachments_encrypted_skipped = 0  # rien à extraire
        return outcome
    if parsed.encryption_status == "smime":
        if not dry_run:
            outcome.email_id = _insert_email_message(
                conn, cabinet_id, folder, uid, uidvalidity, parsed,
            )
        outcome.status = MSG_STATUS_SMIME
        outcome.attachments_encrypted_skipped = 0
        return outcome

    # Plain email : INSERT email_messages
    if not dry_run:
        outcome.email_id = _insert_email_message(
            conn, cabinet_id, folder, uid, uidvalidity, parsed,
        )

    # No attachment ?
    if not parsed.attachments:
        outcome.status = MSG_STATUS_NO_ATTACHMENT
        return outcome

    # Iterate attachments
    for att in parsed.attachments:
        _handle_attachment(
            att=att, outcome=outcome, conn=conn, config=config,
            staging_dir=staging_dir,
            max_attachment_size_bytes=max_attachment_size_bytes,
            process_document_fn=process_document_fn, dry_run=dry_run,
        )

    return outcome


def _handle_attachment(
    *,
    att: ParsedAttachment,
    outcome: MessageOutcome,
    conn: sqlite3.Connection,
    config: Config,
    staging_dir: Path,
    max_attachment_size_bytes: int,
    process_document_fn: ProcessDocumentFn,
    dry_run: bool,
) -> None:
    """Traite 1 attachment + persiste email_attachments (sauf dry_run)."""

    # Empty
    if att.size_bytes == 0:
        outcome.attachments_empty += 1
        if not dry_run and outcome.email_id is not None:
            _insert_email_attachment(
                conn, outcome.email_id, att, db.EMAIL_ATT_STATUS_EMPTY,
                reason="0 bytes",
            )
        return

    # Oversized
    if att.size_bytes > max_attachment_size_bytes:
        outcome.attachments_oversized += 1
        if not dry_run and outcome.email_id is not None:
            _insert_email_attachment(
                conn, outcome.email_id, att, db.EMAIL_ATT_STATUS_OVERSIZED,
                reason=f"size={att.size_bytes} > max={max_attachment_size_bytes}",
            )
        return

    # Unsupported (pas un PDF / image)
    if not is_supported_pipeline(att.content_type, att.filename):
        outcome.attachments_unsupported += 1
        if not dry_run and outcome.email_id is not None:
            _insert_email_attachment(
                conn, outcome.email_id, att, db.EMAIL_ATT_STATUS_UNSUPPORTED,
                reason=f"content-type={att.content_type}",
            )
        return

    # Supported : save staging + pipeline
    if dry_run:
        # Pas d'IO, pas de pipeline.
        outcome.attachments_processed += 1
        return

    staging_path = _save_staging(att, staging_dir)
    try:
        result = process_document_fn(staging_path, config, conn, delete_inbox=False)
        doc_id = getattr(result, "doc_id", None)
        outcome.attachments_processed += 1
        if outcome.email_id is not None:
            _insert_email_attachment(
                conn, outcome.email_id, att,
                db.EMAIL_ATT_STATUS_PROCESSED, document_id=doc_id,
            )
    except Exception as exc:
        _log.warning(
            "process_document raised on %s: %s", staging_path.name, exc,
        )
        outcome.attachments_failed += 1
        if outcome.email_id is not None:
            _insert_email_attachment(
                conn, outcome.email_id, att,
                db.EMAIL_ATT_STATUS_FAILED,
                reason=f"{type(exc).__name__}: {exc}",
            )
    finally:
        _cleanup_staging(staging_path)


def _accumulate(summary: ImapFetchSummary, outcome: MessageOutcome) -> None:
    """Met à jour les compteurs du summary depuis 1 MessageOutcome."""
    if outcome.status == MSG_STATUS_DUPLICATE:
        summary.duplicates += 1
    elif outcome.status == MSG_STATUS_FILTERED_SENDER:
        summary.filtered_sender += 1
    elif outcome.status == MSG_STATUS_PGP:
        summary.new_messages += 1
        summary.pgp_skipped += 1
    elif outcome.status == MSG_STATUS_SMIME:
        summary.new_messages += 1
        summary.smime_skipped += 1
    elif outcome.status == MSG_STATUS_NO_ATTACHMENT:
        summary.new_messages += 1
        summary.no_attachment += 1
    elif outcome.status == MSG_STATUS_INGESTED:
        summary.new_messages += 1

    summary.attachments_total += (
        outcome.attachments_processed
        + outcome.attachments_unsupported
        + outcome.attachments_failed
        + outcome.attachments_oversized
        + outcome.attachments_empty
    )
    summary.attachments_processed += outcome.attachments_processed
    summary.attachments_unsupported += outcome.attachments_unsupported
    summary.attachments_failed += outcome.attachments_failed
    summary.attachments_oversized += outcome.attachments_oversized
    summary.attachments_empty += outcome.attachments_empty
