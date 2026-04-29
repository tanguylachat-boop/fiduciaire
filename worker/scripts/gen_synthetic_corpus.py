"""Génère un corpus synthétique pour valider la chaîne bench (Lundi soir).

⚠️  Ce corpus est SYNTHÉTIQUE (PDFs reportlab, ASCII, sans bruit OCR réaliste).
Il sert UNIQUEMENT à vérifier que le pipeline est branché et à donner un
signal initial. Le bench Jeudi sur 50 docs RÉELS reste l'unique source de
vérité produit (cf DECISIONS.md 2026-04-27 §"Bench Lundi = signal initial").

Sortie : data/samples-synth/{pdf,labels.csv}
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "data" / "samples-synth"


def _build_spc(iban, montant, devise, fournisseur, debiteur, ref="210000000000003139471433000"):
    fl = list(fournisseur) + [""] * 5
    dl = list(debiteur) + [""] * 5
    lines = [""] * 32
    lines[0] = "SPC"; lines[1] = "0200"; lines[2] = "1"
    lines[3] = iban
    lines[4] = "S"
    lines[5], lines[6], lines[7], lines[8], lines[9] = fl[0], fl[1], fl[2], fl[3], fl[4]
    lines[10] = "CH"
    lines[18] = f"{montant:.2f}" if montant else ""
    lines[19] = devise
    lines[20] = "S"
    lines[21], lines[22], lines[23], lines[24], lines[25] = dl[0], dl[1], dl[2], dl[3], dl[4]
    lines[26] = "CH"; lines[27] = "QRR"; lines[28] = ref; lines[30] = "EPD"
    return "\r\n".join(lines)


def _qr_image(payload):
    img = qrcode.make(payload, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _make_pdf(out: Path, lines, qr_payload=None):
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("Helvetica", 11)
    y = 800
    for ln in lines:
        c.drawString(20 * mm, y, ln)
        y -= 14
    if qr_payload:
        qr_buf = _qr_image(qr_payload)
        qr_path = out.with_suffix(".qr.png")
        Image.open(qr_buf).save(qr_path)
        c.drawImage(str(qr_path), 130 * mm, 30 * mm, width=46 * mm, height=46 * mm)
        c.save()
        qr_path.unlink(missing_ok=True)
    else:
        c.save()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []  # filename, type, client, date, montant, fournisseur, devise, notes

    # 1. Facture Swisscom QR — Le Rivage
    pdf = OUT_DIR / "01_swisscom_qr.pdf"
    spc = _build_spc(
        "CH5204835012345678000", 287.00, "CHF",
        ["Swisscom (Suisse) SA", "Postfach", "", "3050", "Bern"],
        ["Restaurant Le Rivage SA", "Rue du Rhone 12", "", "1204", "Geneve"],
    )
    _make_pdf(
        pdf,
        [
            "Swisscom (Suisse) SA", "Postfach, 3050 Bern", "",
            "Restaurant Le Rivage SA", "Rue du Rhone 12", "1204 Geneve", "",
            "Numero facture: FCT-2024-03-12-00891",
            "Date facture: 12.03.2024",
            "Echeance: 11.04.2024", "",
            "Abonnement Internet Pro Fiber 1Gbit/s     99.00 CHF",
            "Telephonie Business                        29.00 CHF",
            "3 lignes mobiles natel pro 45 x 3        135.00 CHF",
            "Frais services techniques                  12.50 CHF", "",
            "Sous-total HT                             265.50 CHF",
            "TVA 8.1 pourcent                           21.50 CHF",
            "Total TTC                                 287.00 CHF",
        ],
        qr_payload=spc,
    )
    rows.append((pdf.name, "facture_fournisseur", "Restaurant Le Rivage SA", "2024-03-12", "287.00", "Swisscom (Suisse) SA", "CHF", "QR-bill"))

    # 2. Facture SIG sans QR — alias "Le Rivage"
    pdf = OUT_DIR / "02_sig_alias.pdf"
    _make_pdf(
        pdf,
        [
            "SIG - Services Industriels de Geneve",
            "Avenue de la Praille 17, 1227 Carouge", "",
            "Le Rivage", "Rue du Rhone 12, 1204 Geneve", "",
            "Facture n SIG-2024-0788",
            "Date emission: 04.04.2024",
            "Periode: 01.01.2024 - 31.03.2024", "",
            "Electricite consommee 4215 kWh         387.20 CHF",
            "Eau consommee 89 m3                     18.65 CHF",
            "Frais fixes trimestriels                 7.00 CHF", "",
            "Total HT                               412.85 CHF",
            "TVA 8.1 pourcent                        33.44 CHF",
            "Total TTC                              446.29 CHF",
        ],
    )
    rows.append((pdf.name, "facture_fournisseur", "Restaurant Le Rivage SA", "2024-04-04", "446.29", "Services Industriels de Geneve", "CHF", "alias"))

    # 3. Décision fiscale GE — variante "Le Rivage Sàrl"
    pdf = OUT_DIR / "03_fiscal_sarl.pdf"
    _make_pdf(
        pdf,
        [
            "REPUBLIQUE ET CANTON DE GENEVE",
            "Office cantonal des impots",
            "Rue du Stand 26, 1204 Geneve", "",
            "Decision de taxation - exercice 2023", "",
            "Contribuable: Le Rivage Sarl",
            "Adresse: Rue du Rhone 12, 1204 Geneve",
            "No contribuable: 12.345.678", "",
            "Date d emission: 15.06.2024",
            "Echeance paiement: 30.09.2024", "",
            "Impot cantonal et communal du benefice    6820.00 CHF",
            "Impot cantonal du capital                  930.00 CHF",
            "Frais de notification                      100.00 CHF",
            "Total a payer                             7850.00 CHF",
        ],
    )
    rows.append((pdf.name, "document_fiscal", "Restaurant Le Rivage SA", "2024-06-15", "7850.00", "Office cantonal des impots", "CHF", "variante Sarl"))

    # 4. Note de frais Migros (client null attendu)
    pdf = OUT_DIR / "04_migros_inconnu.pdf"
    _make_pdf(
        pdf,
        [
            "Migros Geneve",
            "Avenue de la Gare 5, 1204 Geneve", "",
            "Ticket de caisse 14.03.2024", "",
            "Cafe                              4.50 CHF",
            "Sandwich                         12.30 CHF",
            "Eau minerale                      3.00 CHF", "",
            "Total                            19.80 CHF", "",
            "Carte VISA xxxx 1234 - Pierre Muller",
        ],
    )
    rows.append((pdf.name, "note_frais", "", "2024-03-14", "19.80", "Migros", "CHF", "client null attendu"))

    # 5. Relevé bancaire UBS — Atelier Boillat
    pdf = OUT_DIR / "05_ubs_releve.pdf"
    _make_pdf(
        pdf,
        [
            "UBS Switzerland AG",
            "Bahnhofstrasse 45, 8001 Zurich", "",
            "Releve de compte CH00 0023 0023 1234 5678 V", "",
            "Atelier Boillat", "Avenue Eugene-Pittard 14, 1206 Geneve", "",
            "Periode: 01.02.2024 - 29.02.2024",
            "Date d emission: 01.03.2024", "",
            "Solde initial                          12500.00 CHF",
            "Total credits                           8200.00 CHF",
            "Total debits                            6450.00 CHF",
            "Solde final                            14250.00 CHF",
            "Frais de tenue de compte                  18.00 CHF",
        ],
    )
    rows.append((pdf.name, "releve_bancaire", "Atelier Boillat", "2024-03-01", "14250.00", "UBS Switzerland AG", "CHF", "atelier-boillat"))

    # labels.csv
    labels_path = OUT_DIR / "labels.csv"
    with labels_path.open("w", encoding="utf-8") as f:
        f.write("filename,type,client,date,montant_chf,fournisseur,devise,notes\n")
        for r in rows:
            f.write(",".join(r) + "\n")

    print(f"✓ Corpus synthétique généré dans {OUT_DIR.relative_to(REPO_ROOT)}")
    print(f"  {len(rows)} PDFs + labels.csv")
    print(f"\nLancer le bench :")
    print(f"  .venv/bin/python scripts/bench.py --corpus ../data/samples-synth")


if __name__ == "__main__":
    sys.exit(main())
