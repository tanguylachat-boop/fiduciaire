"""Heuristique fournisseur → compte basée sur l'historique Bexio.

À partir des écritures historiques pulled (table `bexio_sync` entity_type='manual_entry'),
on détermine pour chaque fournisseur récurrent le compte le plus probable.

Confidence : f(occurrences, spread). Plus le fournisseur est vu sur un même compte,
plus la reco est confiante. Si plusieurs comptes (split), confidence dégradée.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass

from . import encryption as _enc


@dataclass
class VendorRecommendation:
    vendor_id: str
    vendor_name: str
    recommended_account: str
    recommended_vat_code: str
    occurrences: int
    last_seen: str
    confidence: float


def _confidence(top_count: int, second_count: int) -> float:
    """Score combinant fréquence + spread."""
    if second_count == 0:
        # pas de split, confidence pure-fréquence
        return min(1.0, 0.5 + 0.1 * top_count)
    spread = top_count - second_count
    # spread=0 (50/50) → 0.5 ; spread=3 → 0.65
    return min(0.95, 0.5 + 0.05 * spread)


def build_history_from_bexio_cache(
    conn: sqlite3.Connection,
    client_id: str,
) -> dict[str, VendorRecommendation]:
    """Construit la table vendor_account_history depuis les manual_entries en cache.

    Stratégie : groupe les entries par fournisseur (contact_id ou heuristique
    description), compte les occurrences (vendor, account) puis prend le top.
    """
    rows = conn.execute(
        "SELECT entity_id, payload_json FROM bexio_sync "
        "WHERE client_id = ? AND entity_type = 'manual_entry' "
        "ORDER BY synced_at DESC",
        (client_id,),
    ).fetchall()

    counts_account: dict[str, Counter] = defaultdict(Counter)
    counts_vat: dict[str, Counter] = defaultdict(Counter)
    last_seen: dict[str, str] = {}
    vendor_names: dict[str, str] = {}

    for row in rows:
        payload = json.loads(row["payload_json"])
        # Vendor identification : contact_id (champ Bexio) ou ref ou première ligne description
        vendor_id = str(payload.get("contact_id") or payload.get("reference_nr") or "")
        if not vendor_id:
            desc = (payload.get("description") or "").strip()
            vendor_id = (desc.split() or [""])[0].lower()
            if not vendor_id:
                continue

        vendor_name = (payload.get("description") or vendor_id)[:80]
        first_line = (payload.get("entries") or [{}])[0]
        account = str(first_line.get("debit_account_id") or "")
        vat = str(first_line.get("tax_id") or "TN_NORM")
        if not account:
            continue

        counts_account[vendor_id][account] += 1
        counts_vat[vendor_id][vat] += 1
        # last_seen = première vue (rows déjà ORDER BY synced_at DESC = plus récent en premier)
        last_seen.setdefault(vendor_id, payload.get("date", ""))
        vendor_names.setdefault(vendor_id, vendor_name)

    out: dict[str, VendorRecommendation] = {}
    for vendor_id, account_counter in counts_account.items():
        top_account, top_count = account_counter.most_common(1)[0]
        second_count = (
            account_counter.most_common(2)[1][1] if len(account_counter) > 1 else 0
        )
        top_vat = counts_vat[vendor_id].most_common(1)[0][0]
        rec = VendorRecommendation(
            vendor_id=vendor_id,
            vendor_name=vendor_names[vendor_id],
            recommended_account=top_account,
            recommended_vat_code=top_vat,
            occurrences=top_count,
            last_seen=last_seen[vendor_id],
            confidence=_confidence(top_count, second_count),
        )
        out[vendor_id] = rec
        # Sprint 1 §3.4-bis — chiffrement vendor_name (PII fournisseur).
        vendor_name_db = _enc.encrypt_column_value(
            vendor_names[vendor_id], client_id,
        )
        conn.execute(
            "INSERT OR REPLACE INTO vendor_account_history "
            "(client_id, vendor_id, vendor_name, account, vat_code, occurrences, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                client_id,
                vendor_id,
                vendor_name_db,
                top_account,
                top_vat,
                top_count,
                last_seen[vendor_id],
            ),
        )
    return out


def lookup(
    conn: sqlite3.Connection,
    client_id: str,
    vendor_name_or_id: str,
) -> VendorRecommendation | None:
    """Recherche par vendor_id exact OU vendor_name (LIKE %x%, case-insensitive).

    Sprint 1 §3.4-bis : si vendor_name est chiffré en DB, le fuzzy LIKE
    sur la colonne ne marche plus (le contenu chiffré est un token Fernet).
    Fallback : on charge tous les vendors du cabinet, decrypt en mémoire,
    puis fuzzy match sur le clair. Cost O(N) acceptable car N ≤ quelques
    centaines par cabinet.
    """
    if not vendor_name_or_id:
        return None
    needle = vendor_name_or_id.strip()

    # 1. exact match sur vendor_id (toujours en clair)
    row = conn.execute(
        "SELECT * FROM vendor_account_history WHERE client_id = ? AND vendor_id = ? "
        "ORDER BY occurrences DESC LIMIT 1",
        (client_id, needle),
    ).fetchone()
    if row is None:
        # 2. fuzzy : on tente d'abord SQL LIKE (compat valeurs en clair pré-chiffrement)
        row = conn.execute(
            "SELECT * FROM vendor_account_history "
            "WHERE client_id = ? AND lower(vendor_name) LIKE ? "
            "ORDER BY occurrences DESC LIMIT 1",
            (client_id, f"%{needle.lower()}%"),
        ).fetchone()
    if row is None:
        # 3. fuzzy in-memory si les vendors sont chiffrés
        candidates = conn.execute(
            "SELECT * FROM vendor_account_history WHERE client_id = ? "
            "ORDER BY occurrences DESC",
            (client_id,),
        ).fetchall()
        for c in candidates:
            stored_name = c["vendor_name"]
            if _enc.is_encrypted_column_value(stored_name):
                try:
                    decrypted = _enc.decrypt_column_value(stored_name, client_id)
                except Exception:
                    continue
            else:
                decrypted = stored_name
            if decrypted and needle.lower() in decrypted.lower():
                row = c
                break
    if row is None:
        return None
    vendor_name_plain = _enc.decrypt_column_value(row["vendor_name"], client_id)
    return VendorRecommendation(
        vendor_id=row["vendor_id"],
        vendor_name=vendor_name_plain,
        recommended_account=row["account"],
        recommended_vat_code=row["vat_code"],
        occurrences=row["occurrences"],
        last_seen=row["last_seen"],
        # Confidence reconstruit depuis occurrences seules (le split info n'est pas persisté).
        # Pessimiste vs build : OK car le lookup sert à décider "skip LLM ou pas".
        confidence=_confidence(row["occurrences"], 0),
    )
