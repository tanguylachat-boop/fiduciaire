"""Tests entry_proposer — orchestre vendor history + plan comptable + LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fiduciaire_worker import (
    accounting_schema,
    db,
    entry_proposer,
    plan_comptable_mapper,
    vendor_account_history as vah,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VAT_YAML = REPO_ROOT / "config" / "vat_codes_ch.yaml"
PLAN_YAML = REPO_ROOT / "config" / "plan_comptable_pme_ch.yaml"
PROMPT = REPO_ROOT / "worker" / "prompts" / "entry_proposer_v1.txt"


def _seed_doc(
    conn,
    sha,
    montant_chf=145.50,
    doc_date="2026-04-15",
    fournisseur="Swisscom (Suisse) SA",
    ocr_text="Swisscom abonnement Internet pro",
    classification=None,
) -> int:
    doc_id, _ = db.insert_document(conn, sha, "x.pdf", f"/arch/{sha}.pdf")
    cl = classification or {"fournisseur": fournisseur, "type": "facture_fournisseur"}
    db.update_document(
        conn,
        doc_id,
        montant_chf=montant_chf,
        doc_date=doc_date,
        ocr_text=ocr_text,
        classification_json=json.dumps(cl, ensure_ascii=False),
        type="facture_fournisseur",
    )
    return doc_id


def _setup(tmp_path):
    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    return conn


def _seed_vendor_history(conn, client_id, vendor_id, vendor_name, account, occurrences=5):
    for i in range(occurrences):
        payload = {
            "id": 1000 + i,
            "date": "2026-04-15",
            "description": vendor_name,
            "contact_id": vendor_id,
            "entries": [
                {"debit_account_id": account, "credit_account_id": "2000", "amount": 100.0}
            ],
        }
        conn.execute(
            "INSERT INTO bexio_sync (client_id, entity_type, entity_id, payload_json) "
            "VALUES (?, 'manual_entry', ?, ?)",
            (client_id, str(1000 + i), json.dumps(payload)),
        )
    vah.build_history_from_bexio_cache(conn, client_id)


def test_vendor_history_shortcut_skips_llm(tmp_path):
    conn = _setup(tmp_path)
    _seed_vendor_history(conn, "pilote-jura-01", "swisscom", "Swisscom", "6510", 5)
    doc_id = _seed_doc(conn, "doc-1", fournisseur="Swisscom")

    # llm_caller fail si appelé : on doit prendre le shortcut
    def llm_should_not_be_called(prompt):
        raise AssertionError("LLM appelé alors que vendor history avait haute confiance")

    entry = entry_proposer.propose_entry(
        conn,
        "pilote-jura-01",
        doc_id,
        plan=plan_comptable_mapper.PlanComptable.from_yaml_fallback(PLAN_YAML),
        prompt_template_path=PROMPT,
        vat_yaml_path=VAT_YAML,
        plan_fallback_path=PLAN_YAML,
        llm_caller=llm_should_not_be_called,
    )
    assert entry.debit_account == "6510"
    assert entry.sources["account"] == "vendor_history"
    assert entry.confidence_account >= 0.8


def test_unknown_vendor_falls_back_to_llm(tmp_path):
    conn = _setup(tmp_path)
    doc_id = _seed_doc(
        conn,
        "doc-2",
        fournisseur="Inconnu Nouveau SA",
        ocr_text="Facture services divers",
    )

    def fake_llm(prompt):
        return json.dumps(
            {
                "debit_account": "6500",
                "credit_account": "2000",
                "vat_code": "TN_NORM",
                "description": "Facture inconnu nouveau",
                "confidence_account": 0.65,
                "confidence_vat": 0.6,
                "reasoning": "Fournisseur jamais vu, classement par défaut",
            }
        )

    entry = entry_proposer.propose_entry(
        conn,
        "pilote-jura-01",
        doc_id,
        plan=plan_comptable_mapper.PlanComptable.from_yaml_fallback(PLAN_YAML),
        prompt_template_path=PROMPT,
        vat_yaml_path=VAT_YAML,
        plan_fallback_path=PLAN_YAML,
        llm_caller=fake_llm,
    )
    assert entry.debit_account == "6500"
    assert entry.sources["account"] == "llm"


def test_invalid_llm_json_retries(tmp_path):
    conn = _setup(tmp_path)
    doc_id = _seed_doc(conn, "doc-3", fournisseur="Inconnu")

    calls = {"n": 0}

    def fake_llm(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return "pas du tout du json {invalid"
        return json.dumps(
            {
                "debit_account": "6500",
                "credit_account": "2000",
                "vat_code": "TN_NORM",
                "description": "Retry réussi",
                "confidence_account": 0.6,
                "confidence_vat": 0.5,
                "reasoning": "ok",
            }
        )

    entry = entry_proposer.propose_entry(
        conn,
        "pilote-jura-01",
        doc_id,
        plan=plan_comptable_mapper.PlanComptable.from_yaml_fallback(PLAN_YAML),
        prompt_template_path=PROMPT,
        vat_yaml_path=VAT_YAML,
        plan_fallback_path=PLAN_YAML,
        llm_caller=fake_llm,
    )
    assert calls["n"] == 2
    assert entry.debit_account == "6500"


def test_persisted_in_accounting_entries(tmp_path):
    conn = _setup(tmp_path)
    _seed_vendor_history(conn, "pilote-jura-01", "swisscom", "Swisscom", "6510", 5)
    doc_id = _seed_doc(conn, "doc-4", fournisseur="Swisscom")

    entry = entry_proposer.propose_entry(
        conn,
        "pilote-jura-01",
        doc_id,
        plan=plan_comptable_mapper.PlanComptable.from_yaml_fallback(PLAN_YAML),
        prompt_template_path=PROMPT,
        vat_yaml_path=VAT_YAML,
        plan_fallback_path=PLAN_YAML,
        llm_caller=lambda p: "{}",
    )
    assert entry.db_id is not None
    row = conn.execute(
        "SELECT * FROM accounting_entries WHERE id = ?", (entry.db_id,)
    ).fetchone()
    assert row["debit_account"] == "6510"
    assert row["state"] == "proposed"
    assert row["client_id"] == "pilote-jura-01"


def test_isolation_multi_mandant(tmp_path):
    """2 mandants, mêmes fournisseurs, comptes différents → propositions isolées."""
    conn = _setup(tmp_path)
    _seed_vendor_history(conn, "client-a", "swisscom", "Swisscom", "6510", 5)
    _seed_vendor_history(conn, "client-b", "swisscom", "Swisscom", "4400", 5)

    doc_a = _seed_doc(conn, "doc-a", fournisseur="Swisscom")
    doc_b = _seed_doc(conn, "doc-b", fournisseur="Swisscom")

    entry_a = entry_proposer.propose_entry(
        conn, "client-a", doc_a,
        plan=plan_comptable_mapper.PlanComptable.from_yaml_fallback(PLAN_YAML),
        prompt_template_path=PROMPT, vat_yaml_path=VAT_YAML,
        plan_fallback_path=PLAN_YAML,
        llm_caller=lambda p: "{}",
    )
    entry_b = entry_proposer.propose_entry(
        conn, "client-b", doc_b,
        plan=plan_comptable_mapper.PlanComptable.from_yaml_fallback(PLAN_YAML),
        prompt_template_path=PROMPT, vat_yaml_path=VAT_YAML,
        plan_fallback_path=PLAN_YAML,
        llm_caller=lambda p: "{}",
    )
    assert entry_a.debit_account == "6510"
    assert entry_b.debit_account == "4400"


def test_unknown_document_raises(tmp_path):
    conn = _setup(tmp_path)
    with pytest.raises(ValueError):
        entry_proposer.propose_entry(
            conn, "pilote-jura-01", 99999,
            plan=plan_comptable_mapper.PlanComptable.from_yaml_fallback(PLAN_YAML),
            prompt_template_path=PROMPT, vat_yaml_path=VAT_YAML,
            plan_fallback_path=PLAN_YAML,
            llm_caller=lambda p: "{}",
        )
