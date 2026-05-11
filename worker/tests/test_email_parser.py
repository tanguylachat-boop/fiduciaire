"""Tests pour `fiduciaire_worker.email_parser`.

Parse RFC822 bytes → ParsedEmail avec attachments. Pure stdlib
`email.message_from_bytes`, donc tests entièrement offline avec
fixtures email synthétiques générés en mémoire.
"""

from __future__ import annotations

import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker.email_parser import (  # noqa: E402
    ParsedAttachment,
    ParsedEmail,
    is_supported_pipeline,
    parse_email_bytes,
)


# --- Helpers fixtures email ---------------------------------------------------


def _build_plain_email(
    from_addr: str = "fournisseur@swisscom.ch",
    to_addr: str = "factures@cabinet-jura.ch",
    subject: str = "Facture mars 2026",
    body: str = "Bonjour, veuillez trouver votre facture en pièce jointe.",
    message_id: str | None = "<abc123@swisscom.ch>",
    date: str | None = "Tue, 11 Mar 2026 09:30:00 +0100",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    if message_id is not None:
        msg["Message-ID"] = message_id
    if date is not None:
        msg["Date"] = date
    msg.set_content(body)
    return msg.as_bytes()


def _build_email_with_pdf(
    pdf_bytes: bytes = b"%PDF-1.4\nfake-pdf-content",
    pdf_name: str = "facture.pdf",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "billing@romande-energie.ch"
    msg["To"] = "factures@cabinet-jura.ch"
    msg["Subject"] = "Votre facture energie"
    msg["Message-ID"] = "<re-2026-03@romande-energie.ch>"
    msg["Date"] = "Mon, 04 Apr 2026 10:00:00 +0200"
    msg.set_content("Veuillez trouver votre facture ci-jointe.")
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_name,
    )
    return msg.as_bytes()


def _build_multipart_alternative(
    text_body: str = "Plain text version",
    html_body: str = "<p>HTML version</p>",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "newsletter@bexio.ch"
    msg["To"] = "factures@cabinet-jura.ch"
    msg["Subject"] = "Newsletter"
    msg["Message-ID"] = "<news@bexio.ch>"
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg.as_bytes()


def _build_email_with_multiple_attachments() -> bytes:
    msg = EmailMessage()
    msg["From"] = "scan@cabinet-jura.ch"
    msg["To"] = "factures@cabinet-jura.ch"
    msg["Subject"] = "Scans du jour"
    msg["Message-ID"] = "<scan-2026-04-04@cabinet>"
    msg.set_content("3 documents scannés.")
    msg.add_attachment(
        b"%PDF-1.4\nfacture1", maintype="application", subtype="pdf",
        filename="facture1.pdf",
    )
    msg.add_attachment(
        b"%PDF-1.4\nfacture2", maintype="application", subtype="pdf",
        filename="facture2.pdf",
    )
    msg.add_attachment(
        b"\x89PNG\r\n\x1a\nticket", maintype="image", subtype="png",
        filename="ticket.png",
    )
    return msg.as_bytes()


def _build_pgp_encrypted() -> bytes:
    """Email PGP/MIME (RFC 3156) : multipart/encrypted; protocol=application/pgp-encrypted."""
    raw = (
        b'From: secure@helsana.ch\r\n'
        b'To: factures@cabinet-jura.ch\r\n'
        b'Subject: =?utf-8?B?RGVjb21wdGUgYXNzdXJhbmNl?=\r\n'
        b'Message-ID: <pgp-helsana@helsana.ch>\r\n'
        b'MIME-Version: 1.0\r\n'
        b'Content-Type: multipart/encrypted; '
        b'protocol="application/pgp-encrypted"; boundary="BOUND"\r\n'
        b'\r\n'
        b'--BOUND\r\n'
        b'Content-Type: application/pgp-encrypted\r\n\r\nVersion: 1\r\n\r\n'
        b'--BOUND\r\n'
        b'Content-Type: application/octet-stream; name="encrypted.asc"\r\n\r\n'
        b'-----BEGIN PGP MESSAGE-----\r\n[encrypted blob]\r\n'
        b'-----END PGP MESSAGE-----\r\n'
        b'--BOUND--\r\n'
    )
    return raw


def _build_smime_encrypted() -> bytes:
    raw = (
        b'From: cfo@private.ch\r\n'
        b'To: factures@cabinet-jura.ch\r\n'
        b'Subject: Confidentiel\r\n'
        b'Message-ID: <smime-1@private.ch>\r\n'
        b'MIME-Version: 1.0\r\n'
        b'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; '
        b'name="smime.p7m"\r\n'
        b'Content-Transfer-Encoding: base64\r\n'
        b'Content-Disposition: attachment; filename="smime.p7m"\r\n\r\n'
        b'MIAGCSqGSIb3DQEHA6CAMIACAQAxggEYMIIBFAIBADCB4DCBzjE...\r\n'
    )
    return raw


def _build_email_with_rfc2047_filename() -> bytes:
    """Filename encodé RFC 2047 (caractères accentués)."""
    raw = (
        b'From: postmaster@helvetia.ch\r\n'
        b'To: factures@cabinet-jura.ch\r\n'
        b'Subject: Facture\r\n'
        b'Message-ID: <accent@helvetia.ch>\r\n'
        b'MIME-Version: 1.0\r\n'
        b'Content-Type: multipart/mixed; boundary="BB"\r\n\r\n'
        b'--BB\r\n'
        b'Content-Type: text/plain\r\n\r\n'
        b'Voir piece jointe\r\n'
        b'--BB\r\n'
        b'Content-Type: application/pdf; '
        b'name="=?utf-8?B?ZmFjdHVyZS1lbGVjdHJpY2l0w6kucGRm?="\r\n'
        b'Content-Transfer-Encoding: base64\r\n'
        b'Content-Disposition: attachment; '
        b'filename="=?utf-8?B?ZmFjdHVyZS1lbGVjdHJpY2l0w6kucGRm?="\r\n\r\n'
        b'JVBERi0xLjQKJWFiY2RlZg==\r\n'
        b'--BB--\r\n'
    )
    return raw


def _build_email_rfc2047_subject_iso() -> bytes:
    raw = (
        b'From: support@sig.ch\r\n'
        b'To: factures@cabinet-jura.ch\r\n'
        b'Subject: =?iso-8859-1?Q?Votre_facture_d=27=E9nergie?=\r\n'
        b'Message-ID: <iso-sig@sig.ch>\r\n'
        b'MIME-Version: 1.0\r\n'
        b'Content-Type: text/plain\r\n\r\n'
        b'Bonjour\r\n'
    )
    return raw


def _build_nested_related_with_pdf() -> bytes:
    """multipart/mixed > multipart/related > application/pdf."""
    raw = (
        b'From: scan@cabinet.ch\r\n'
        b'To: factures@cabinet-jura.ch\r\n'
        b'Subject: Scan\r\n'
        b'Message-ID: <nested@cabinet>\r\n'
        b'MIME-Version: 1.0\r\n'
        b'Content-Type: multipart/mixed; boundary="OUTER"\r\n\r\n'
        b'--OUTER\r\n'
        b'Content-Type: multipart/related; boundary="INNER"\r\n\r\n'
        b'--INNER\r\n'
        b'Content-Type: text/plain\r\n\r\nDescription\r\n'
        b'--INNER\r\n'
        b'Content-Type: application/pdf; name="nested.pdf"\r\n'
        b'Content-Transfer-Encoding: base64\r\n'
        b'Content-Disposition: attachment; filename="nested.pdf"\r\n\r\n'
        b'JVBERi0xLjQK\r\n'
        b'--INNER--\r\n'
        b'--OUTER--\r\n'
    )
    return raw


def _build_email_no_message_id() -> bytes:
    raw = (
        b'From: weird@server.com\r\n'
        b'To: factures@cabinet-jura.ch\r\n'
        b'Subject: No Message-ID\r\n'
        b'MIME-Version: 1.0\r\n'
        b'Content-Type: text/plain\r\n\r\n'
        b'Body without message-id header\r\n'
    )
    return raw


# --- Tests parse_email_bytes --------------------------------------------------


def test_parse_simple_text_email() -> None:
    raw = _build_plain_email()
    parsed = parse_email_bytes(raw)
    assert isinstance(parsed, ParsedEmail)
    assert parsed.message_id == "<abc123@swisscom.ch>"
    assert parsed.from_addr is not None and "swisscom.ch" in parsed.from_addr
    assert parsed.to_addr is not None and "cabinet-jura.ch" in parsed.to_addr
    assert parsed.subject == "Facture mars 2026"
    assert "facture" in parsed.body_excerpt.lower()
    assert parsed.attachments == []
    assert parsed.encryption_status == "plain"
    assert parsed.size_bytes == len(raw)


def test_parse_multipart_alternative_no_attachments() -> None:
    raw = _build_multipart_alternative("Plain", "<p>HTML</p>")
    parsed = parse_email_bytes(raw)
    assert parsed.attachments == []
    assert "Plain" in parsed.body_excerpt


def test_parse_with_pdf_attachment() -> None:
    pdf_content = b"%PDF-1.4\nfake content here"
    raw = _build_email_with_pdf(pdf_bytes=pdf_content, pdf_name="facture.pdf")
    parsed = parse_email_bytes(raw)
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert isinstance(att, ParsedAttachment)
    assert att.filename == "facture.pdf"
    assert att.content_type == "application/pdf"
    assert att.size_bytes == len(pdf_content)
    assert att.raw_bytes == pdf_content
    assert len(att.content_sha256) == 64  # SHA256 hex digest


def test_parse_multiple_attachments_preserves_order() -> None:
    raw = _build_email_with_multiple_attachments()
    parsed = parse_email_bytes(raw)
    assert len(parsed.attachments) == 3
    assert parsed.attachments[0].filename == "facture1.pdf"
    assert parsed.attachments[1].filename == "facture2.pdf"
    assert parsed.attachments[2].filename == "ticket.png"
    assert parsed.attachments[2].content_type == "image/png"


def test_parse_nested_multipart_related_finds_pdf() -> None:
    raw = _build_nested_related_with_pdf()
    parsed = parse_email_bytes(raw)
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].filename == "nested.pdf"
    assert parsed.attachments[0].content_type == "application/pdf"


def test_parse_pgp_encrypted_no_attachment_extraction() -> None:
    raw = _build_pgp_encrypted()
    parsed = parse_email_bytes(raw)
    assert parsed.encryption_status == "pgp"
    # On ne tente PAS d'extraire les attachments d'un mail PGP
    assert parsed.attachments == []
    assert parsed.from_addr is not None and "helsana" in parsed.from_addr


def test_parse_smime_encrypted_detected() -> None:
    raw = _build_smime_encrypted()
    parsed = parse_email_bytes(raw)
    assert parsed.encryption_status == "smime"
    assert parsed.attachments == []


def test_parse_rfc2047_filename_decoded() -> None:
    raw = _build_email_with_rfc2047_filename()
    parsed = parse_email_bytes(raw)
    assert len(parsed.attachments) == 1
    # facture-electricité.pdf (avec accent é)
    assert "facture-electricit" in parsed.attachments[0].filename
    assert parsed.attachments[0].filename.endswith(".pdf")


def test_parse_rfc2047_subject_iso_decoded() -> None:
    raw = _build_email_rfc2047_subject_iso()
    parsed = parse_email_bytes(raw)
    # "Votre facture d'énergie" (accent é depuis ISO-8859-1)
    assert parsed.subject is not None
    assert "facture" in parsed.subject.lower()
    assert "énergie" in parsed.subject.lower() or "energie" in parsed.subject.lower()


def test_parse_missing_message_id_synthesizes_stable_id() -> None:
    raw = _build_email_no_message_id()
    parsed = parse_email_bytes(raw)
    # message_id non vide même si header absent
    assert parsed.message_id is not None
    assert parsed.message_id != ""
    # Stable : même bytes → même id synthétique
    parsed2 = parse_email_bytes(raw)
    assert parsed.message_id == parsed2.message_id


def test_parse_body_excerpt_truncated_at_200_chars() -> None:
    long_body = "A" * 500
    raw = _build_plain_email(body=long_body)
    parsed = parse_email_bytes(raw)
    assert len(parsed.body_excerpt) <= 200


def test_parse_malformed_bytes_returns_best_effort() -> None:
    """Bytes incomplets / corrompus : retourne ParsedEmail avec champs null,
    pas de raise."""
    raw = b"not really an email at all"
    parsed = parse_email_bytes(raw)
    assert isinstance(parsed, ParsedEmail)
    # message_id synthétique stable
    assert parsed.message_id is not None
    assert parsed.attachments == []


# --- is_supported_pipeline ---------------------------------------------------


def test_is_supported_pipeline_pdf() -> None:
    assert is_supported_pipeline("application/pdf", "facture.pdf") is True


def test_is_supported_pipeline_png() -> None:
    assert is_supported_pipeline("image/png", "ticket.png") is True


def test_is_supported_pipeline_jpeg() -> None:
    assert is_supported_pipeline("image/jpeg", "scan.jpg") is True
    assert is_supported_pipeline("image/jpeg", "scan.jpeg") is True


def test_is_supported_pipeline_tiff() -> None:
    assert is_supported_pipeline("image/tiff", "scan.tif") is True
    assert is_supported_pipeline("image/tiff", "scan.tiff") is True


def test_is_supported_pipeline_zip_rejected() -> None:
    assert is_supported_pipeline("application/zip", "archive.zip") is False


def test_is_supported_pipeline_docx_rejected() -> None:
    assert (
        is_supported_pipeline(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc.docx",
        )
        is False
    )


def test_is_supported_pipeline_filename_only_pdf_extension() -> None:
    """Si content_type est application/octet-stream mais filename .pdf → accepté."""
    assert is_supported_pipeline("application/octet-stream", "facture.pdf") is True


def test_is_supported_pipeline_unknown_extension_rejected() -> None:
    assert is_supported_pipeline("application/octet-stream", "random.xyz") is False
