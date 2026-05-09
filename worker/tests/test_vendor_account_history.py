"""Tests vendor_account_history — heuristique fournisseur → compte."""

from __future__ import annotations

import json
from pathlib import Path

from fiduciaire_worker import accounting_schema, db, vendor_account_history as vah


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    return conn


def _insert_manual_entry(
    conn, client_id, entry_id, contact_id, description, debit_account, vat="TN_NORM"
):
    payload = {
        "id": entry_id,
        "date": "2026-04-15",
        "description": description,
        "contact_id": contact_id,
        "entries": [
            {
                "debit_account_id": debit_account,
                "credit_account_id": "2000",
                "amount": 100.0,
                "tax_id": vat,
            }
        ],
    }
    conn.execute(
        "INSERT INTO bexio_sync (client_id, entity_type, entity_id, payload_json) "
        "VALUES (?, 'manual_entry', ?, ?)",
        (client_id, str(entry_id), json.dumps(payload)),
    )


def test_single_vendor_single_account_high_confidence(tmp_path):
    conn = _setup_db(tmp_path)
    for i in range(5):
        _insert_manual_entry(conn, "pilote", 100 + i, "swisscom-id", "Swisscom abo", "6510")
    history = vah.build_history_from_bexio_cache(conn, "pilote")
    assert "swisscom-id" in history
    rec = history["swisscom-id"]
    assert rec.recommended_account == "6510"
    assert rec.confidence == 1.0  # 5 occurrences, pas de split


def test_split_two_accounts_lower_confidence(tmp_path):
    conn = _setup_db(tmp_path)
    # 3 sur 6510, 2 sur 6700
    for i in range(3):
        _insert_manual_entry(conn, "pilote", 100 + i, "x-id", "X", "6510")
    for i in range(2):
        _insert_manual_entry(conn, "pilote", 200 + i, "x-id", "X", "6700")
    history = vah.build_history_from_bexio_cache(conn, "pilote")
    rec = history["x-id"]
    assert rec.recommended_account == "6510"  # le top
    # spread=1 → confidence basse
    assert 0.5 <= rec.confidence < 0.7


def test_lookup_unknown_returns_none(tmp_path):
    conn = _setup_db(tmp_path)
    result = vah.lookup(conn, "pilote", "Inconnu SA")
    assert result is None


def test_lookup_exact_vendor_id(tmp_path):
    conn = _setup_db(tmp_path)
    for i in range(3):
        _insert_manual_entry(conn, "pilote", 100 + i, "vendor-x", "Vendor X SA", "6510")
    vah.build_history_from_bexio_cache(conn, "pilote")
    result = vah.lookup(conn, "pilote", "vendor-x")
    assert result is not None
    assert result.recommended_account == "6510"
    assert result.occurrences == 3


def test_lookup_fuzzy_vendor_name(tmp_path):
    conn = _setup_db(tmp_path)
    for i in range(3):
        _insert_manual_entry(
            conn, "pilote", 100 + i, "swiss-id", "Swisscom Suisse SA abo", "6510"
        )
    vah.build_history_from_bexio_cache(conn, "pilote")
    # lookup par fragment de nom
    result = vah.lookup(conn, "pilote", "Swisscom")
    assert result is not None
    assert result.recommended_account == "6510"


def test_isolation_multi_mandant(tmp_path):
    """Vendor 'Swisscom' présent chez client-a et client-b → lookups isolés."""
    conn = _setup_db(tmp_path)
    # client-a : Swisscom → 6510
    for i in range(3):
        _insert_manual_entry(conn, "client-a", 100 + i, "swiss-id", "Swisscom", "6510")
    # client-b : Swisscom → 4400 (différent)
    for i in range(3):
        _insert_manual_entry(conn, "client-b", 200 + i, "swiss-id", "Swisscom", "4400")

    vah.build_history_from_bexio_cache(conn, "client-a")
    vah.build_history_from_bexio_cache(conn, "client-b")

    a = vah.lookup(conn, "client-a", "Swisscom")
    b = vah.lookup(conn, "client-b", "Swisscom")
    assert a.recommended_account == "6510"
    assert b.recommended_account == "4400"
