"""Tests d'intégration `fiduciaire_worker.imap_fetch` — Phase B orchestrator.

End-to-end : FakeImap (offline) → email_parser → email_messages/email_attachments
en DB → pipeline mocké. Vérifie idempotence, dry-run, filtres sender allow-list,
PGP/S/MIME flag, multi-mandant strict, oversized, unsupported, limit, mark_seen,
UIDVALIDITY rescan, fetch_state persistant.

Cf docs/specs/imap-fetch.md §3.2 data flow Phase B.
"""

from __future__ import annotations

import hashlib
import imaplib
import sqlite3
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker.imap_client import ImapCredentials  # noqa: E402
from fiduciaire_worker.imap_fetch import (  # noqa: E402
    ImapFetchFilters,
    ImapFetchSummary,
    MAX_ATTACHMENT_SIZE_DEFAULT,
    MessageOutcome,
    fetch_emails,
)
from fiduciaire_worker.pipeline import PipelineOutcome  # noqa: E402


# --- FakeImap intégration (offline) ------------------------------------------


class FakeImap:
    """imaplib.IMAP4_SSL-like ; messages dict + login_ok configurables.

    Diffère du FakeImap de test_imap_client : SEARCH retourne les uids
    triés depuis `self._messages.keys()`, FETCH retourne le payload correspondant,
    STORE +Seen est tracé. Adapté à plusieurs UIDs distincts par scenario.
    """

    def __init__(
        self,
        host: str,
        port: int = 993,
        login_ok: bool = True,
        uidvalidity: int = 42,
        messages: dict[int, bytes] | None = None,
        timeout: int | None = None,
    ):
        self.host = host
        self.port = port
        self._login_ok = login_ok
        self._uidvalidity = uidvalidity
        self._messages: dict[int, bytes] = dict(messages or {})
        self.selected_folder: str | None = None
        self.login_called = False
        self.logout_called = False
        self.store_calls: list[tuple[str, str, str]] = []

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        self.login_called = True
        if not self._login_ok:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] bad creds")
        return ("OK", [b"LOGIN ok"])

    def select(self, folder: str = "INBOX", readonly: bool = False):
        self.selected_folder = folder
        return ("OK", [str(len(self._messages)).encode()])

    def response(self, key: str):
        if key.upper() == "UIDVALIDITY":
            return ("OK", [str(self._uidvalidity).encode()])
        return ("OK", [b""])

    def uid(self, command: str, *args: Any):
        cmd = command.upper()
        if cmd == "SEARCH":
            uids = sorted(self._messages.keys())
            return ("OK", [b" ".join(str(u).encode() for u in uids)])
        if cmd == "FETCH":
            try:
                uid = int(args[0])
            except (ValueError, TypeError):
                return ("NO", [b"invalid uid"])
            if uid not in self._messages:
                return ("OK", [None])
            payload = self._messages[uid]
            return (
                "OK",
                [(b"%d (BODY[] {%d}" % (uid, len(payload)), payload), b")"],
            )
        if cmd == "STORE":
            uid_str, flags_op, flags = args
            self.store_calls.append((uid_str, flags_op, flags))
            return ("OK", [b""])
        return ("NO", [b"unknown command"])

    def logout(self):
        self.logout_called = True
        return ("BYE", [b"LOGOUT ok"])


# --- Email fixtures -----------------------------------------------------------


def _email_with_pdf(
    from_addr: str = "billing@swisscom.ch",
    to_addr: str = "factures@cabinet-jura.ch",
    subject: str = "Facture mensuelle",
    message_id: str = "<msg-001@swisscom.ch>",
    pdf_bytes: bytes = b"%PDF-1.4\nhello-world",
    pdf_name: str = "facture.pdf",
    date: str = "Mon, 01 Apr 2026 10:00:00 +0200",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = date
    msg.set_content("Bonjour, votre facture en pièce jointe.")
    msg.add_attachment(
        pdf_bytes, maintype="application", subtype="pdf", filename=pdf_name
    )
    return msg.as_bytes()


def _email_plain_no_pj(
    from_addr: str = "newsletter@bexio.ch",
    message_id: str = "<news-001@bexio.ch>",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "factures@cabinet-jura.ch"
    msg["Subject"] = "Newsletter Bexio"
    msg["Message-ID"] = message_id
    msg["Date"] = "Tue, 02 Apr 2026 10:00:00 +0200"
    msg.set_content("Notre newsletter mensuelle, pas de PJ.")
    return msg.as_bytes()


def _email_pgp_encrypted(message_id: str = "<pgp-001@helsana.ch>") -> bytes:
    """Email avec content-type multipart/encrypted protocol pgp-encrypted."""
    raw = (
        b"From: billing@helsana.ch\r\n"
        b"To: factures@cabinet-jura.ch\r\n"
        b"Subject: Decompte chiffre\r\n"
        b"Message-ID: " + message_id.encode() + b"\r\n"
        b'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; '
        b'boundary="boundary42"\r\n'
        b"\r\n"
        b"--boundary42\r\n"
        b"Content-Type: application/pgp-encrypted\r\n"
        b"\r\n"
        b"Version: 1\r\n"
        b"\r\n"
        b"--boundary42\r\n"
        b"Content-Type: application/octet-stream\r\n"
        b"\r\n"
        b"<encrypted payload>\r\n"
        b"--boundary42--\r\n"
    )
    return raw


def _email_smime(message_id: str = "<smime-001@aXa.ch>") -> bytes:
    raw = (
        b"From: claims@axa.ch\r\n"
        b"To: factures@cabinet-jura.ch\r\n"
        b"Subject: Sinistre\r\n"
        b"Message-ID: " + message_id.encode() + b"\r\n"
        b'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; '
        b'name="smime.p7m"\r\n'
        b"Content-Disposition: attachment; filename=smime.p7m\r\n"
        b"\r\n"
        b"<binary smime payload>\r\n"
    )
    return raw


def _email_with_zip(message_id: str = "<zip-001@vendor.ch>") -> bytes:
    """Attachment .zip — content-type non supporté par pipeline."""
    msg = EmailMessage()
    msg["From"] = "vendor@vendor.ch"
    msg["To"] = "factures@cabinet-jura.ch"
    msg["Subject"] = "Archive"
    msg["Message-ID"] = message_id
    msg["Date"] = "Wed, 03 Apr 2026 10:00:00 +0200"
    msg.set_content("Archive en piece jointe.")
    msg.add_attachment(
        b"PK\x03\x04fake-zip-bytes",
        maintype="application",
        subtype="zip",
        filename="docs.zip",
    )
    return msg.as_bytes()


def _email_with_huge_pdf(
    size_bytes: int = 60 * 1024 * 1024,
    message_id: str = "<huge-001@vendor.ch>",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "huge@vendor.ch"
    msg["To"] = "factures@cabinet-jura.ch"
    msg["Subject"] = "Gros doc"
    msg["Message-ID"] = message_id
    msg["Date"] = "Thu, 04 Apr 2026 10:00:00 +0200"
    msg.set_content("Doc volumineux.")
    msg.add_attachment(
        b"%PDF-1.4\n" + b"X" * (size_bytes - 9),
        maintype="application",
        subtype="pdf",
        filename="huge.pdf",
    )
    return msg.as_bytes()


# --- Helpers DB + config ------------------------------------------------------


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "test.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    return conn


def _make_creds() -> ImapCredentials:
    return ImapCredentials(
        host="imap.example.com", port=993,
        user="alice@example.com", password="s3cret",
    )


def _make_imap_factory(messages: dict[int, bytes], uidvalidity: int = 42,
                      login_ok: bool = True):
    """Retourne un factory qui produit un FakeImap pré-rempli."""
    holder: dict[str, Any] = {}

    def factory(host, port, timeout=None):
        fk = FakeImap(
            host=host, port=port, login_ok=login_ok,
            uidvalidity=uidvalidity, messages=messages,
        )
        holder["fk"] = fk
        return fk

    return factory, holder


def _make_fake_pipeline():
    """Retourne (fn, calls) — fake process_document qui retourne PipelineOutcome."""
    calls: list[Path] = []

    def fake_process_document(source: Path, config, conn, delete_inbox: bool = False):
        calls.append(source)
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        doc_id, _is_new = db.insert_document(
            conn, sha256=sha,
            original_filename=source.name,
            archive_path=f"data/archive/{sha}.{source.suffix.lstrip('.')}",
        )
        db.update_document(conn, doc_id, status=db.STATUS_ROUTED)
        return PipelineOutcome(
            doc_id=doc_id, sha256=sha, status=db.STATUS_ROUTED,
            final_path=None, classification=None, qr_used=False,
            duration_s=0.01, review_reasons=[],
        )

    return fake_process_document, calls


@pytest.fixture
def cfg(tmp_path: Path):
    """Config minimal pour tests intégration."""
    cfg = load_config()
    # On override les paths pour ne pas polluer le repo en tests
    cfg.paths.inbox = tmp_path / "inbox"
    cfg.paths.archive = tmp_path / "archive"
    cfg.paths.needs_review = tmp_path / "needs-review"
    cfg.paths.clients_root = tmp_path / "clients"
    cfg.paths.ensure()
    return cfg


# --- Tests --------------------------------------------------------------------


def test_end_to_end_fetch_and_ingest_5_emails(tmp_path: Path, cfg) -> None:
    """5 emails (4 PDF + 1 newsletter sans PJ) → 4 documents créés + 5 email_messages."""
    messages = {
        10: _email_with_pdf(message_id="<m1@swisscom.ch>", pdf_name="m1.pdf",
                            pdf_bytes=b"%PDF-1.4\nbody-1"),
        11: _email_with_pdf(message_id="<m2@swisscom.ch>", pdf_name="m2.pdf",
                            pdf_bytes=b"%PDF-1.4\nbody-2"),
        12: _email_with_pdf(message_id="<m3@romande.ch>", pdf_name="m3.pdf",
                            pdf_bytes=b"%PDF-1.4\nbody-3"),
        13: _email_with_pdf(message_id="<m4@swisscom.ch>", pdf_name="m4.pdf",
                            pdf_bytes=b"%PDF-1.4\nbody-4"),
        14: _email_plain_no_pj(message_id="<m5@bexio.ch>"),
    }
    factory, holder = _make_imap_factory(messages)
    fake_pipeline, pipeline_calls = _make_fake_pipeline()

    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01",
        creds=_make_creds(),
        conn=conn,
        config=cfg,
        staging_dir=tmp_path / "staging",
        imap_factory=factory,
        process_document_fn=fake_pipeline,
    )

    assert summary.new_messages == 5
    assert summary.duplicates == 0
    assert summary.no_attachment == 1
    assert summary.attachments_processed == 4
    assert len(pipeline_calls) == 4
    assert summary.last_uid_seen == 14
    assert summary.uidvalidity == 42

    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM email_messages WHERE cabinet_id=?",
        ("pilote-jura-01",),
    ).fetchone()
    assert rows["n"] == 5

    att_rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM email_attachments GROUP BY status"
    ).fetchall()
    by_status = {r["status"]: r["n"] for r in att_rows}
    assert by_status.get("processed") == 4

    docs = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
    assert docs["n"] == 4


def test_idempotence_second_run_no_duplicates(tmp_path: Path, cfg) -> None:
    """2× le même fetch → email_messages count ne double pas."""
    messages = {
        20: _email_with_pdf(message_id="<dup-1@swisscom.ch>"),
        21: _email_with_pdf(message_id="<dup-2@swisscom.ch>"),
    }
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    factory1, _ = _make_imap_factory(messages)
    s1 = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory1, process_document_fn=fake_pipeline,
    )
    assert s1.new_messages == 2
    assert s1.duplicates == 0

    factory2, _ = _make_imap_factory(messages)
    s2 = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory2, process_document_fn=fake_pipeline,
    )
    # Run 2 : reprend depuis last_uid_seen → 0 nouveaux
    assert s2.new_messages == 0
    # ou si search retourne les mêmes UIDs : dedup côté Message-ID
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM email_messages WHERE cabinet_id=?",
        ("pilote-jura-01",),
    ).fetchone()["n"]
    assert total == 2


def test_dry_run_no_db_writes_no_pipeline_no_mark_seen(tmp_path: Path, cfg) -> None:
    """dry_run=True : aucune écriture DB, aucun pipeline, aucun mark_seen."""
    messages = {30: _email_with_pdf(message_id="<dry-1@x.ch>")}
    factory, holder = _make_imap_factory(messages)
    fake_pipeline, pipeline_calls = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
        dry_run=True, mark_seen=True,  # même si mark_seen=True, dry-run prime
    )

    assert summary.dry_run is True
    assert summary.new_messages == 1
    assert summary.attachments_total == 1
    # Aucune écriture DB
    rows = conn.execute("SELECT COUNT(*) AS n FROM email_messages").fetchone()
    assert rows["n"] == 0
    docs = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
    assert docs["n"] == 0
    # Aucun appel pipeline
    assert pipeline_calls == []
    # Aucun mark seen
    assert holder["fk"].store_calls == []


def test_filter_sender_allowlist_exact_email(tmp_path: Path, cfg) -> None:
    """Sender allowlist exact email : 1 OK, 1 rejeté."""
    messages = {
        40: _email_with_pdf(from_addr="billing@swisscom.ch",
                            message_id="<ok@swisscom.ch>"),
        41: _email_with_pdf(from_addr="spam@malicious.ru",
                            message_id="<spam@malicious.ru>"),
    }
    factory, _ = _make_imap_factory(messages)
    fake_pipeline, pipeline_calls = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
        filters=ImapFetchFilters(sender_allowlist=["billing@swisscom.ch"]),
    )

    assert summary.new_messages == 1
    assert summary.filtered_sender == 1
    assert len(pipeline_calls) == 1


def test_filter_sender_allowlist_domain_wildcard(tmp_path: Path, cfg) -> None:
    """`@swisscom.ch` matche tous les expéditeurs du domaine."""
    messages = {
        50: _email_with_pdf(from_addr="billing@swisscom.ch", message_id="<a@x.ch>"),
        51: _email_with_pdf(from_addr="support@swisscom.ch", message_id="<b@x.ch>"),
        52: _email_with_pdf(from_addr="random@elsewhere.com", message_id="<c@x.ch>"),
    }
    factory, _ = _make_imap_factory(messages)
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
        filters=ImapFetchFilters(sender_allowlist=["@swisscom.ch"]),
    )

    assert summary.new_messages == 2
    assert summary.filtered_sender == 1


def test_pgp_email_flagged_no_attachments_extracted(tmp_path: Path, cfg) -> None:
    """Email PGP : encryption_status='pgp', 0 attachments processés."""
    messages = {60: _email_pgp_encrypted(message_id="<pgp-1@h.ch>")}
    factory, _ = _make_imap_factory(messages)
    fake_pipeline, pipeline_calls = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
    )

    assert summary.pgp_skipped == 1
    assert summary.new_messages == 1
    assert summary.attachments_processed == 0
    assert pipeline_calls == []

    row = conn.execute(
        "SELECT encryption_status FROM email_messages WHERE message_id=?",
        ("<pgp-1@h.ch>",),
    ).fetchone()
    assert row["encryption_status"] == "pgp"


def test_smime_email_flagged_no_attachments_extracted(tmp_path: Path, cfg) -> None:
    """Email S/MIME : encryption_status='smime', 0 attachments processés."""
    messages = {70: _email_smime(message_id="<smime-1@axa.ch>")}
    factory, _ = _make_imap_factory(messages)
    fake_pipeline, pipeline_calls = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
    )

    assert summary.smime_skipped == 1
    assert pipeline_calls == []


def test_multi_mandant_isolation(tmp_path: Path, cfg) -> None:
    """Cabinet A fetch puis cabinet B → email_messages bien isolés par cabinet_id."""
    messages = {
        80: _email_with_pdf(message_id="<m-shared@swisscom.ch>"),
    }
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    factory_a, _ = _make_imap_factory(messages)
    fetch_emails(
        cabinet_id="cabinet-a", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging-a",
        imap_factory=factory_a, process_document_fn=fake_pipeline,
    )

    factory_b, _ = _make_imap_factory(messages)
    fetch_emails(
        cabinet_id="cabinet-b", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging-b",
        imap_factory=factory_b, process_document_fn=fake_pipeline,
    )

    rows_a = conn.execute(
        "SELECT COUNT(*) AS n FROM email_messages WHERE cabinet_id=?",
        ("cabinet-a",),
    ).fetchone()["n"]
    rows_b = conn.execute(
        "SELECT COUNT(*) AS n FROM email_messages WHERE cabinet_id=?",
        ("cabinet-b",),
    ).fetchone()["n"]
    assert rows_a == 1
    assert rows_b == 1


def test_oversized_attachment_marked_and_skipped(tmp_path: Path, cfg) -> None:
    """Attachment > max_size → status 'oversized', pipeline NON appelé."""
    messages = {90: _email_with_huge_pdf(size_bytes=200 * 1024)}  # 200 KB > limit 100 KB
    factory, _ = _make_imap_factory(messages)
    fake_pipeline, pipeline_calls = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
        max_attachment_size_bytes=100 * 1024,
    )

    assert summary.attachments_oversized == 1
    assert summary.attachments_processed == 0
    assert pipeline_calls == []

    row = conn.execute(
        "SELECT status FROM email_attachments WHERE filename=?",
        ("huge.pdf",),
    ).fetchone()
    assert row["status"] == "oversized"


def test_unsupported_attachment_zip_status_set(tmp_path: Path, cfg) -> None:
    """Attachment .zip → status 'unsupported', pipeline non appelé."""
    messages = {100: _email_with_zip()}
    factory, _ = _make_imap_factory(messages)
    fake_pipeline, pipeline_calls = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
    )

    assert summary.attachments_unsupported == 1
    assert pipeline_calls == []

    row = conn.execute(
        "SELECT status FROM email_attachments WHERE filename=?",
        ("docs.zip",),
    ).fetchone()
    assert row["status"] == "unsupported"


def test_limit_caps_processing(tmp_path: Path, cfg) -> None:
    """limit=2 sur 5 emails → seulement 2 traités."""
    messages = {
        110 + i: _email_with_pdf(message_id=f"<lim-{i}@x.ch>", pdf_name=f"f{i}.pdf")
        for i in range(5)
    }
    factory, _ = _make_imap_factory(messages)
    fake_pipeline, pipeline_calls = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
        limit=2,
    )

    assert summary.new_messages == 2
    assert len(pipeline_calls) == 2


def test_mark_seen_when_flag_set(tmp_path: Path, cfg) -> None:
    """mark_seen=True → STORE +Seen appelé pour chaque UID traité."""
    messages = {120: _email_with_pdf(message_id="<seen-1@x.ch>")}
    factory, holder = _make_imap_factory(messages)
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
        mark_seen=True,
    )

    assert len(holder["fk"].store_calls) == 1
    assert "Seen" in holder["fk"].store_calls[0][2]


def test_mark_seen_false_by_default(tmp_path: Path, cfg) -> None:
    """mark_seen pas demandé → STORE +Seen non appelé."""
    messages = {130: _email_with_pdf(message_id="<noseen-1@x.ch>")}
    factory, holder = _make_imap_factory(messages)
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
    )

    assert holder["fk"].store_calls == []


def test_uidvalidity_change_triggers_full_rescan(tmp_path: Path, cfg) -> None:
    """Si UIDVALIDITY change entre 2 runs → rescan complet + dedup Message-ID."""
    messages = {200: _email_with_pdf(message_id="<rsc-1@x.ch>")}
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    factory1, _ = _make_imap_factory(messages, uidvalidity=42)
    s1 = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory1, process_document_fn=fake_pipeline,
    )
    assert s1.new_messages == 1
    assert s1.uidvalidity == 42

    # Serveur a rebuild la mailbox → nouvel UIDVALIDITY → full rescan
    factory2, _ = _make_imap_factory(messages, uidvalidity=99)
    s2 = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory2, process_document_fn=fake_pipeline,
    )
    # Dedup Message-ID empêche le doublon
    assert s2.uidvalidity == 99
    assert s2.duplicates == 1
    assert s2.new_messages == 0
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM email_messages"
    ).fetchone()["n"]
    assert total == 1


def test_fetch_state_persisted_after_run(tmp_path: Path, cfg) -> None:
    """Après run, email_fetch_state contient last_uid_seen et uidvalidity."""
    messages = {300: _email_with_pdf(message_id="<st-1@x.ch>"),
                301: _email_with_pdf(message_id="<st-2@x.ch>")}
    factory, _ = _make_imap_factory(messages, uidvalidity=77)
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
    )

    row = conn.execute(
        "SELECT * FROM email_fetch_state WHERE cabinet_id=? AND folder=?",
        ("pilote-jura-01", "INBOX"),
    ).fetchone()
    assert row is not None
    assert row["last_uid_seen"] == 301
    assert row["uidvalidity"] == 77
    assert row["last_fetch_status"] == "ok"


def test_pipeline_exception_marks_attachment_failed(tmp_path: Path, cfg) -> None:
    """Si process_document raise sur 1 PJ → status 'failed', continue les autres."""
    messages = {
        400: _email_with_pdf(message_id="<ok@x.ch>", pdf_name="ok.pdf",
                             pdf_bytes=b"%PDF-1.4\nok-content"),
        401: _email_with_pdf(message_id="<boom@x.ch>", pdf_name="boom.pdf",
                             pdf_bytes=b"%PDF-1.4\nboom-content"),
    }

    def flaky_pipeline(source, config, conn, delete_inbox=False):
        # Le staging file est nommé <sha>.pdf, donc on inspecte le contenu.
        if b"boom" in source.read_bytes():
            raise RuntimeError("pipeline crash simulé")
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        doc_id, _ = db.insert_document(
            conn, sha256=sha, original_filename=source.name,
            archive_path=f"archive/{sha}.pdf",
        )
        return PipelineOutcome(
            doc_id=doc_id, sha256=sha, status=db.STATUS_ROUTED,
            final_path=None, classification=None, qr_used=False,
            duration_s=0.01, review_reasons=[],
        )

    factory, _ = _make_imap_factory(messages)
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=flaky_pipeline,
    )

    assert summary.attachments_processed == 1
    assert summary.attachments_failed == 1
    assert summary.new_messages == 2  # les 2 emails sont quand même persistés

    row = conn.execute(
        "SELECT status, reason FROM email_attachments WHERE filename=?",
        ("boom.pdf",),
    ).fetchone()
    assert row["status"] == "failed"
    assert "pipeline crash simulé" in (row["reason"] or "")


def test_summary_dataclass_shape(tmp_path: Path, cfg) -> None:
    """Smoke test : Summary contient les champs attendus."""
    messages = {500: _email_with_pdf(message_id="<shape-1@x.ch>")}
    factory, _ = _make_imap_factory(messages)
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    summary = fetch_emails(
        cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
        config=cfg, staging_dir=tmp_path / "staging",
        imap_factory=factory, process_document_fn=fake_pipeline,
    )

    assert isinstance(summary, ImapFetchSummary)
    assert summary.cabinet_id == "pilote-jura-01"
    assert summary.folder == "INBOX"
    assert summary.duration_s > 0
    assert len(summary.by_message) == 1
    assert isinstance(summary.by_message[0], MessageOutcome)


def test_filters_dataclass_defaults() -> None:
    """ImapFetchFilters() par défaut accepte tout."""
    f = ImapFetchFilters()
    assert f.matches_sender("anyone@anywhere.com") is True
    assert f.matches_sender(None) is True  # défaut tolérant


def test_filters_matches_sender_with_name_prefix() -> None:
    """Sender allow-list doit extraire l'email depuis 'Foo <foo@bar.com>'."""
    f = ImapFetchFilters(sender_allowlist=["billing@swisscom.ch"])
    assert f.matches_sender("Swisscom Billing <billing@swisscom.ch>") is True
    assert f.matches_sender("Random <random@example.com>") is False


def test_filters_empty_allowlist_rejects_all() -> None:
    """sender_allowlist=[] → rien ne passe (explicit deny-all)."""
    f = ImapFetchFilters(sender_allowlist=[])
    assert f.matches_sender("anything@anywhere.com") is False


def test_auth_error_propagates_without_db_write(tmp_path: Path, cfg) -> None:
    """Si login refusé → ImapAuthError, aucun changement DB."""
    from fiduciaire_worker.imap_client import ImapAuthError

    factory, _ = _make_imap_factory({}, login_ok=False)
    fake_pipeline, _ = _make_fake_pipeline()
    conn = _make_db(tmp_path)

    with pytest.raises(ImapAuthError):
        fetch_emails(
            cabinet_id="pilote-jura-01", creds=_make_creds(), conn=conn,
            config=cfg, staging_dir=tmp_path / "staging",
            imap_factory=factory, process_document_fn=fake_pipeline,
        )

    rows = conn.execute("SELECT COUNT(*) AS n FROM email_messages").fetchone()
    assert rows["n"] == 0
