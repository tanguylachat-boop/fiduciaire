"""Fixtures pytest : tmp config + génération PDFs synthétiques.

NB Session 6 (§3.4-bis) : `FIDUCIAIRE_ENCRYPTION_DISABLED=true` est
activé par défaut pour TOUS les tests via `_disable_encryption_by_default`.
Les tests qui veulent tester le chiffrement (test_encryption,
test_column_encryption, test_backup) doivent `monkeypatch.delenv` ce flag
explicitement dans leur propre autouse fixture.
"""

from __future__ import annotations

import io
import shutil
import sys
import textwrap
from pathlib import Path

import pytest
import yaml
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))


# --- Encryption disabled par défaut (non-régression) -----------------------
# Les tests existants (entry_proposer, vendor_history, imap_fetch, dashboard,
# multi_mandant_e2e) ne doivent pas voir de différence quand on intègre
# encrypt/decrypt automatique dans les modules métier.

@pytest.fixture(autouse=True)
def _disable_encryption_by_default(monkeypatch):
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_DISABLED", "true")
    yield


# --- Helpers génération PDF ----------------------------------------------------

def _build_swiss_qr_payload(
    iban: str,
    montant: float,
    devise: str,
    fournisseur_lines: list[str],
    debiteur_lines: list[str],
    reference: str,
    ref_type: str = "QRR",
) -> str:
    """Construit un payload Swiss Payments Code v0200 minimal valide."""
    # Spec : 31 lignes terminées par CRLF.
    # Ordre critique pour notre parser : 0=SPC, 3=IBAN, 5=name créancier, 18=montant, 19=devise, 20=name débiteur, 26=ref_type, 27=reference
    lines = [""] * 32
    lines[0] = "SPC"
    lines[1] = "0200"
    lines[2] = "1"
    lines[3] = iban
    lines[4] = "S"  # type adresse créancier
    lines[5] = fournisseur_lines[0] if fournisseur_lines else ""
    lines[6] = fournisseur_lines[1] if len(fournisseur_lines) > 1 else ""
    lines[7] = fournisseur_lines[2] if len(fournisseur_lines) > 2 else ""
    lines[8] = fournisseur_lines[3] if len(fournisseur_lines) > 3 else ""
    lines[9] = fournisseur_lines[4] if len(fournisseur_lines) > 4 else ""
    lines[10] = "CH"
    # 11-17 : ultimate creditor (vide dans 99 % des cas)
    lines[18] = f"{montant:.2f}" if montant else ""
    lines[19] = devise
    lines[20] = "S"  # type adresse débiteur
    lines[21] = debiteur_lines[0] if debiteur_lines else ""
    lines[22] = debiteur_lines[1] if len(debiteur_lines) > 1 else ""
    lines[23] = debiteur_lines[2] if len(debiteur_lines) > 2 else ""
    lines[24] = debiteur_lines[3] if len(debiteur_lines) > 3 else ""
    lines[25] = debiteur_lines[4] if len(debiteur_lines) > 4 else ""
    lines[26] = "CH"
    lines[27] = ref_type
    lines[28] = reference
    lines[29] = ""
    lines[30] = "EPD"
    return "\r\n".join(lines)


def _qr_png_bytes(payload: str, box_size: int = 6) -> bytes:
    import qrcode
    img = qrcode.make(payload, box_size=box_size, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_pdf_with_qr(
    out_path: Path,
    visible_text: list[str],
    qr_payload: str,
) -> Path:
    """PDF A4 : texte ASCII en haut + QR Swiss en bas. Tesseract lit le texte."""
    c = canvas.Canvas(str(out_path), pagesize=A4)
    c.setFont("Helvetica", 11)
    y = 800
    for line in visible_text:
        c.drawString(20 * mm, y, line)
        y -= 14
    # QR code en bas à droite
    qr_bytes = _qr_png_bytes(qr_payload)
    qr_img = Image.open(io.BytesIO(qr_bytes))
    qr_path = out_path.with_suffix(".qr.png")
    qr_img.save(qr_path, format="PNG")
    c.drawImage(str(qr_path), 130 * mm, 30 * mm, width=46 * mm, height=46 * mm)
    c.save()
    qr_path.unlink(missing_ok=True)
    return out_path


def make_pdf_text_only(out_path: Path, lines: list[str]) -> Path:
    c = canvas.Canvas(str(out_path), pagesize=A4)
    c.setFont("Helvetica", 11)
    y = 800
    for line in lines:
        c.drawString(20 * mm, y, line)
        y -= 14
    c.save()
    return out_path


# --- Fixtures ------------------------------------------------------------------

@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    for sub in ("inbox", "needs-review", "archive", "clients"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def tmp_config(tmp_workspace: Path) -> Path:
    cfg = {
        "cabinet": {
            "name": "Cabinet Test",
            "slug": "test",
            "langues_ocr": ["fra", "deu"],
        },
        "paths": {
            "inbox": str(tmp_workspace / "inbox"),
            "needs_review": str(tmp_workspace / "needs-review"),
            "archive": str(tmp_workspace / "archive"),
            "clients_root": str(tmp_workspace / "clients"),
            "db": str(tmp_workspace / "fiduciaire.sqlite"),
        },
        "llm": {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "env": "dev",
            "models": {
                "dev": {
                    "primary": "qwen2.5:7b-instruct-q4_K_M",
                    "fallback": "qwen2.5:7b-instruct-q4_K_M",
                    "vision": None,
                },
            },
            "prompt_file": "worker/prompts/classify_v2_fewshot.txt",
            "timeout_s": 120,
            "temperature": 0.0,
            "num_predict": 512,
        },
        "preparser": {"swiss_qr_bill": {"enabled": True}},
        "ocr_fallback": {"vision_when_text_ratio_below": 0.10},  # désactive vision en test
        "ocr": {"dpi": 200, "preprocess": {"deskew": False, "binarize": False}},
        "confidence_thresholds": {
            "type": 0.85,
            "client": 0.80,
            "date": 0.75,
            "montant": 0.75,
        },
        "naming": {
            "pattern": "{date_iso}_{type_short}_{fournisseur_slug}_{montant_chf}_{hash6}.pdf",
            "type_short_map": {
                "facture_fournisseur": "FF",
                "note_frais": "NF",
                "releve_bancaire": "RB",
                "document_fiscal": "FI",
                "courrier": "CO",
                "autre": "XX",
            },
        },
        "routing": {"client_dir_pattern": "{client_slug}/{annee}/{type_long}"},
        "clients": [
            {
                "name": "Restaurant Le Rivage SA",
                "aliases": ["Le Rivage", "Rivage SA"],
                "slug": "le-rivage",
            }
        ],
        "logging": {"level": "INFO", "file": str(tmp_workspace / "worker.log")},
    }
    cfg_path = tmp_workspace / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return cfg_path


@pytest.fixture
def pdf_qrbill_swisscom(tmp_workspace: Path) -> Path:
    payload = _build_swiss_qr_payload(
        iban="CH5204835012345678000",
        montant=287.00,
        devise="CHF",
        fournisseur_lines=["Swisscom (Suisse) SA", "Postfach", "3050", "Bern", ""],
        debiteur_lines=["Restaurant Le Rivage SA", "Rue du Rhone 12", "1204", "Geneve", ""],
        reference="210000000000003139471433000",
    )
    pdf = tmp_workspace / "fixtures" / "swisscom_qr.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    return make_pdf_with_qr(
        pdf,
        visible_text=[
            "Swisscom (Suisse) SA",
            "Postfach, 3050 Bern",
            "",
            "Restaurant Le Rivage SA",
            "Rue du Rhone 12",
            "1204 Geneve",
            "",
            "Numero facture: FCT-2024-03-12-00891",
            "Date facture: 12.03.2024",
            "Echeance: 11.04.2024",
            "",
            "Abonnement Internet Pro Fiber 1Gbit/s     99.00 CHF",
            "Abonnement telephonie Business             29.00 CHF",
            "3 lignes mobiles natel pro 45 x 3 =       135.00 CHF",
            "Frais services techniques                  12.50 CHF",
            "",
            "Sous-total HT                             265.50 CHF",
            "TVA 8.1 pourcent                           21.50 CHF",
            "Total TTC                                 287.00 CHF",
        ],
        qr_payload=payload,
    )


@pytest.fixture
def pdf_no_qr_alias(tmp_workspace: Path) -> Path:
    """Facture SIG sans QR-bill, client en alias 'Le Rivage'."""
    pdf = tmp_workspace / "fixtures" / "sig_no_qr.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    return make_pdf_text_only(
        pdf,
        lines=[
            "SIG - Services Industriels de Geneve",
            "Avenue de la Praille 17, 1227 Carouge",
            "",
            "Le Rivage",
            "Rue du Rhone 12, 1204 Geneve",
            "",
            "Facture n SIG-2024-0788",
            "Date emission: 04.04.2024",
            "Periode facturation: 01.01.2024 - 31.03.2024",
            "",
            "Electricite consommee 4215 kWh         387.20 CHF",
            "Eau consommee 89 m3                     18.65 CHF",
            "Frais fixes trimestriels                 7.00 CHF",
            "",
            "Total HT                               412.85 CHF",
            "TVA 8.1 pourcent                        33.44 CHF",
            "Total TTC                              446.29 CHF",
        ],
    )


@pytest.fixture
def pdf_inconnu_low_conf(tmp_workspace: Path) -> Path:
    """Document sans client identifiable (note de frais Migros) → review queue."""
    pdf = tmp_workspace / "fixtures" / "migros_inconnu.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    return make_pdf_text_only(
        pdf,
        lines=[
            "Migros Geneve",
            "Avenue de la Gare 5, 1204 Geneve",
            "",
            "Ticket de caisse 14.03.2024",
            "Cafe                              4.50 CHF",
            "Sandwich                         12.30 CHF",
            "Eau minerale                      3.00 CHF",
            "",
            "Total                            19.80 CHF",
            "",
            "Carte VISA xxxx 1234 - Pierre Muller",
        ],
    )
