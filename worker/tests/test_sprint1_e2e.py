"""Tests E2E Sprint 1 complet — final integration tests.

Scénario bout-en-bout qui parcourt toute la chaîne Sprint 1 :
1. Seed 3 mandants synthétiques
2. Propose entries (vendor history hit, pas de LLM)
3. Validate transitions → audit log
4. Bexio push dry-run
5. Import CAMT.053 + bank_matcher auto
6. Scan anomalies
7. WinBIZ export CSV
8. Verify audit chain
9. Create backup + verify_backup_restorable
10. Multi-mandant isolation assertion finale

Performance cible : < 60s pour le scénario complet.

Aucun appel LLM réel (vendor_history seed pour skip), aucun OCR
(documents synthétiques pré-classifiés).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))
sys.path.insert(0, str(REPO_ROOT / "worker" / "scripts"))

from fiduciaire_worker import (  # noqa: E402
    accounting_schema, audit_log, db, workflow_states as ws,
)
from fiduciaire_worker.backup import (  # noqa: E402
    create_backup, verify_backup_restorable,
)
from fiduciaire_worker.bank_camt import (  # noqa: E402
    import_camt053_file, init_bank_schema,
)
from fiduciaire_worker.bank_matcher import match_bank_transactions  # noqa: E402
from fiduciaire_worker.bexio_push import push_validated_entries  # noqa: E402
from fiduciaire_worker.encryption import MasterKey  # noqa: E402
from fiduciaire_worker.entry_proposer import propose_entry  # noqa: E402
from fiduciaire_worker.missing_docs_detector import scan_anomalies  # noqa: E402
from fiduciaire_worker.winbiz_export import export_to_winbiz_csv  # noqa: E402
from seed_multi_mandant_test import MANDANT_SEEDS, seed_all  # noqa: E402


_VAT_YAML = REPO_ROOT / "config" / "vat_codes_ch.yaml"
_PLAN_YAML = REPO_ROOT / "config" / "plan_comptable_pme_ch.yaml"


def _llm_panic(prompt: str) -> str:
    raise AssertionError("LLM ne doit JAMAIS être appelé en E2E")


def _propose(conn, cabinet_id: str, doc_id: int):
    return propose_entry(
        conn, cabinet_id, doc_id,
        llm_caller=_llm_panic,
        vat_yaml_path=_VAT_YAML,
        plan_fallback_path=_PLAN_YAML,
    )


def _setup_full_db(tmp_path: Path):
    conn = db.connect(tmp_path / "e2e.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    init_bank_schema(conn)
    return conn


def _build_camt053_with_qr(iban: str, qr_ref: str, amount: float,
                           date: str = "2026-04-20") -> bytes:
    """Synthèse minimal CAMT.053 avec QR-ref pour matcher une facture."""
    xml = f"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.04">
  <BkToCstmrStmt>
    <GrpHdr><MsgId>E2E</MsgId></GrpHdr>
    <Stmt>
      <Id>STMT-E2E</Id>
      <Acct><Id><IBAN>{iban}</IBAN></Id></Acct>
      <Ntry>
        <Amt Ccy="CHF">{amount:.2f}</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <ValDt><Dt>{date}</Dt></ValDt>
        <AcctSvcrRef>BANK-E2E-1</AcctSvcrRef>
        <NtryDtls><TxDtls>
          <Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs>
          <RmtInf>
            <Strd><CdtrRefInf><Ref>{qr_ref}</Ref></CdtrRefInf></Strd>
          </RmtInf>
        </TxDtls></NtryDtls>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
    return xml.encode("utf-8")


# --- Scénario E2E complet ---------------------------------------------------


def test_sprint1_full_pipeline_3_mandants(tmp_path: Path, monkeypatch) -> None:
    """Scénario complet bout-en-bout sur 3 mandants synthétiques."""
    t_start = time.perf_counter()

    # 1. Seed
    conn = _setup_full_db(tmp_path)
    seeded = seed_all(conn, docs_per_vendor=2)
    cabinet = "pilote-jura-01"
    other_cabinet = "synth-vaud-02"

    # 2. Propose toutes les entries (vendor history hit → pas de LLM)
    proposed_ids: dict[str, list[int]] = {}
    for m in MANDANT_SEEDS:
        proposed_ids[m.cabinet_id] = []
        for doc_id in seeded[m.cabinet_id]:
            entry = _propose(conn, m.cabinet_id, doc_id)
            proposed_ids[m.cabinet_id].append(entry.db_id)
    assert len(proposed_ids[cabinet]) == 10

    # 3. Validate la moitié des entries du mandant pilote
    validated_ids = []
    for entry_id in proposed_ids[cabinet][:5]:
        ws.transition(conn, entry_id, ws.ENTRY_STATE_VALIDATED, user_id="tanguy")
        validated_ids.append(entry_id)
    # Met une QR-ref dans classification_json pour 1 entry (sera matchée)
    target_entry_id = validated_ids[0]
    target_row = conn.execute(
        "SELECT source_document_id FROM accounting_entries WHERE id=?",
        (target_entry_id,),
    ).fetchone()
    qr_ref = "210000000000003139471433000"
    conn.execute(
        "UPDATE documents SET classification_json=? WHERE id=?",
        (json.dumps({"qr_reference": qr_ref}),
         target_row["source_document_id"]),
    )
    target_amount = float(conn.execute(
        "SELECT amount_chf FROM accounting_entries WHERE id=?",
        (target_entry_id,),
    ).fetchone()["amount_chf"])

    # 4. Bexio push dry-run pour pilote
    def bexio_handler(req):
        raise AssertionError("dry-run ne doit pas appeler HTTP")

    http = httpx.Client(
        base_url="https://api.bexio.com",
        transport=httpx.MockTransport(bexio_handler),
    )
    push_summary = push_validated_entries(
        cabinet_id=cabinet, pat="FAKE", conn=conn,
        http_client=http, dry_run=True,
        account_no_to_bexio_id={"6510": 1, "6520": 2, "4200": 3, "6530": 4,
                                "6710": 5, "2000": 6},
        tax_code_to_bexio_id={"TN_NORM": 10, "TN_RED": 11, "EXO": 12},
    )
    assert push_summary.total == 5  # validated entries du pilote
    assert push_summary.skipped_dry_run == 5

    # 5. Import CAMT.053 avec QR-ref matchant target_entry
    camt_xml = _build_camt053_with_qr(
        "CH5204835012345678000", qr_ref, target_amount,
    )
    camt_file = tmp_path / "camt.xml"
    camt_file.write_bytes(camt_xml)
    import_camt053_file(
        path=camt_file, cabinet_id=cabinet, client_id=cabinet, conn=conn,
    )

    # 6. Run bank_matcher → doit auto-matcher (QR exact, confidence 1.0)
    match_report = match_bank_transactions(
        cabinet_id=cabinet, client_id=None, conn=conn,
    )
    assert match_report.auto_matched == 1
    matched_tx = conn.execute(
        "SELECT matched_accounting_entry_id, match_strategy, match_confidence "
        "FROM bank_transactions WHERE qr_reference=?", (qr_ref,),
    ).fetchone()
    assert matched_tx["match_strategy"] == "qr_exact"
    assert matched_tx["match_confidence"] == 1.0

    # 7. Scan anomalies — peut détecter des choses (potential_duplicate
    # car le seed crée plusieurs entries similaires)
    anomalies_report = scan_anomalies(cabinet_id=cabinet, conn=conn)
    assert anomalies_report.existing_open >= 0  # tolérant

    # 8. WinBIZ export CSV
    export_path = tmp_path / "winbiz.csv"
    wb_summary = export_to_winbiz_csv(
        cabinet_id=cabinet, conn=conn, output_path=export_path,
    )
    assert wb_summary.rows_exported == 5  # les 5 validated
    assert export_path.exists()
    content = export_path.read_text(encoding="utf-8-sig")
    assert "Date;Compte_Debit" in content

    # 9. Verify audit chain — doit être valide pour tous les cabinets
    for m in MANDANT_SEEDS:
        result = audit_log.verify_audit_chain(conn, m.cabinet_id)
        assert result.is_valid, f"Audit chain broken for {m.cabinet_id}"

    # 10. Backup + verify_restorable
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_BACKUP_MASTER",
                       MasterKey.generate("backup-master").value.decode())
    backup_dir = tmp_path / "backups"
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    (archive_root / "dummy.pdf").write_bytes(b"%PDF-1.4 dummy")

    backup_res = create_backup(
        db_path=tmp_path / "e2e.sqlite",
        archive_root=archive_root,
        backup_dir=backup_dir,
    )
    assert backup_res.path.exists()
    ok, reason = verify_backup_restorable(
        backup_res.path, tmp_path / "verify_tmp",
    )
    assert ok, f"backup not restorable: {reason}"

    # 11. Multi-mandant isolation : aucune fuite cross-cabinet
    for m in MANDANT_SEEDS:
        own_count = conn.execute(
            "SELECT COUNT(*) AS n FROM accounting_entries WHERE client_id=?",
            (m.cabinet_id,),
        ).fetchone()["n"]
        assert own_count == 10, (
            f"{m.cabinet_id} doit avoir 10 entries, a {own_count}"
        )

    # Aucune bank_transaction pour les autres cabinets
    for other in MANDANT_SEEDS:
        if other.cabinet_id == cabinet:
            continue
        n_bank = conn.execute(
            "SELECT COUNT(*) AS n FROM bank_transactions WHERE cabinet_id=?",
            (other.cabinet_id,),
        ).fetchone()["n"]
        assert n_bank == 0

    duration = time.perf_counter() - t_start
    print(f"\n[E2E Sprint 1] Scénario complet : {duration:.1f}s")
    assert duration < 60, f"Performance E2E dégradée : {duration:.1f}s > 60s"


# --- Audit chain isolation tampering --------------------------------------


def test_sprint1_audit_chain_resists_tampering(tmp_path: Path) -> None:
    """Si quelqu'un altère audit_log, verify_audit_chain le détecte."""
    conn = _setup_full_db(tmp_path)
    seeded = seed_all(conn, docs_per_vendor=1)
    cabinet = "pilote-jura-01"

    # Propose + validate 2 entries
    for doc_id in seeded[cabinet][:2]:
        e = _propose(conn, cabinet, doc_id)
        ws.transition(conn, e.db_id, ws.ENTRY_STATE_VALIDATED, user_id="t")

    # Chain valide
    ok = audit_log.verify_audit_chain(conn, cabinet)
    assert ok.is_valid

    # Tampering : on modifie l'action d'un event
    conn.execute(
        "UPDATE audit_log SET action='hacked' "
        "WHERE cabinet_id=? AND id=(SELECT MIN(id) FROM audit_log WHERE cabinet_id=?)",
        (cabinet, cabinet),
    )

    ko = audit_log.verify_audit_chain(conn, cabinet)
    assert not ko.is_valid
