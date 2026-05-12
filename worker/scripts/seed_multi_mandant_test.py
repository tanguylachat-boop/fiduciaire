"""Seed 3 mandants synthétiques pour tests E2E multi-mandant + démo.

3 cabinets :
  - pilote-jura-01 : fournisseurs Suisse romande (Swisscom, Romande Energie)
  - synth-vaud-02 : fournisseurs Vaud (BKW, Coop, Sunrise)
  - synth-berne-03 : fournisseurs Berne (EW Bern, Manor, Salt)

Pour chaque mandant :
- 10 `documents` avec classification_json (fournisseur, montant, date)
- 5+ `bexio_sync` manual_entries (pour bootstrap vendor_account_history)
- `vendor_account_history` pré-calculé pour skip LLM dans les tests
- 3 comptes minimum dans bexio_sync entity_type='account'

Usage :
  python worker/scripts/seed_multi_mandant_test.py --db /tmp/test.sqlite
  python worker/scripts/seed_multi_mandant_test.py --db /tmp/test.sqlite --reset

Réutilisé par worker/tests/test_multi_mandant_e2e.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402


@dataclass
class VendorSeed:
    name: str
    account: str
    vat_code: str


@dataclass
class MandantSeed:
    cabinet_id: str
    vendors: list[VendorSeed]
    accounts_plan: list[tuple[str, str]]  # (code, label)


# Vendors DISTINCTS par mandant pour détecter toute fuite cross-tenant
# (si un vendor de A apparaît dans une query de B → bug isolation)
MANDANT_SEEDS: list[MandantSeed] = [
    MandantSeed(
        cabinet_id="pilote-jura-01",
        vendors=[
            VendorSeed("Swisscom AG", "6510", "TN_NORM"),
            VendorSeed("Romande Energie SA", "6520", "TN_NORM"),
            VendorSeed("Migros Lausanne", "4200", "TN_RED"),
            VendorSeed("CFF Mobilite", "6530", "TN_NORM"),
            VendorSeed("Helsana Jura", "6710", "EXO"),
        ],
        accounts_plan=[
            ("6510", "Telecommunications"),
            ("6520", "Energie"),
            ("4200", "Achats marchandises"),
            ("6530", "Frais deplacements"),
            ("6710", "Assurances"),
            ("2000", "Creanciers"),
        ],
    ),
    MandantSeed(
        cabinet_id="synth-vaud-02",
        vendors=[
            VendorSeed("BKW Energie AG", "6520", "TN_NORM"),
            VendorSeed("Coop Vevey", "4200", "TN_RED"),
            VendorSeed("Sunrise Communications", "6510", "TN_NORM"),
            VendorSeed("Mobiliere Vaud", "6710", "EXO"),
            VendorSeed("BVB Buses", "6530", "TN_NORM"),
        ],
        accounts_plan=[
            ("6510", "Telekommunikation"),
            ("6520", "Energie"),
            ("4200", "Wareneinkauf"),
            ("6530", "Reisespesen"),
            ("6710", "Versicherungen"),
            ("2000", "Kreditoren"),
        ],
    ),
    MandantSeed(
        cabinet_id="synth-berne-03",
        vendors=[
            VendorSeed("EWBerne AG", "6520", "TN_NORM"),
            VendorSeed("Manor Berne", "4200", "TN_RED"),
            VendorSeed("Salt Mobile SA", "6510", "TN_NORM"),
            VendorSeed("Generali Berne", "6710", "EXO"),
            VendorSeed("SBB Berne", "6530", "TN_NORM"),
        ],
        accounts_plan=[
            ("6510", "Telekom"),
            ("6520", "Energie"),
            ("4200", "Einkauf"),
            ("6530", "Spesen"),
            ("6710", "Vers"),
            ("2000", "Kred"),
        ],
    ),
]


def _seed_accounts(conn: sqlite3.Connection, m: MandantSeed) -> None:
    """Seed bexio_sync entity_type='account' pour le plan comptable."""
    for code, label in m.accounts_plan:
        payload = {"id": int(code), "account_no": code, "name": label,
                   "account_type": "actif" if code.startswith("1") else "charge"}
        conn.execute(
            "INSERT OR REPLACE INTO bexio_sync "
            "(client_id, entity_type, entity_id, payload_json, synced_at) "
            "VALUES (?, 'account', ?, ?, datetime('now'))",
            (m.cabinet_id, code, json.dumps(payload, ensure_ascii=False)),
        )


def _seed_documents_and_entries(
    conn: sqlite3.Connection, m: MandantSeed, docs_per_vendor: int,
) -> list[int]:
    """Crée `docs_per_vendor` documents par vendor + bexio_sync manual_entries pour bootstrap vendor_account_history."""
    doc_ids: list[int] = []
    base_date = "2026-04-01"
    for vendor_idx, v in enumerate(m.vendors):
        for i in range(docs_per_vendor):
            # SHA unique par doc : mandant + vendor + index (les SHA cross-mandant doivent rester distincts)
            sha = hashlib.sha256(
                f"{m.cabinet_id}|{v.name}|{i}".encode()
            ).hexdigest()
            filename = f"{m.cabinet_id}_v{vendor_idx}_d{i}.pdf"
            archive_path = f"data/archive/{m.cabinet_id}/{sha}.pdf"
            amount = 100.0 + 10 * vendor_idx + i

            classification = {
                "type": "facture_fournisseur",
                "client": m.cabinet_id,
                "fournisseur": v.name,
                "date": base_date,
                "montant_chf": amount,
                "montant_tva": amount * 0.075,
            }

            cur = conn.execute(
                """INSERT INTO documents
                (sha256, original_filename, archive_path, ocr_text,
                 classification_json, type, client_slug, doc_date,
                 montant_chf, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sha, filename, archive_path,
                    f"Facture de {v.name} - montant CHF {amount:.2f}",
                    json.dumps(classification, ensure_ascii=False),
                    "facture_fournisseur", m.cabinet_id, base_date, amount,
                    "routed",
                ),
            )
            doc_ids.append(int(cur.lastrowid))

            # Seed manual_entry bexio_sync pour ce vendor (5+ occurrences pour confidence > 0.8)
            entry_payload = {
                "id": 1000 * (vendor_idx + 1) + i,
                "date": base_date,
                "description": v.name,
                "contact_id": f"{m.cabinet_id}-{vendor_idx}",
                "entries": [{
                    "debit_account_id": v.account,
                    "credit_account_id": "2000",
                    "tax_id": v.vat_code,
                    "amount": amount,
                }],
            }
            conn.execute(
                "INSERT OR REPLACE INTO bexio_sync "
                "(client_id, entity_type, entity_id, payload_json, synced_at) "
                "VALUES (?, 'manual_entry', ?, ?, datetime('now'))",
                (
                    m.cabinet_id, str(entry_payload["id"]),
                    json.dumps(entry_payload, ensure_ascii=False),
                ),
            )
    return doc_ids


def _seed_vendor_history(
    conn: sqlite3.Connection, m: MandantSeed, docs_per_vendor: int,
) -> None:
    """Précalcule vendor_account_history pour skip LLM dans les tests.

    Utilise directement les vendors connus du seed (au lieu de
    `build_history_from_bexio_cache`) pour garantir confidence >= 0.8.
    """
    for vendor_idx, v in enumerate(m.vendors):
        vendor_id = f"{m.cabinet_id}-{vendor_idx}"
        occurrences = max(5, docs_per_vendor)  # >= 5 → confidence 1.0
        conn.execute(
            "INSERT OR REPLACE INTO vendor_account_history "
            "(client_id, vendor_id, vendor_name, account, vat_code, "
            " occurrences, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, '2026-04-01')",
            (
                m.cabinet_id, vendor_id, v.name,
                v.account, v.vat_code, occurrences,
            ),
        )


def seed_all(
    conn: sqlite3.Connection, docs_per_vendor: int = 2,
) -> dict[str, list[int]]:
    """Seed les 3 mandants. Retourne {cabinet_id: [doc_ids]}."""
    out: dict[str, list[int]] = {}
    for m in MANDANT_SEEDS:
        _seed_accounts(conn, m)
        doc_ids = _seed_documents_and_entries(conn, m, docs_per_vendor)
        _seed_vendor_history(conn, m, docs_per_vendor)
        out[m.cabinet_id] = doc_ids
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed 3 mandants synthétiques pour tests E2E + démo.",
    )
    parser.add_argument("--db", type=Path, required=True,
                        help="Path SQLite cible (sera créée si absente).")
    parser.add_argument("--docs-per-vendor", type=int, default=2,
                        help="Documents par vendor (défaut 2 → 10 docs/mandant).")
    parser.add_argument("--reset", action="store_true",
                        help="Supprime la DB avant de seeder.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.reset and args.db.exists():
        args.db.unlink()
        print(f"✗ {args.db} supprimée")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    seeded = seed_all(conn, docs_per_vendor=args.docs_per_vendor)

    print(f"✓ DB seedée : {args.db}")
    for cabinet, doc_ids in seeded.items():
        print(f"  {cabinet}: {len(doc_ids)} documents")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
