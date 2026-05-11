"""Parsing RFC822 bytes → ParsedEmail + attachments.

Pure stdlib `email` module. Pas d'IO, pas de réseau. Conçu pour être
mocké facilement dans les tests et appelé depuis l'orchestrateur
`imap_fetch` (Phase B).

Garanties :
- Détecte PGP/SMIME et n'extrait PAS les attachments chiffrés.
- Walk récursif des multipart (related, mixed, alternative) pour
  trouver les PDFs nichés.
- Décode RFC 2047 pour subject et filename (caractères non-ASCII).
- `message_id` synthétique stable si header absent (hash sha256 court
  des bytes).
- `body_excerpt` tronqué à 200 chars (minimisation RGPD/LPD).
- Best-effort sur bytes corrompus : retourne ParsedEmail avec champs
  null plutôt que de raise.

Cf docs/specs/imap-fetch.md §3.4.
"""

from __future__ import annotations

import email
import email.errors
import email.header
import email.message
import email.policy
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("fiduciaire.email_parser")

BODY_EXCERPT_MAX = 200

# Suffixes alignés avec watcher.ACCEPTED_SUFFIXES / pipeline.
_PIPELINE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

# Content-types reconnus comme supportables pipeline. Le filename peut
# toujours sauver le coup si content-type est application/octet-stream.
_SUPPORTED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/tiff",
    "image/tif",
}

# Marqueurs chiffrement
_PGP_CONTENT_TYPES = {"multipart/encrypted", "application/pgp-encrypted"}
_SMIME_CONTENT_TYPES = {
    "application/pkcs7-mime",
    "application/x-pkcs7-mime",
}


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    size_bytes: int
    content_sha256: str
    raw_bytes: bytes


@dataclass
class ParsedEmail:
    message_id: str
    date_received: str | None
    from_addr: str | None
    to_addr: str | None
    subject: str | None
    body_excerpt: str
    encryption_status: str  # 'plain' | 'pgp' | 'smime'
    attachments: list[ParsedAttachment] = field(default_factory=list)
    size_bytes: int = 0


def _synthesize_message_id(raw: bytes) -> str:
    """ID stable basé sur le hash des bytes (header absent)."""
    h = hashlib.sha256(raw).hexdigest()[:16]
    return f"<synth-{h}@fiduciaire.local>"


def _decode_rfc2047(value: str | None) -> str | None:
    """Décode un header RFC 2047 (=?utf-8?B?...?=) si présent."""
    if value is None:
        return None
    try:
        parts = email.header.decode_header(value)
    except Exception:
        return value
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(enc or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(chunk.decode("utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def detect_encryption(msg: email.message.Message) -> str:
    """Retourne 'plain' | 'pgp' | 'smime'."""
    ctype = (msg.get_content_type() or "").lower()
    if ctype in _PGP_CONTENT_TYPES:
        return "pgp"
    # Vérif PGP/MIME via protocol param
    protocol = (msg.get_param("protocol") or "").lower()
    if "pgp-encrypted" in protocol:
        return "pgp"
    if ctype in _SMIME_CONTENT_TYPES:
        return "smime"
    # SMIME via smime-type param
    if (msg.get_param("smime-type") or "") != "":
        return "smime"
    # Sous-parts (au cas où le top-level est multipart/mixed avec un
    # part chiffré)
    if msg.is_multipart():
        for part in msg.walk():
            if part is msg:
                continue
            sub_ctype = (part.get_content_type() or "").lower()
            if sub_ctype in _PGP_CONTENT_TYPES | _SMIME_CONTENT_TYPES:
                return "pgp" if "pgp" in sub_ctype else "smime"
    return "plain"


def is_supported_pipeline(content_type: str, filename: str) -> bool:
    """Le pipeline peut-il traiter ce type d'attachment ?

    Logique :
      1. Si content_type ∈ supported list → True.
      2. Sinon, si suffixe du filename ∈ pipeline → True (cas
         application/octet-stream avec .pdf).
      3. Sinon → False.
    """
    ct = (content_type or "").lower().strip()
    if ct in _SUPPORTED_CONTENT_TYPES:
        return True
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in _PIPELINE_SUFFIXES:
            return True
    return False


def _walk_attachments(msg: email.message.Message) -> list[ParsedAttachment]:
    """Walk récursif et retourne les attachments (parts avec
    Content-Disposition attachment OU filename présent ET pas du body)."""
    out: list[ParsedAttachment] = []
    for part in msg.walk():
        if part is msg:
            continue
        if part.is_multipart():
            continue
        # Skip body parts (text/plain, text/html sans Content-Disposition)
        disp = (part.get("Content-Disposition") or "").lower()
        filename_raw = part.get_filename()
        ctype = (part.get_content_type() or "").lower()
        is_attachment = "attachment" in disp or "inline" in disp or filename_raw
        if not is_attachment:
            continue
        # Skip si c'est juste un text/plain inline sans filename
        if not filename_raw and ctype.startswith("text/"):
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception as exc:  # pragma: no cover — defensive
            _log.warning("attachment decode failed: %s", exc)
            continue
        if payload is None or len(payload) == 0:
            continue
        filename = _decode_rfc2047(filename_raw) if filename_raw else "unnamed.bin"
        out.append(
            ParsedAttachment(
                filename=filename,
                content_type=ctype,
                size_bytes=len(payload),
                content_sha256=hashlib.sha256(payload).hexdigest(),
                raw_bytes=payload,
            )
        )
    return out


def _extract_body_excerpt(msg: email.message.Message) -> str:
    """Extrait les 200 premiers caractères du body texte."""
    if msg.is_multipart():
        for part in msg.walk():
            if part is msg or part.is_multipart():
                continue
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        text = payload.decode(
                            part.get_content_charset() or "utf-8",
                            errors="replace",
                        )
                        return text.strip()[:BODY_EXCERPT_MAX]
                except Exception:
                    continue
        return ""
    # Single-part
    try:
        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        text = payload.decode(
            msg.get_content_charset() or "utf-8", errors="replace"
        )
        return text.strip()[:BODY_EXCERPT_MAX]
    except Exception:
        return ""


def parse_email_bytes(raw: bytes) -> ParsedEmail:
    """Parse raw RFC822 bytes → ParsedEmail.

    Tolérant aux bytes corrompus : retourne best-effort, ne raise pas.
    """
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.compat32)
    except (email.errors.MessageParseError, Exception) as exc:
        _log.warning("email parse failed (returning minimal ParsedEmail): %s", exc)
        return ParsedEmail(
            message_id=_synthesize_message_id(raw),
            date_received=None,
            from_addr=None,
            to_addr=None,
            subject=None,
            body_excerpt="",
            encryption_status="plain",
            attachments=[],
            size_bytes=len(raw),
        )

    # Headers
    msg_id = (msg.get("Message-ID") or "").strip()
    if not msg_id:
        msg_id = _synthesize_message_id(raw)

    encryption_status = detect_encryption(msg)

    # Attachments uniquement si plain (jamais sur PGP/SMIME)
    attachments = _walk_attachments(msg) if encryption_status == "plain" else []

    body_excerpt = _extract_body_excerpt(msg) if encryption_status == "plain" else ""

    return ParsedEmail(
        message_id=msg_id,
        date_received=(msg.get("Date") or None),
        from_addr=_decode_rfc2047(msg.get("From")),
        to_addr=_decode_rfc2047(msg.get("To")),
        subject=_decode_rfc2047(msg.get("Subject")),
        body_excerpt=body_excerpt,
        encryption_status=encryption_status,
        attachments=attachments,
        size_bytes=len(raw),
    )
