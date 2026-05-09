"""Seed des écritures comptables démo pour le dashboard /(poc)/entries.

Utilisé quand Bexio n'est pas accessible (Phase 2 reportée). Crée 8 documents
synthétiques + 8 écritures proposées variées (vendor history, LLM, validated,
rejected) pour démontrer le workflow Loom.

Usage:
    python worker/scripts/seed_demo_entries.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402

CLIENT_ID = "cabinet-pilote-01"
DOC_DIR = "data/archive"

DEMO_DOCS = [
    {
        "sha256": "demo01" + "0" * 58,
        "filename": "01_swisscom_qrbill.pdf",
        "doc_date": "2026-04-12",
        "montant": 287.00,
        "fournisseur": "Swisscom (Schweiz) AG",
    },
    {
        "sha256": "demo02" + "0" * 58,
        "filename": "02_migros_economat.pdf",
        "doc_date": "2026-04-08",
        "montant": 87.40,
        "fournisseur": "Migros Genève",
    },
    {
        "sha256": "demo03" + "0" * 58,
        "filename": "03_swisspost_rechnung.pdf",
        "doc_date": "2026-04-05",
        "montant": 142.20,
        "fournisseur": "Die Schweizerische Post AG",
    },
    {
        "sha256": "demo04" + "0" * 58,
        "filename": "04_romande_energie_t2.pdf",
        "doc_date": "2026-04-15",
        "montant": 542.30,
        "fournisseur": "Romande Énergie SA",
    },
    {
        "sha256": "demo05" + "0" * 58,
        "filename": "05_helsana_assurance.pdf",
        "doc_date": "2026-04-01",
        "montant": 1872.00,
        "fournisseur": "Helsana Versicherungen AG",
    },
    {
        "sha256": "demo06" + "0" * 58,
        "filename": "06_lieferant_imprimante_de.pdf",
        "doc_date": "2026-04-18",
        "montant": 1240.00,
        "fournisseur": "Druckerei Müller GmbH",
    },
    {
        "sha256": "demo07" + "0" * 58,
        "filename": "07_avs_cotisations_t2.pdf",
        "doc_date": "2026-04-22",
        "montant": 4250.00,
        "fournisseur": "Caisse cantonale AVS Genève",
    },
    {
        "sha256": "demo08" + "0" * 58,
        "filename": "08_freelance_designer.pdf",
        "doc_date": "2026-04-20",
        "montant": 3800.00,
        "fournisseur": "Studio Lemonpix Sàrl",
    },
]

DEMO_ENTRIES = [
    # 6 proposed (cœur du workflow Loom), 1 validated (déjà cliqué), 1 rejected
    {
        "doc_idx": 0,
        "debit_account": "6510",
        "credit_account": "2000",
        "vat_code": "TN_NORM",
        "vat_amount": 21.93,
        "description": "Swisscom abonnement Internet+téléphone",
        "confidence_account": 0.92,
        "confidence_vat": 0.95,
        "reasoning": "Vendor history match (12 occurrences sur 6510). VAT: ratio TVA/HT = 8.1% détecté.",
        "sources": {"account": "vendor_history", "vat_code": "detector"},
        "state": "proposed",
    },
    {
        "doc_idx": 1,
        "debit_account": "6500",
        "credit_account": "2000",
        "vat_code": "TN_NORM",
        "vat_amount": 6.59,
        "description": "Migros économat fournitures bureau",
        "confidence_account": 0.78,
        "confidence_vat": 0.93,
        "reasoning": "LLM proposition (vendor inconnu en historique). Compte 6500 selon plan PME.",
        "sources": {"account": "llm", "vat_code": "detector"},
        "state": "proposed",
    },
    {
        "doc_idx": 2,
        "debit_account": "6500",
        "credit_account": "2000",
        "vat_code": "TN_NORM",
        "vat_amount": 10.86,
        "description": "SwissPost frais postaux T2",
        "confidence_account": 0.88,
        "confidence_vat": 0.95,
        "reasoning": "Vendor history match (8 occurrences sur 6500).",
        "sources": {"account": "vendor_history", "vat_code": "detector"},
        "state": "proposed",
    },
    {
        "doc_idx": 3,
        "debit_account": "6000",
        "credit_account": "2000",
        "vat_code": "TN_NORM",
        "vat_amount": 41.42,
        "description": "Romande Énergie T2 électricité bureau",
        "confidence_account": 0.95,
        "confidence_vat": 0.93,
        "reasoning": "Vendor history match (24 occurrences sur 6000) — fournisseur récurrent, haute confiance.",
        "sources": {"account": "vendor_history", "vat_code": "detector"},
        "state": "proposed",
    },
    {
        "doc_idx": 4,
        "debit_account": "5700",
        "credit_account": "2000",
        "vat_code": "EXO",
        "vat_amount": 0.0,
        "description": "Helsana assurance maladie collective T2",
        "confidence_account": 0.85,
        "confidence_vat": 0.98,
        "reasoning": "Vendor history match (4 occurrences). Code EXO détecté (assurances maladie exonérées).",
        "sources": {"account": "vendor_history", "vat_code": "detector"},
        "state": "proposed",
    },
    {
        "doc_idx": 5,
        "debit_account": "6700",
        "credit_account": "2000",
        "vat_code": "TN_NORM",
        "vat_amount": 94.69,
        "description": "Druckerei matériel imprimante service IT",
        "confidence_account": 0.62,
        "confidence_vat": 0.91,
        "reasoning": "LLM proposition (vendor inconnu). 6700 ou 1500 ? À valider humain.",
        "sources": {"account": "llm", "vat_code": "detector"},
        "state": "proposed",
    },
    {
        "doc_idx": 6,
        "debit_account": "5700",
        "credit_account": "2270",
        "vat_code": "EXO",
        "vat_amount": 0.0,
        "description": "AVS cotisations T2 employeur",
        "confidence_account": 0.97,
        "confidence_vat": 0.99,
        "reasoning": "Vendor history match (16 occurrences). Charges sociales exonérées TVA.",
        "sources": {"account": "vendor_history", "vat_code": "detector"},
        "state": "validated",
    },
    {
        "doc_idx": 7,
        "debit_account": "6900",
        "credit_account": "2000",
        "vat_code": "TN_NORM",
        "vat_amount": 290.00,
        "description": "Honoraires designer freelance",
        "confidence_account": 0.71,
        "confidence_vat": 0.88,
        "reasoning": "LLM proposition. Confiance modérée — vérifier compte (6900 honoraires vs 6800 sous-traitance).",
        "sources": {"account": "llm", "vat_code": "detector"},
        "state": "rejected",
    },
]


def main() -> int:
    db_path = REPO_ROOT / "data" / "fiduciaire.sqlite"
    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    print(f"Seeding demo entries pour {CLIENT_ID} dans {db_path}")

    # Upsert documents
    doc_ids: list[int] = []
    for doc in DEMO_DOCS:
        row = conn.execute(
            "SELECT id FROM documents WHERE sha256 = ?", (doc["sha256"],)
        ).fetchone()
        if row:
            doc_ids.append(int(row["id"]))
            continue
        cur = conn.execute(
            "INSERT INTO documents "
            "(sha256, original_filename, archive_path, doc_date, montant_chf, "
            " status, classification_json, type, client_slug) "
            "VALUES (?, ?, ?, ?, ?, 'classified', ?, 'facture_fournisseur', ?)",
            (
                doc["sha256"],
                doc["filename"],
                f"{DOC_DIR}/{doc['sha256']}.pdf",
                doc["doc_date"],
                doc["montant"],
                json.dumps(
                    {"fournisseur": doc["fournisseur"], "montant_ttc": doc["montant"]},
                    ensure_ascii=False,
                ),
                CLIENT_ID,
            ),
        )
        doc_ids.append(int(cur.lastrowid))
    print(f"  ✓ {len(doc_ids)} documents (idempotent)")

    # Insert entries idempotent : skip si entrée existe pour (client_id, source_doc, debit_account, amount)
    inserted = 0
    for entry in DEMO_ENTRIES:
        doc_id = doc_ids[entry["doc_idx"]]
        existing = conn.execute(
            "SELECT id FROM accounting_entries "
            "WHERE client_id=? AND source_document_id=? AND debit_account=? AND amount_chf=?",
            (
                CLIENT_ID,
                doc_id,
                entry["debit_account"],
                DEMO_DOCS[entry["doc_idx"]]["montant"],
            ),
        ).fetchone()
        if existing:
            continue
        cur = conn.execute(
            "INSERT INTO accounting_entries "
            "(client_id, source_document_id, date, debit_account, credit_account, "
            " amount_chf, vat_code, vat_amount, description, confidence_account, "
            " confidence_vat, reasoning, sources_json, state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                CLIENT_ID,
                doc_id,
                DEMO_DOCS[entry["doc_idx"]]["doc_date"],
                entry["debit_account"],
                entry["credit_account"],
                DEMO_DOCS[entry["doc_idx"]]["montant"],
                entry["vat_code"],
                entry["vat_amount"],
                entry["description"],
                entry["confidence_account"],
                entry["confidence_vat"],
                entry["reasoning"],
                json.dumps(entry["sources"], ensure_ascii=False),
                entry["state"],
            ),
        )
        eid = int(cur.lastrowid)
        # Pour les états "validated"/"rejected", logger une transition fictive
        if entry["state"] != "proposed":
            conn.execute(
                "INSERT INTO entry_state_changes "
                "(entry_id, from_state, to_state, user_id, reason) VALUES (?, ?, ?, ?, ?)",
                (
                    eid,
                    "proposed",
                    entry["state"],
                    "demo-user",
                    "validated as-is" if entry["state"] == "validated" else "Hors périmètre fiduciaire",
                ),
            )
        inserted += 1

    print(f"  ✓ {inserted} écritures insérées")
    print("\nDémo prête. Lance `npm run dev` puis ouvre /entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
