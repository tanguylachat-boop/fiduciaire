"""Tests plan_comptable_mapper — chargement YAML/Bexio + suggestions keyword."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fiduciaire_worker import plan_comptable_mapper as pcm

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_YAML = REPO_ROOT / "config" / "plan_comptable_pme_ch.yaml"


def _mem_db_with_bexio_table() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE bexio_sync ("
        "  client_id TEXT, entity_type TEXT, entity_id TEXT, payload_json TEXT,"
        "  synced_at TEXT,"
        "  PRIMARY KEY (client_id, entity_type, entity_id)"
        ");"
    )
    return conn


def test_load_from_yaml_fallback():
    plan = pcm.PlanComptable.from_yaml_fallback(PLAN_YAML)
    assert plan.source == "yaml"
    assert "1020" in plan.accounts
    assert "6510" in plan.accounts


def test_get_account():
    plan = pcm.PlanComptable.from_yaml_fallback(PLAN_YAML)
    acc = plan.get_account("6510")
    assert acc is not None
    assert any(
        "internet" in kw.lower() or "swisscom" in kw.lower()
        for kw in acc["default_for_keywords"]
    )


def test_suggest_swisscom_returns_telecom():
    plan = pcm.PlanComptable.from_yaml_fallback(PLAN_YAML)
    suggestions = plan.suggest_accounts(
        "Facture Swisscom abonnement Internet et téléphonie pro"
    )
    assert len(suggestions) > 0
    assert suggestions[0].code == "6510"


def test_suggest_loyer_returns_charges_locaux():
    plan = pcm.PlanComptable.from_yaml_fallback(PLAN_YAML)
    suggestions = plan.suggest_accounts("Loyer mensuel locaux commerciaux")
    assert suggestions[0].code == "6000"


def test_suggest_carburant_returns_vehicules():
    plan = pcm.PlanComptable.from_yaml_fallback(PLAN_YAML)
    suggestions = plan.suggest_accounts("Carburant essence diesel station")
    assert suggestions[0].code == "6300"


def test_suggest_unknown_returns_empty():
    plan = pcm.PlanComptable.from_yaml_fallback(PLAN_YAML)
    suggestions = plan.suggest_accounts("aaa bbb ccc xyz random")
    assert suggestions == []


def test_from_bexio_cache_empty_returns_none():
    conn = _mem_db_with_bexio_table()
    plan = pcm.PlanComptable.from_bexio_cache(conn, "pilote-jura-01")
    assert plan is None


def test_from_bexio_cache_populated():
    conn = _mem_db_with_bexio_table()
    conn.execute(
        "INSERT INTO bexio_sync VALUES (?, 'account', ?, ?, datetime('now'))",
        (
            "pilote-jura-01",
            "1020",
            json.dumps({"account_no": "1020", "name": "Banque", "account_type": "actif"}),
        ),
    )
    plan = pcm.PlanComptable.from_bexio_cache(conn, "pilote-jura-01")
    assert plan is not None
    assert plan.source == "bexio"
    assert "1020" in plan.accounts
    assert plan.accounts["1020"]["label_fr"] == "Banque"


def test_bexio_cache_filtered_by_client_id():
    """Multi-mandant : pull client A ne doit pas voir les comptes client B."""
    conn = _mem_db_with_bexio_table()
    conn.execute(
        "INSERT INTO bexio_sync VALUES (?, 'account', ?, ?, datetime('now'))",
        ("client-a", "1020", json.dumps({"account_no": "1020", "name": "Banque A"})),
    )
    conn.execute(
        "INSERT INTO bexio_sync VALUES (?, 'account', ?, ?, datetime('now'))",
        ("client-b", "1020", json.dumps({"account_no": "1020", "name": "Banque B"})),
    )
    plan_a = pcm.PlanComptable.from_bexio_cache(conn, "client-a")
    plan_b = pcm.PlanComptable.from_bexio_cache(conn, "client-b")
    assert plan_a.accounts["1020"]["label_fr"] == "Banque A"
    assert plan_b.accounts["1020"]["label_fr"] == "Banque B"
