"""Génère 30 PDFs synthétiques complémentaires dans data/samples/ (numéros 21-50).

But : étendre le corpus officiel de 20 → 50 docs pour le bench final Mardi.
Couvre les angles morts identifiés au bench V2 :
- Plus de relevés bancaires (UBS, PostFinance, BCV, Raiffeisen) → docs 21-26
- Plus de QR-bills (Swiss Post, CFF, AVS, factures Pro) → docs 27-34
- Plus de docs fiscaux (TVA, AVS, AFC, cantons) → docs 35-39
- Plus de contrats (bail, mandat, prestation, NDA) → docs 40-43
- Cas limites (photo floue, manuscrit dégradé) → docs 44-46
- Notes de frais variées (taxi, parking, hôtel, restaurant) → docs 47-50

Usage : .venv/bin/python scripts/gen_corpus_extension.py
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "data" / "samples"


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


def _make_pdf(out: Path, lines, qr_payload=None, font_size=11):
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("Helvetica", font_size)
    y = 800
    for ln in lines:
        c.drawString(20 * mm, y, ln)
        y -= font_size + 3
    if qr_payload:
        qr_buf = _qr_image(qr_payload)
        qr_path = out.with_suffix(".qr.png")
        Image.open(qr_buf).save(qr_path)
        c.drawImage(str(qr_path), 130 * mm, 30 * mm, width=46 * mm, height=46 * mm)
        c.save()
        qr_path.unlink(missing_ok=True)
    else:
        c.save()


def gen() -> list[tuple]:
    """Retourne la liste des labels CSV pour les 30 nouveaux docs."""
    rows = []

    # ─── Relevés bancaires (21-26) ─────────────────────────────────────────────
    pdf = SAMPLES_DIR / "21_ubs_releve_t1.pdf"
    _make_pdf(pdf, [
        "UBS Switzerland AG", "Bahnhofstrasse 45, 8001 Zürich", "",
        "Relevé de compte CH52 0023 0023 4567 8901 V", "",
        "Restaurant Le Rivage SA", "Rue du Rhône 12, 1204 Genève", "",
        "Période : 01.01.2026 - 31.03.2026",
        "Date émission : 31.03.2026", "",
        "Solde initial                              42'581.30 CHF",
        "Total crédits                              28'945.50 CHF",
        "Total débits                               31'287.80 CHF",
        "Solde final                                40'239.00 CHF",
        "Frais tenue de compte                          24.00 CHF",
    ])
    rows.append(("21_ubs_releve_t1.pdf", "releve_bancaire", "Restaurant Le Rivage SA",
                 "2026-03-31", "40239.00", "UBS Switzerland AG", "CHF",
                 "Relevé UBS T1 — pattern solde final"))

    pdf = SAMPLES_DIR / "22_postfinance_releve_avril.pdf"
    _make_pdf(pdf, [
        "PostFinance SA", "Mingerstrasse 20, 3030 Berne", "",
        "Relevé compte personnel CH98 0900 0000 1234 5678 9", "",
        "Cabinet Médical Dr. Martin Sàrl", "Avenue de Champel 24, 1206 Genève", "",
        "Période : 01.04.2026 - 30.04.2026",
        "Date émission : 30.04.2026", "",
        "Solde au début                              5'420.50 CHF",
        "Total crédits                              18'250.00 CHF",
        "Total débits                               14'880.20 CHF",
        "Solde au 30.04.2026                         8'790.30 CHF",
    ])
    rows.append(("22_postfinance_releve_avril.pdf", "releve_bancaire", "Cabinet Médical Dr. Martin Sàrl",
                 "2026-04-30", "8790.30", "PostFinance SA", "CHF", "Relevé PostFinance avril"))

    pdf = SAMPLES_DIR / "23_bcv_releve_mars.pdf"
    _make_pdf(pdf, [
        "Banque Cantonale Vaudoise (BCV)", "Place St-François 14, 1003 Lausanne", "",
        "Relevé compte courant CH80 0076 7000 1234 5678 9", "",
        "SARL Étude Comptable Genevoise", "Rue du Mont-Blanc 17, 1201 Genève", "",
        "Mars 2026 — date arrêté : 31.03.2026", "",
        "Solde initial                              15'600.00 CHF",
        "Mouvements créditeurs                      24'880.00 CHF",
        "Mouvements débiteurs                       19'410.50 CHF",
        "Solde au 31.03.2026                        21'069.50 CHF",
    ])
    rows.append(("23_bcv_releve_mars.pdf", "releve_bancaire", "SARL Étude Comptable Genevoise",
                 "2026-03-31", "21069.50", "Banque Cantonale Vaudoise", "CHF", "Relevé BCV mars"))

    pdf = SAMPLES_DIR / "24_raiffeisen_releve.pdf"
    _make_pdf(pdf, [
        "Raiffeisenbank Genève-Centre", "Rue du Stand 60, 1204 Genève", "",
        "Auszug Geschäftskonto CH47 8080 8001 2345 6789 0", "",
        "Bauunternehmung Zumstein AG", "Zürichstrasse 88, 8048 Zürich", "",
        "Auszug 04/2026 — Stichtag 30.04.2026", "",
        "Saldo Beginn                               33'440.00 CHF",
        "Total Gutschriften                         52'870.00 CHF",
        "Total Belastungen                          47'195.20 CHF",
        "Saldo Ende                                 39'114.80 CHF",
    ])
    rows.append(("24_raiffeisen_releve.pdf", "releve_bancaire", "Bauunternehmung Zumstein AG",
                 "2026-04-30", "39114.80", "Raiffeisenbank", "CHF", "Auszug Raiffeisen DE"))

    pdf = SAMPLES_DIR / "25_credit_suisse_releve.pdf"
    _make_pdf(pdf, [
        "Credit Suisse (Schweiz) AG", "Paradeplatz 8, 8001 Zürich", "",
        "Compte épargne CH12 0483 5012 3456 7800 0", "",
        "Étude Notariale Roulet & Associés", "Rue du Rhône 65, 1204 Genève", "",
        "Relevé : avril 2026 — date émission 30.04.2026", "",
        "Solde initial                              82'150.00 CHF",
        "Intérêts crédités                              45.20 CHF",
        "Frais et taxes                                 -8.00 CHF",
        "Solde final                                82'187.20 CHF",
    ])
    rows.append(("25_credit_suisse_releve.pdf", "releve_bancaire", "Étude Notariale Roulet & Associés",
                 "2026-04-30", "82187.20", "Credit Suisse (Schweiz) AG", "CHF", "Relevé épargne CS"))

    pdf = SAMPLES_DIR / "26_zkb_releve.pdf"
    _make_pdf(pdf, [
        "Zürcher Kantonalbank (ZKB)", "Bahnhofstrasse 9, 8001 Zürich", "",
        "Geschäftskonto CH74 0070 0110 0012 3456 7", "",
        "Treuhand Berner & Co AG", "Hardturmstrasse 76, 8005 Zürich", "",
        "Auszug 04/2026 — 01.04. - 30.04.2026", "",
        "Anfangssaldo                              125'600.00 CHF",
        "Eingänge                                  187'440.00 CHF",
        "Ausgänge                                  172'331.10 CHF",
        "Endsaldo                                  140'708.90 CHF",
    ])
    rows.append(("26_zkb_releve.pdf", "releve_bancaire", "Treuhand Berner & Co AG",
                 "2026-04-30", "140708.90", "Zürcher Kantonalbank", "CHF", "Auszug ZKB DE"))

    # ─── Factures QR-bill (27-34) ──────────────────────────────────────────────
    pdf = SAMPLES_DIR / "27_swisspost_qr.pdf"
    spc = _build_spc(
        "CH4509000000300003600",
        45.80, "CHF",
        ["Die Schweizerische Post AG", "Wankdorfallee 4", "", "3030", "Bern"],
        ["Architecte Pierre Müller SA", "Rue de la Paix 15", "", "1003", "Lausanne"],
    )
    _make_pdf(pdf, [
        "Die Schweizerische Post AG", "Wankdorfallee 4, 3030 Bern", "",
        "Architecte Pierre Müller SA", "Rue de la Paix 15, 1003 Lausanne", "",
        "Rechnung Nr. PB-2026-7891",
        "Datum : 14.04.2026",
        "Fälligkeit : 14.05.2026", "",
        "Geschäftspaket-Sendungen 12x                  35.40 CHF",
        "Frankaturmaschine Service                     10.40 CHF",
        "Total inkl. MwSt 8.1%                         45.80 CHF",
    ], qr_payload=spc)
    rows.append(("27_swisspost_qr.pdf", "facture_fournisseur", "Architecte Pierre Müller SA",
                 "2026-04-14", "45.80", "Die Schweizerische Post AG", "CHF", "Post DE QR-bill"))

    pdf = SAMPLES_DIR / "28_cff_facture_qr.pdf"
    spc = _build_spc(
        "CH3300700110000001234",
        890.00, "CHF",
        ["Schweizerische Bundesbahnen SBB", "Hilfikerstrasse 1", "", "3000", "Bern"],
        ["Cabinet Avocat Vionnet & Partners", "Cours de Rive 6", "", "1204", "Genève"],
    )
    _make_pdf(pdf, [
        "Schweizerische Bundesbahnen SBB", "Hilfikerstrasse 1, 3000 Bern 65", "",
        "Cabinet Avocat Vionnet & Partners", "Cours de Rive 6, 1204 Genève", "",
        "Facture Business Travel Account #BTA-2026-04-2287",
        "Date facture : 22.04.2026", "",
        "Abonnement général 1 collaborateur          580.00 CHF",
        "Trajets 1ère classe Genève-Zurich (3x)      225.00 CHF",
        "Restauration train (3x)                      85.00 CHF",
        "Total TTC                                   890.00 CHF",
    ], qr_payload=spc)
    rows.append(("28_cff_facture_qr.pdf", "facture_fournisseur", "Cabinet Avocat Vionnet & Partners",
                 "2026-04-22", "890.00", "Schweizerische Bundesbahnen SBB", "CHF", "CFF business travel QR"))

    pdf = SAMPLES_DIR / "29_groupemutuel_qr.pdf"
    spc = _build_spc(
        "CH8908000000123456789",
        2_410.00, "CHF",
        ["Groupe Mutuel Assurances", "Rue des Cèdres 5", "", "1920", "Martigny"],
        ["Cabinet Dentaire Dr. Bernasconi", "Rue de Lausanne 38", "", "1201", "Genève"],
    )
    _make_pdf(pdf, [
        "Groupe Mutuel Assurances", "Rue des Cèdres 5, 1920 Martigny", "",
        "Cabinet Dentaire Dr. Bernasconi", "Rue de Lausanne 38, 1201 Genève", "",
        "Facture trimestrielle assurance LAA",
        "Police N° GM-2026-44871",
        "Date facture : 02.04.2026",
        "Période : 01.04.2026 - 30.06.2026", "",
        "LAA prof. 4 employés                      2'085.00 CHF",
        "Indemnités journalières maladie             325.00 CHF",
        "Total TTC                                 2'410.00 CHF",
    ], qr_payload=spc)
    rows.append(("29_groupemutuel_qr.pdf", "facture_fournisseur", "Cabinet Dentaire Dr. Bernasconi",
                 "2026-04-02", "2410.00", "Groupe Mutuel Assurances", "CHF", "Assurance LAA QR"))

    pdf = SAMPLES_DIR / "30_salt_facture_qr.pdf"
    spc = _build_spc(
        "CH4900788000123456789",
        178.50, "CHF",
        ["Salt Mobile SA", "Rue du Caudray 4", "", "1020", "Renens"],
        ["Boutique Mode Délice Sàrl", "Rue du Marché 9", "", "1003", "Lausanne"],
    )
    _make_pdf(pdf, [
        "Salt Mobile SA", "Rue du Caudray 4, 1020 Renens", "",
        "Boutique Mode Délice Sàrl", "Rue du Marché 9, 1003 Lausanne", "",
        "Facture mensuelle N° SLT-2026-04-9981",
        "Date facture : 18.04.2026",
        "Échéance : 18.05.2026", "",
        "Forfaits mobile pro 3 lignes               135.00 CHF",
        "Internet fibre boutique                     35.00 CHF",
        "Frais services                               8.50 CHF",
        "Total TTC                                  178.50 CHF",
    ], qr_payload=spc)
    rows.append(("30_salt_facture_qr.pdf", "facture_fournisseur", "Boutique Mode Délice Sàrl",
                 "2026-04-18", "178.50", "Salt Mobile SA", "CHF", "Salt mobile QR"))

    pdf = SAMPLES_DIR / "31_iwb_basel_qr.pdf"
    spc = _build_spc(
        "CH9300762011623852957",
        612.40, "CHF",
        ["Industrielle Werke Basel (IWB)", "Margarethenstrasse 40", "", "4053", "Basel"],
        ["Brasserie La Cigale Sàrl", "Boulevard Saint-Georges 12", "", "1205", "Genève"],
    )
    _make_pdf(pdf, [
        "Industrielle Werke Basel (IWB)", "Margarethenstrasse 40, 4053 Basel", "",
        "Brasserie La Cigale Sàrl", "Boulevard Saint-Georges 12, 1205 Genève", "",
        "Rechnung Energie & Wasser",
        "Rechnungsnummer : IWB-2026-44129",
        "Rechnungsdatum : 09.04.2026",
        "Periode : Q1 2026", "",
        "Strom 4'820 kWh                            384.20 CHF",
        "Wasser 78 m³                               142.00 CHF",
        "Grundgebühren                               86.20 CHF",
        "Total TTC                                  612.40 CHF",
    ], qr_payload=spc)
    rows.append(("31_iwb_basel_qr.pdf", "facture_fournisseur", "Brasserie La Cigale Sàrl",
                 "2026-04-09", "612.40", "Industrielle Werke Basel", "CHF", "IWB Basel DE QR"))

    pdf = SAMPLES_DIR / "32_office_world_qr.pdf"
    spc = _build_spc(
        "CH7430000001250112345",
        348.20, "CHF",
        ["Office World AG", "Industriestrasse 25", "", "8627", "Grüningen"],
        ["Études Cabinet Tanguy Lachat", "Rue de la Croix-d'Or 5", "", "1204", "Genève"],
    )
    _make_pdf(pdf, [
        "Office World AG", "Industriestrasse 25, 8627 Grüningen", "",
        "Études Cabinet Tanguy Lachat", "Rue de la Croix-d'Or 5, 1204 Genève", "",
        "Facture N° OW-2026-12774",
        "Date : 16.04.2026",
        "Échéance : 16.05.2026", "",
        "Toner HP LaserJet 312A noir x4              184.00 CHF",
        "Ramettes A4 80g x10                          89.50 CHF",
        "Stylos & fournitures bureau                  74.70 CHF",
        "Total TTC                                  348.20 CHF",
    ], qr_payload=spc)
    rows.append(("32_office_world_qr.pdf", "facture_fournisseur", "Études Cabinet Tanguy Lachat",
                 "2026-04-16", "348.20", "Office World AG", "CHF", "Fournitures bureau QR"))

    pdf = SAMPLES_DIR / "33_axa_assurance_qr.pdf"
    spc = _build_spc(
        "CH3704835000111223344",
        1_525.00, "CHF",
        ["AXA Assurances SA", "General-Guisan-Strasse 40", "", "8401", "Winterthur"],
        ["Boulangerie La Mie Dorée Sàrl", "Rue Centrale 47", "", "1003", "Lausanne"],
    )
    _make_pdf(pdf, [
        "AXA Assurances SA", "General-Guisan-Strasse 40, 8401 Winterthur", "",
        "Boulangerie La Mie Dorée Sàrl", "Rue Centrale 47, 1003 Lausanne", "",
        "Facture annuelle assurance commerce",
        "Police RC + Inventaire #AX-2026-77291",
        "Date : 11.04.2026",
        "Période : 01.05.2026 - 30.04.2027", "",
        "Responsabilité civile prof.                820.00 CHF",
        "Inventaire & marchandises                  490.00 CHF",
        "Protection juridique                       215.00 CHF",
        "Total TTC                                1'525.00 CHF",
    ], qr_payload=spc)
    rows.append(("33_axa_assurance_qr.pdf", "facture_fournisseur", "Boulangerie La Mie Dorée Sàrl",
                 "2026-04-11", "1525.00", "AXA Assurances SA", "CHF", "AXA RC commerce QR"))

    pdf = SAMPLES_DIR / "34_localnet_qr.pdf"
    spc = _build_spc(
        "CH2008300100000123456",
        58.90, "CHF",
        ["Localnet AG", "Bielstrasse 25", "", "4500", "Solothurn"],
        ["Cafe du Centre", "Place du Marché 3", "", "1820", "Montreux"],
    )
    _make_pdf(pdf, [
        "Localnet AG", "Bielstrasse 25, 4500 Solothurn", "",
        "Cafe du Centre", "Place du Marché 3, 1820 Montreux", "",
        "Facture mensuelle Internet pro",
        "N° LN-2026-04-3389",
        "Date : 05.04.2026",
        "Échéance : 05.05.2026", "",
        "Internet 100 Mbit/s commerces               49.00 CHF",
        "TVA 8.1%                                     3.97 CHF",
        "Frais service                                5.93 CHF",
        "Total TTC                                   58.90 CHF",
    ], qr_payload=spc)
    rows.append(("34_localnet_qr.pdf", "facture_fournisseur", "Cafe du Centre",
                 "2026-04-05", "58.90", "Localnet AG", "CHF", "Internet pro QR"))

    # ─── Documents fiscaux (35-39) ─────────────────────────────────────────────
    pdf = SAMPLES_DIR / "35_afc_decompte_tva_t1.pdf"
    _make_pdf(pdf, [
        "Administration fédérale des contributions (AFC)",
        "Eigerstrasse 65, 3003 Berne", "",
        "DÉCOMPTE TVA - 1er trimestre 2026", "",
        "Assujetti : Restaurant Le Rivage SA",
        "N° TVA : CHE-145.892.674 TVA",
        "Date émission : 02.04.2026",
        "Échéance paiement : 31.05.2026", "",
        "Chiffre d'affaires imposable             185'420.00 CHF",
        "TVA due (8.1%)                            15'019.02 CHF",
        "TVA récupérable                           -3'150.00 CHF",
        "Solde TVA à payer                         11'869.02 CHF",
    ])
    rows.append(("35_afc_decompte_tva_t1.pdf", "document_fiscal", "Restaurant Le Rivage SA",
                 "2026-04-02", "11869.02", "Administration fédérale des contributions (AFC)",
                 "CHF", "Décompte TVA T1 AFC"))

    pdf = SAMPLES_DIR / "36_avs_cotisations_t2.pdf"
    _make_pdf(pdf, [
        "Caisse cantonale AVS Genève",
        "Route de Chêne 54, 1208 Genève", "",
        "FACTURE D'ACOMPTE COTISATIONS - Trimestre 2 / 2026", "",
        "Affilié : Cabinet Médical Dr. Martin Sàrl",
        "N° affilié : 100.7782.4521",
        "Date émission : 02.04.2026",
        "Échéance paiement : 30.06.2026", "",
        "AVS-AI-APG (10.6%)                         8'420.00 CHF",
        "Allocations familiales (2.0%)              1'588.00 CHF",
        "Frais administration (3%)                    300.24 CHF",
        "Total acompte                             10'308.24 CHF",
    ])
    rows.append(("36_avs_cotisations_t2.pdf", "document_fiscal", "Cabinet Médical Dr. Martin Sàrl",
                 "2026-04-02", "10308.24", "Caisse cantonale AVS Genève", "CHF",
                 "AVS T2 acompte"))

    pdf = SAMPLES_DIR / "37_taxation_communale.pdf"
    _make_pdf(pdf, [
        "Administration communale de Lausanne",
        "Service des impôts", "Place de la Palud 2, 1003 Lausanne", "",
        "AVIS DE TAXATION COMMUNALE 2025", "",
        "Contribuable : Architecte Pierre Müller SA",
        "N° contribuable : 76.4452.881",
        "Date émission : 12.04.2026", "",
        "Impôt communal sur le bénéfice            22'410.00 CHF",
        "Impôt communal sur le capital              1'820.00 CHF",
        "Total dû                                  24'230.00 CHF",
        "Échéance : 30.06.2026",
    ])
    rows.append(("37_taxation_communale.pdf", "document_fiscal", "Architecte Pierre Müller SA",
                 "2026-04-12", "24230.00", "Administration communale de Lausanne",
                 "CHF", "Taxation communale 2025"))

    pdf = SAMPLES_DIR / "38_estv_mwst_de.pdf"
    _make_pdf(pdf, [
        "Eidgenössische Steuerverwaltung (ESTV)",
        "Schwarztorstrasse 50, 3003 Bern", "",
        "MWST-ABRECHNUNG - 1. Quartal 2026", "",
        "Steuerpflichtige : Bauunternehmung Zumstein AG",
        "MWST-Nr. : CHE-251.443.882 MWST",
        "Ausstellungsdatum : 03.04.2026",
        "Fälligkeit : 31.05.2026", "",
        "Steuerbarer Umsatz                       412'880.00 CHF",
        "MWST geschuldet (8.1%)                    33'443.28 CHF",
        "Vorsteuer abziehbar                       -7'995.00 CHF",
        "Schuld total                              25'448.28 CHF",
    ])
    rows.append(("38_estv_mwst_de.pdf", "document_fiscal", "Bauunternehmung Zumstein AG",
                 "2026-04-03", "25448.28", "Eidgenössische Steuerverwaltung (ESTV)",
                 "CHF", "MWST DE Q1 2026"))

    pdf = SAMPLES_DIR / "39_ofas_contribution.pdf"
    _make_pdf(pdf, [
        "Office fédéral des assurances sociales (OFAS)",
        "Effingerstrasse 20, 3003 Berne", "",
        "DÉCISION DE CONTRIBUTION 2026", "",
        "Employeur : SARL Étude Comptable Genevoise",
        "N° employeur : 2.345.678.9",
        "Date émission : 08.04.2026", "",
        "Contribution OFAS sur masse salariale       1'250.00 CHF",
        "Décision portant sur l'année 2026",
        "Échéance : 30.04.2026",
    ])
    rows.append(("39_ofas_contribution.pdf", "document_fiscal", "SARL Étude Comptable Genevoise",
                 "2026-04-08", "1250.00", "Office fédéral des assurances sociales (OFAS)",
                 "CHF", "Décision OFAS 2026"))

    # ─── Contrats (40-43) ──────────────────────────────────────────────────────
    pdf = SAMPLES_DIR / "40_bail_commercial_v2.pdf"
    _make_pdf(pdf, [
        "CONTRAT DE BAIL COMMERCIAL", "",
        "Conformément aux articles 253 et suivants du Code des obligations.", "",
        "Entre les soussignés :",
        "Bailleur : Patrimoine Lausannois SA, Place St-François 7, 1003 Lausanne",
        "Locataire : Boulangerie La Mie Dorée Sàrl, Rue Centrale 47, 1003 Lausanne", "",
        "Objet : local commercial 78 m² + arrière-boutique 22 m², rez-de-chaussée",
        "Adresse : Rue Centrale 47, 1003 Lausanne", "",
        "Loyer mensuel net : CHF 3'850.00",
        "Charges forfaitaires : CHF 380.00",
        "Total mensuel : CHF 4'230.00", "",
        "Durée : 5 ans à compter du 1er juin 2026",
        "Date signature : 25 avril 2026",
        "Signatures des parties.",
    ])
    rows.append(("40_bail_commercial_v2.pdf", "contrat", "Boulangerie La Mie Dorée Sàrl",
                 "2026-04-25", "3850.00", "Patrimoine Lausannois SA", "CHF",
                 "Bail commercial 5 ans"))

    pdf = SAMPLES_DIR / "41_mandat_fiduciaire.pdf"
    _make_pdf(pdf, [
        "CONTRAT DE MANDAT FIDUCIAIRE", "",
        "Entre les soussignés :",
        "Mandant : Brasserie La Cigale Sàrl, Boulevard Saint-Georges 12, 1205 Genève",
        "Mandataire : SARL Étude Comptable Genevoise, Rue du Mont-Blanc 17, 1201 Genève", "",
        "Objet : tenue de la comptabilité, déclarations TVA trimestrielles,",
        "bouclement annuel, déclaration fiscale.", "",
        "Tarif horaire : CHF 165.00 HT",
        "Forfait bouclement annuel : CHF 2'800.00 HT",
        "Forfait déclaration fiscale : CHF 950.00 HT", "",
        "Durée : 1 année reconductible tacitement",
        "Date entrée en vigueur : 1er mai 2026",
        "Signatures des parties.",
    ])
    rows.append(("41_mandat_fiduciaire.pdf", "contrat", "Brasserie La Cigale Sàrl",
                 "2026-05-01", "165.00", "SARL Étude Comptable Genevoise", "CHF",
                 "Mandat fiduciaire annuel"))

    pdf = SAMPLES_DIR / "42_contrat_prestation_it.pdf"
    _make_pdf(pdf, [
        "CONTRAT DE PRESTATION DE SERVICES INFORMATIQUES", "",
        "Entre les soussignés :",
        "Prestataire : LX Studio SA, Genève",
        "Client : Étude Notariale Roulet & Associés, Rue du Rhône 65, 1204 Genève", "",
        "Objet : intégration logiciel comptable, formation 2 jours, support 1 an", "",
        "Forfait projet : CHF 8'400.00 HT",
        "Support mensuel inclus 4h : CHF 690.00 HT/mois", "",
        "Date signature : 22 avril 2026",
        "Date début prestation : 1er juin 2026",
        "Durée engagement : 12 mois",
        "Signatures des parties.",
    ])
    rows.append(("42_contrat_prestation_it.pdf", "contrat", "Étude Notariale Roulet & Associés",
                 "2026-04-22", "8400.00", "LX Studio SA", "CHF",
                 "Contrat IT prestation forfait"))

    pdf = SAMPLES_DIR / "43_avenant_loyer.pdf"
    _make_pdf(pdf, [
        "AVENANT N° 1 AU CONTRAT DE BAIL", "",
        "Conformément aux dispositions du contrat initial signé le 15.03.2024.", "",
        "Entre les soussignés :",
        "Bailleur : Société Immobilière Lac Léman SA",
        "Locataire : Cabinet Avocat Vionnet & Partners, Cours de Rive 6, 1204 Genève", "",
        "Objet : indexation du loyer ICHA index 105.2 → 107.8", "",
        "Ancien loyer mensuel : CHF 4'200.00",
        "Nouveau loyer mensuel : CHF 4'305.00",
        "Différentiel mensuel : CHF 105.00", "",
        "Date avenant : 14.04.2026",
        "Date entrée en vigueur : 1er juillet 2026",
        "Signatures des parties.",
    ])
    rows.append(("43_avenant_loyer.pdf", "contrat", "Cabinet Avocat Vionnet & Partners",
                 "2026-04-14", "4305.00", "Société Immobilière Lac Léman SA", "CHF",
                 "Avenant indexation loyer"))

    # ─── Cas limites OCR (44-46) ───────────────────────────────────────────────
    # Doc 44 : police petite simulant photo floue (texte court, 1 ligne lisible)
    pdf = SAMPLES_DIR / "44_recu_taxi_flou.pdf"
    _make_pdf(pdf, [
        "Taxi Phone Geneve",
        "Course du 17.04.2026 23:42",
        "Total TTC: 38.50 CHF",
    ], font_size=7)
    rows.append(("44_recu_taxi_flou.pdf", "note_frais", "inconnu",
                 "2026-04-17", "38.50", "Taxi Phone Geneve", "CHF",
                 "CAS LIMITE - reçu taxi simulant photo dégradée"))

    # Doc 45 : encore plus court, simule manuscrit illisible
    pdf = SAMPLES_DIR / "45_recu_manuscrit_2.pdf"
    _make_pdf(pdf, [
        "Restaurant La Coupole",
        "Date 19/04/26 - Diner 2 pers.",
        "Net 87.00 CHF",
        "[Ticket dégradé OCR]",
    ], font_size=7)
    rows.append(("45_recu_manuscrit_2.pdf", "note_frais", "inconnu",
                 "2026-04-19", "87.00", "Restaurant La Coupole", "CHF",
                 "CAS LIMITE - manuscrit/dégradé"))

    pdf = SAMPLES_DIR / "46_quittance_parking.pdf"
    _make_pdf(pdf, [
        "Parking Cornavin SA", "",
        "Quittance N° 442881",
        "Date : 21.04.2026 14:37",
        "Durée : 3h12min",
        "Tarif jour                                  18.00 CHF",
    ], font_size=8)
    rows.append(("46_quittance_parking.pdf", "note_frais", "inconnu",
                 "2026-04-21", "18.00", "Parking Cornavin SA", "CHF",
                 "Quittance parking standard"))

    # ─── Notes de frais (47-50) ────────────────────────────────────────────────
    pdf = SAMPLES_DIR / "47_facture_hotel.pdf"
    _make_pdf(pdf, [
        "Hotel Beau-Rivage Lausanne", "Place du Port 17-19, 1006 Lausanne", "",
        "Cabinet Avocat Vionnet & Partners",
        "Cours de Rive 6, 1204 Genève", "",
        "Facture séjour N° HBR-2026-04-1132",
        "Date facture : 24.04.2026",
        "Période séjour : 22.04 - 24.04.2026", "",
        "Chambre Deluxe 2 nuits                     820.00 CHF",
        "Restaurant + minibar                       145.00 CHF",
        "Taxe de séjour                              12.00 CHF",
        "Total TTC                                  977.00 CHF",
    ])
    rows.append(("47_facture_hotel.pdf", "facture_fournisseur", "Cabinet Avocat Vionnet & Partners",
                 "2026-04-24", "977.00", "Hotel Beau-Rivage Lausanne", "CHF",
                 "Facture hôtel — pas note frais (destinataire identifié)"))

    pdf = SAMPLES_DIR / "48_ticket_coop_pronto.pdf"
    _make_pdf(pdf, [
        "Coop Pronto", "Gare de Genève", "",
        "Ticket de caisse",
        "Date 23.04.2026 - 18:24", "",
        "Sandwich poulet                              8.50 CHF",
        "Boisson San Pellegrino                       4.00 CHF",
        "Pomme bio                                    1.80 CHF",
        "Total                                       14.30 CHF",
        "TVA incl. 8.1%                              1.07 CHF",
        "Carte VISA xxxx 7745",
    ], font_size=9)
    rows.append(("48_ticket_coop_pronto.pdf", "note_frais", "inconnu",
                 "2026-04-23", "14.30", "Coop Pronto", "CHF",
                 "Ticket caisse économat"))

    pdf = SAMPLES_DIR / "49_essence_socar.pdf"
    _make_pdf(pdf, [
        "SOCAR Energy Switzerland", "Station Genève-Acacias", "",
        "Quittance carburant",
        "Date 26.04.2026 09:14", "",
        "Sans plomb 95     45.20 L     2.18 CHF/L",
        "Sous-total                                  98.54 CHF",
        "Total TTC                                   98.54 CHF",
        "Carte BP xxxx 4421",
    ])
    rows.append(("49_essence_socar.pdf", "note_frais", "inconnu",
                 "2026-04-26", "98.54", "SOCAR Energy Switzerland", "CHF",
                 "Carburant véhicule professionnel"))

    pdf = SAMPLES_DIR / "50_courrier_relance.pdf"
    _make_pdf(pdf, [
        "Swisscom (Suisse) SA", "Service clientèle entreprises", "Postfach, 3050 Bern", "",
        "Restaurant Le Rivage SA", "Rue du Rhône 12, 1204 Genève", "", "",
        "Genève, le 28.04.2026", "",
        "RAPPEL DE PAIEMENT — Facture FCT-2026-03-08891", "",
        "Madame, Monsieur,", "",
        "Notre facture du 12.03.2026 d'un montant de CHF 287.00 reste impayée.",
        "Nous vous prions de procéder au règlement dans les 10 jours.",
        "À défaut de paiement, des frais de relance s'appliqueront.", "",
        "Avec nos salutations distinguées,",
        "Service comptabilité",
    ])
    rows.append(("50_courrier_relance.pdf", "courrier", "Restaurant Le Rivage SA",
                 "2026-04-28", "", "Swisscom (Suisse) SA", "CHF",
                 "Lettre de rappel — pas une facture"))

    return rows


def main() -> int:
    if not SAMPLES_DIR.exists():
        sys.exit(f"FATAL : {SAMPLES_DIR} n'existe pas")

    new_rows = gen()
    print(f"✓ {len(new_rows)} PDFs générés dans {SAMPLES_DIR.relative_to(REPO_ROOT)}")

    labels_path = SAMPLES_DIR / "labels.csv"
    existing_filenames: set[str] = set()
    existing_lines: list[str] = []
    if labels_path.exists():
        with labels_path.open(encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                if row and row[0]:
                    existing_filenames.add(row[0])
                    existing_lines.append(",".join(row))

    appended = 0
    with labels_path.open("a", encoding="utf-8") as f:
        for r in new_rows:
            if r[0] in existing_filenames:
                continue
            line = ",".join(str(v) for v in r)
            f.write(line + "\n")
            appended += 1

    print(f"✓ {appended} lignes ajoutées dans labels.csv")
    print(f"  Total corpus : {len(existing_filenames) + appended} docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
