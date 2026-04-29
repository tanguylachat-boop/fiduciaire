"""Étape 2 — Pré-parser Swiss QR-bill (Swiss Payments Code v2.3).

Spec : Implementation Guidelines QR-bill v2.3 (SIX / SwissBanking).
Payload = lignes ASCII séparées par CRLF (ou LF selon scanners).
Header `SPC` (Swiss Payments Code), version `0200` ou `0210`.

Pour le POC on extrait :
  - montant (ligne 19) — peut être vide pour QR sans montant
  - devise (ligne 20)
  - créancier (= fournisseur du document) : nom (ligne 6) + adresse (7-10)
  - débiteur (= client du cabinet) : nom (ligne 21)
  - référence (ligne 28) — type ligne 27 : QRR / SCOR / NON

Confidence = 1.0 sur les champs extraits, par construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Lignes Swiss Payments Code v0200 (0-indexed). Spec SIX Implementation
# Guidelines QR-bill v2.3 :
#   3 = IBAN, 5 = Name créancier, 18 = Amount, 19 = Currency,
#   21 = Name débiteur (final), 27 = RefType, 28 = Reference.
SPC_IBAN = 3
SPC_AMOUNT = 18
SPC_CURRENCY = 19
SPC_CREDITOR_NAME = 5
SPC_DEBTOR_NAME = 21
SPC_REF_TYPE = 27
SPC_REFERENCE = 28


@dataclass
class QRBillData:
    iban: str | None = None
    montant_chf: float | None = None
    devise: str | None = None
    fournisseur: str | None = None
    client_raw: str | None = None
    reference: str | None = None
    reference_type: str | None = None
    raw_payload: str = ""


def is_swiss_qr_payload(payload: str) -> bool:
    if not payload:
        return False
    head = payload.lstrip().splitlines()
    return bool(head) and head[0].strip() == "SPC"


def parse_spc_payload(payload: str) -> QRBillData:
    """Parser SPC tolérant : split par lignes (CRLF ou LF), accès défensif."""
    lines = [ln.rstrip("\r") for ln in payload.replace("\r\n", "\n").split("\n")]

    def _at(idx: int) -> str | None:
        if 0 <= idx < len(lines):
            v = lines[idx].strip()
            return v or None
        return None

    out = QRBillData(raw_payload=payload)
    out.iban = _at(SPC_IBAN)
    out.fournisseur = _at(SPC_CREDITOR_NAME)
    out.client_raw = _at(SPC_DEBTOR_NAME)
    out.reference_type = _at(SPC_REF_TYPE)
    out.reference = _at(SPC_REFERENCE)
    out.devise = _at(SPC_CURRENCY)

    amount_raw = _at(SPC_AMOUNT)
    if amount_raw:
        try:
            out.montant_chf = float(amount_raw)
        except ValueError:
            out.montant_chf = None
    return out


def scan_qr_in_pdf(pdf_path: Path, dpi: int = 300) -> str | None:
    """Convertit chaque page en image et tente un scan QR. Retourne le 1er payload SPC trouvé."""
    from pdf2image import convert_from_path
    from pyzbar.pyzbar import decode

    try:
        pages = convert_from_path(str(pdf_path), dpi=dpi)
    except Exception:
        return None

    return _scan_qr_in_images(pages)


def scan_qr_in_image(image_path: Path) -> str | None:
    from PIL import Image

    try:
        img = Image.open(image_path)
    except Exception:
        return None
    return _scan_qr_in_images([img])


def _scan_qr_in_images(images: Iterable) -> str | None:
    from pyzbar.pyzbar import decode

    for page in images:
        try:
            results = decode(page)
        except Exception:
            continue
        for r in results:
            try:
                payload = r.data.decode("utf-8", errors="replace")
            except Exception:
                continue
            if is_swiss_qr_payload(payload):
                return payload
    return None


def detect_and_parse(path: Path, dpi: int = 300) -> QRBillData | None:
    """Point d'entrée : PDF ou image → SPC parsé ou None."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        payload = scan_qr_in_pdf(path, dpi=dpi)
    else:
        payload = scan_qr_in_image(path)
    if payload is None:
        return None
    return parse_spc_payload(payload)
