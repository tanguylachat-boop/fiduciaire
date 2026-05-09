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
        conn.execute(
            "INSERT OR REPLACE INTO vendor_account_history "
            "(client_id, vendor_id, vendor_name, account, vat_code, occurrences, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                client_id,
                vendor_id,
                vendor_names[vendor_id],
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
    """Recherche par vendor_id exact OU vendor_name (LIKE %x%, case-insensitive)."""
    if not vendor_name_or_id:
        return None
    needle = vendor_name_or_id.strip()

    # 1. exact match sur vendor_id
    row = conn.execute(
        "SELECT * FROM vendor_account_history WHERE client_id = ? AND vendor_id = ? "
        "ORDER BY occurrences DESC LIMIT 1",
        (client_id, needle),
    ).fetchone()
    if row is None:
        # 2. fuzzy sur vendor_name (LIKE)
        row = conn.execute(
            "SELECT * FROM vendor_account_history "
            "WHERE client_id = ? AND lower(vendor_name) LIKE ? "
            "ORDER BY occurrences DESC LIMIT 1",
            (client_id, f"%{needle.lower()}%"),
        ).fetchone()
    if row is None:
        return None
    return VendorRecommendation(
        vendor_id=row["vendor_id"],
        vendor_name=row["vendor_name"],
        recommended_account=row["account"],
        recommended_vat_code=row["vat_code"],
        occurrences=row["occurrences"],
        last_seen=row["last_seen"],
        # Confidence reconstruit depuis occurrences seules (le split info n'est pas persisté).
        # Pessimiste vs build : OK car le lookup sert à décider "skip LLM ou pas".
        confidence=_confidence(row["occurrences"], 0),
    )
