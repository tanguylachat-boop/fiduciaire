"""Tests `fiduciaire_worker.bank_camt` — Sprint 1 §3.9."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.bank_camt import (  # noqa: E402
    BankTransactionData,
    CamtImportSummary,
    get_transaction,
    get_unmatched_transactions,
    import_camt053_file,
    init_bank_schema,
    parse_camt053,
)


# --- Fixtures CAMT.053 synthétiques -----------------------------------------


def _camt053(iban: str, ntries: list[dict]) -> bytes:
    """Génère un XML CAMT.053 minimal multi-Ntry pour tests.

    `ntries` : liste de dicts avec clés (amount, currency, credit_debit,
    value_date, qr_ref, description, creditor_name, debtor_name, bank_ref).
    """
    ntry_blocks = []
    for n in ntries:
        qr = n.get("qr_ref")
        desc = n.get("description", "")
        cdtr = n.get("creditor_name")
        dbtr = n.get("debtor_name")
        bank_ref = n.get("bank_ref", "")
        rmt_strd = ""
        if qr:
            rmt_strd = f"""
              <Strd>
                <CdtrRefInf>
                  <Ref>{qr}</Ref>
                </CdtrRefInf>
              </Strd>"""
        rmt_ustrd = f"<Ustrd>{desc}</Ustrd>" if desc else ""
        rltd_parties = ""
        if cdtr:
            rltd_parties += f"<Cdtr><Nm>{cdtr}</Nm></Cdtr>"
        if dbtr:
            rltd_parties += f"<Dbtr><Nm>{dbtr}</Nm></Dbtr>"
        rltd_block = f"<RltdPties>{rltd_parties}</RltdPties>" if rltd_parties else ""
        ntry_blocks.append(f"""
      <Ntry>
        <Amt Ccy="{n.get('currency', 'CHF')}">{n['amount']}</Amt>
        <CdtDbtInd>{n.get('credit_debit', 'CRDT')}</CdtDbtInd>
        <ValDt><Dt>{n['value_date']}</Dt></ValDt>
        <AcctSvcrRef>{bank_ref}</AcctSvcrRef>
        <NtryDtls>
          <TxDtls>
            <Refs><EndToEndId>{n.get('end_to_end_id', '')}</EndToEndId></Refs>
            <RmtInf>{rmt_ustrd}{rmt_strd}</RmtInf>
            {rltd_block}
          </TxDtls>
        </NtryDtls>
      </Ntry>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.04">
  <BkToCstmrStmt>
    <GrpHdr><MsgId>TEST</MsgId></GrpHdr>
    <Stmt>
      <Id>STMT-1</Id>
      <Acct>
        <Id><IBAN>{iban}</IBAN></Id>
      </Acct>
      {"".join(ntry_blocks)}
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
    return xml.encode("utf-8")


# --- Parse ------------------------------------------------------------------


def test_parse_simple_credit_transaction() -> None:
    xml = _camt053("CH5204835012345678000", [
        {"amount": "287.00", "credit_debit": "CRDT",
         "value_date": "2026-04-15", "description": "Paiement Le Rivage",
         "qr_ref": "210000000000003139471433000",
         "creditor_name": "Swisscom (Suisse) SA",
         "debtor_name": "Restaurant Le Rivage SA",
         "bank_ref": "REF-001"},
    ])
    iban, txs = parse_camt053(xml)
    assert iban == "CH5204835012345678000"
    assert len(txs) == 1
    tx = txs[0]
    assert tx.amount_chf == 287.00
    assert tx.credit_debit == "CRDT"
    assert tx.value_date == "2026-04-15"
    assert tx.qr_reference == "210000000000003139471433000"
    assert tx.creditor_name == "Swisscom (Suisse) SA"
    assert tx.debtor_name == "Restaurant Le Rivage SA"
    assert tx.bank_ref == "REF-001"
    assert "Paiement Le Rivage" in tx.description


def test_parse_debit_is_negative() -> None:
    xml = _camt053("CH5204835012345678000", [
        {"amount": "150.00", "credit_debit": "DBIT",
         "value_date": "2026-04-10", "description": "Achat",
         "bank_ref": "REF-002"},
    ])
    _, txs = parse_camt053(xml)
    assert len(txs) == 1
    assert txs[0].amount_chf == -150.00
    assert txs[0].credit_debit == "DBIT"


def test_parse_multiple_ntries() -> None:
    xml = _camt053("CH...", [
        {"amount": "100", "value_date": "2026-04-01", "bank_ref": "A"},
        {"amount": "200", "value_date": "2026-04-02", "bank_ref": "B"},
        {"amount": "300", "value_date": "2026-04-03", "bank_ref": "C"},
    ])
    _, txs = parse_camt053(xml)
    assert len(txs) == 3
    assert [tx.bank_ref for tx in txs] == ["A", "B", "C"]


def test_parse_invalid_xml_raises() -> None:
    import xml.etree.ElementTree as ET
    with pytest.raises(ET.ParseError):
        parse_camt053(b"<not-xml>broken")


def test_parse_missing_stmt_raises() -> None:
    with pytest.raises(ValueError, match="Stmt"):
        parse_camt053(b'<?xml version="1.0"?><Document/>')


def test_parse_othr_id_fallback_iban_absent() -> None:
    """Si pas d'IBAN, fallback sur Acct/Id/Othr/Id (comptes anciens)."""
    xml = b"""<?xml version="1.0"?>
<Document>
  <BkToCstmrStmt>
    <Stmt>
      <Acct><Id><Othr><Id>OLD-ACC-123</Id></Othr></Id></Acct>
      <Ntry>
        <Amt Ccy="CHF">50</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <ValDt><Dt>2026-04-01</Dt></ValDt>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
    iban, txs = parse_camt053(xml)
    assert iban == "OLD-ACC-123"
    assert len(txs) == 1


# --- Import + DB ------------------------------------------------------------


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "bank.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    init_bank_schema(conn)
    return conn


def test_import_persists_to_db(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    xml = _camt053("CH5204835012345678000", [
        {"amount": "100", "value_date": "2026-04-01",
         "qr_ref": "210000000000000000001", "bank_ref": "X-001"},
        {"amount": "250", "value_date": "2026-04-02",
         "bank_ref": "X-002"},
    ])
    camt_file = tmp_path / "test.xml"
    camt_file.write_bytes(xml)

    summary = import_camt053_file(
        path=camt_file, cabinet_id="cab-a", client_id="client-1", conn=conn,
    )
    assert isinstance(summary, CamtImportSummary)
    assert summary.transactions_total == 2
    assert summary.transactions_inserted == 2
    assert summary.transactions_duplicates == 0

    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM bank_transactions WHERE cabinet_id='cab-a'"
    ).fetchone()
    assert rows["n"] == 2


def test_import_idempotent_no_duplicates(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    xml = _camt053("CH5204835012345678000", [
        {"amount": "100", "value_date": "2026-04-01", "bank_ref": "X-001"},
    ])
    f = tmp_path / "t.xml"
    f.write_bytes(xml)

    s1 = import_camt053_file(path=f, cabinet_id="c", client_id="m", conn=conn)
    s2 = import_camt053_file(path=f, cabinet_id="c", client_id="m", conn=conn)
    assert s1.transactions_inserted == 1
    assert s2.transactions_inserted == 0
    assert s2.transactions_duplicates == 1


def test_import_multi_mandant_isolation(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    xml = _camt053("CH5204835012345678000", [
        {"amount": "100", "value_date": "2026-04-01", "bank_ref": "X-001"},
    ])
    f = tmp_path / "t.xml"
    f.write_bytes(xml)

    # 2 cabinets différents : même fichier mais 2 entries indépendantes
    import_camt053_file(path=f, cabinet_id="cab-a", client_id="m1", conn=conn)
    import_camt053_file(path=f, cabinet_id="cab-b", client_id="m2", conn=conn)

    n_a = conn.execute(
        "SELECT COUNT(*) AS n FROM bank_transactions WHERE cabinet_id='cab-a'"
    ).fetchone()["n"]
    n_b = conn.execute(
        "SELECT COUNT(*) AS n FROM bank_transactions WHERE cabinet_id='cab-b'"
    ).fetchone()["n"]
    assert n_a == 1
    assert n_b == 1


# --- Query helpers ----------------------------------------------------------


def test_get_unmatched_transactions(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    xml = _camt053("CH...", [
        {"amount": "100", "value_date": "2026-04-01", "bank_ref": "A"},
        {"amount": "200", "value_date": "2026-04-02", "bank_ref": "B"},
    ])
    f = tmp_path / "t.xml"
    f.write_bytes(xml)
    import_camt053_file(path=f, cabinet_id="c", client_id="m", conn=conn)

    # Crée un document FK valid puis matche A
    doc_id, _ = db.insert_document(conn, "sha-x", "x.pdf", "/arch/x.pdf")
    conn.execute(
        "UPDATE bank_transactions SET matched_document_id=? "
        "WHERE bank_ref='A'", (doc_id,),
    )
    unmatched = get_unmatched_transactions(
        cabinet_id="c", client_id="m", conn=conn,
    )
    assert len(unmatched) == 1
    assert unmatched[0].bank_ref == "B"


def test_get_unmatched_filters_only_credits(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    xml = _camt053("CH...", [
        {"amount": "100", "credit_debit": "CRDT", "value_date": "2026-04-01",
         "bank_ref": "C1"},
        {"amount": "200", "credit_debit": "DBIT", "value_date": "2026-04-02",
         "bank_ref": "D1"},
    ])
    f = tmp_path / "t.xml"
    f.write_bytes(xml)
    import_camt053_file(path=f, cabinet_id="c", client_id="m", conn=conn)

    only_credits = get_unmatched_transactions(
        cabinet_id="c", client_id="m", conn=conn, only_credits=True,
    )
    assert len(only_credits) == 1
    assert only_credits[0].bank_ref == "C1"


# --- Multi-banque robustness ------------------------------------------------


def test_parse_handles_various_namespaces() -> None:
    """Versions camt.053.001.02 vs .04 vs .08 — namespace varie."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
  <BkToCstmrStmt>
    <Stmt>
      <Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>
      <Ntry>
        <Amt Ccy="CHF">42.50</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <ValDt><Dt>2026-05-01</Dt></ValDt>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
    iban, txs = parse_camt053(xml)
    assert iban == "CH9300762011623852957"
    assert len(txs) == 1
    assert txs[0].amount_chf == 42.50
