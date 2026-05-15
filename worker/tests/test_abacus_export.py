"""Tests `fiduciaire_worker.abacus_export` — Sprint 2 Session 11.

Export XML inspiré AbaConnect avec idempotence via `abacus_exported_at`,
multi-mandant strict, decrypt des descriptions chiffrées, audit log live.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, audit_log, db  # noqa: E402


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "abacus.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    doc_id, _ = db.insert_document(conn, "sha1", "x.pdf", "/arch/x.pdf")
    return conn, doc_id


def _insert_entry(conn, doc_id: int, client_id: str = "cab-a",
                  date: str = "2026-04-15", amount: float = 100.0,
                  description: str = "Facture Swisscom",
                  state: str = "validated", debit: str = "6510",
                  credit: str = "2000", vat: str = "TN_NORM") -> int:
    cur = conn.execute(
        "INSERT INTO accounting_entries "
        "(client_id, source_document_id, date, debit_account, credit_account, "
        " amount_chf, vat_code, vat_amount, description, "
        " confidence_account, confidence_vat, state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.9, 0.9, ?)",
        (client_id, doc_id, date, debit, credit, amount, vat, amount * 0.081,
         description, state),
    )
    return int(cur.lastrowid)


# --- Tests -----------------------------------------------------------------


def test_abacus_export_writes_xml_with_expected_structure(
    tmp_path: Path,
) -> None:
    from fiduciaire_worker.abacus_export import (
        XML_ENTRY_TAG,
        XML_ROOT_TAG,
        FORMAT_VERSION,
        export_to_abacus_xml,
    )

    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, description="Facture Swisscom")
    _insert_entry(conn, doc_id, description="Facture Romande",
                  date="2026-04-16", amount=250.50)

    out = tmp_path / "abacus.xml"
    summary = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out,
    )

    assert summary.rows_exported == 2
    assert out.exists()

    tree = ET.parse(out)
    root = tree.getroot()
    assert root.tag == XML_ROOT_TAG  # "Data"
    assert root.attrib["cabinet_id"] == "cab-a"
    assert root.attrib["abacs_export_version"] == FORMAT_VERSION
    entries = root.findall(XML_ENTRY_TAG)  # "AccountingDocument"
    assert len(entries) == 2
    e0 = entries[0]
    for tag in (
        "DocumentDate", "Currency", "AccountNumber", "AccountNumberAgainst",
        "Amount", "Text", "VatCode", "ClientReference",
    ):
        assert e0.find(tag) is not None, f"missing tag {tag}"
    assert e0.find("Currency").text == "CHF"
    assert e0.find("AccountNumber").text == "6510"
    assert e0.find("AccountNumberAgainst").text == "2000"
    descs = {e.find("Text").text for e in entries}
    assert "Facture Swisscom" in descs
    assert "Facture Romande" in descs


def test_abacus_export_idempotence_marks_and_skips(tmp_path: Path) -> None:
    from fiduciaire_worker.abacus_export import export_to_abacus_xml

    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id)

    s1 = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "1.xml",
    )
    assert s1.rows_exported == 1

    s2 = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "2.xml",
    )
    assert s2.rows_exported == 0

    row = conn.execute(
        "SELECT abacus_exported_at FROM accounting_entries "
        "WHERE client_id='cab-a'"
    ).fetchone()
    assert row["abacus_exported_at"] is not None


def test_abacus_export_include_already_exported(tmp_path: Path) -> None:
    from fiduciaire_worker.abacus_export import export_to_abacus_xml

    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id)
    export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "1.xml",
    )
    s = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "2.xml",
        include_already_exported=True,
    )
    assert s.rows_exported == 1


def test_abacus_export_multi_mandant_isolation(tmp_path: Path) -> None:
    from fiduciaire_worker.abacus_export import (
        XML_ENTRY_TAG,
        export_to_abacus_xml,
    )

    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, client_id="cab-a", description="A only")
    _insert_entry(conn, doc_id, client_id="cab-b", description="B leak")

    out_a = tmp_path / "a.xml"
    s_a = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out_a,
    )
    assert s_a.rows_exported == 1
    tree = ET.parse(out_a)
    texts = [e.find("Text").text
             for e in tree.getroot().findall(XML_ENTRY_TAG)]
    assert texts == ["A only"]

    row_b = conn.execute(
        "SELECT abacus_exported_at FROM accounting_entries "
        "WHERE client_id='cab-b'"
    ).fetchone()
    assert row_b["abacus_exported_at"] is None


def test_abacus_export_date_range_filter(tmp_path: Path) -> None:
    from fiduciaire_worker.abacus_export import export_to_abacus_xml

    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, date="2026-03-01")
    _insert_entry(conn, doc_id, date="2026-04-15")
    _insert_entry(conn, doc_id, date="2026-05-30")

    out = tmp_path / "apr.xml"
    s = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out,
        date_from="2026-04-01", date_to="2026-04-30",
    )
    assert s.rows_exported == 1


def test_abacus_export_only_validated_state(tmp_path: Path) -> None:
    from fiduciaire_worker.abacus_export import export_to_abacus_xml

    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, description="OK", state="validated")
    _insert_entry(conn, doc_id, description="NOPE p", state="proposed")
    _insert_entry(conn, doc_id, description="NOPE r", state="rejected")

    out = tmp_path / "v.xml"
    s = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out,
    )
    assert s.rows_exported == 1


def test_abacus_export_decrypts_description(
    tmp_path: Path, monkeypatch,
) -> None:
    """Decrypt automatique d'une description chiffrée (marker enc:v1:)."""
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_DISABLED", "false")
    from fiduciaire_worker import encryption as enc
    from fiduciaire_worker.abacus_export import (
        XML_ENTRY_TAG,
        export_to_abacus_xml,
    )

    conn, doc_id = _setup_db(tmp_path)
    key = enc.MasterKey.generate("cab-a")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_CAB_A", key.value.decode())

    encrypted = enc.encrypt_column_value("Secret abacus desc", "cab-a")
    assert encrypted is not None and encrypted.startswith("enc:v1:")
    _insert_entry(conn, doc_id, client_id="cab-a", description=encrypted)

    out = tmp_path / "dec.xml"
    s = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out,
    )
    assert s.rows_exported == 1

    tree = ET.parse(out)
    text = tree.getroot().find(XML_ENTRY_TAG).find("Text").text
    assert text == "Secret abacus desc"


def test_abacus_export_dry_run_no_file_no_mark(tmp_path: Path) -> None:
    from fiduciaire_worker.abacus_export import export_to_abacus_xml

    conn, doc_id = _setup_db(tmp_path)
    eid = _insert_entry(conn, doc_id)

    out = tmp_path / "dry.xml"
    s = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out, dry_run=True,
    )
    assert s.rows_exported == 1
    assert not out.exists()
    row = conn.execute(
        "SELECT abacus_exported_at FROM accounting_entries WHERE id=?",
        (eid,),
    ).fetchone()
    assert row["abacus_exported_at"] is None


def test_abacus_export_no_path_when_not_dry_raises(tmp_path: Path) -> None:
    from fiduciaire_worker.abacus_export import export_to_abacus_xml

    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id)
    with pytest.raises(ValueError, match="output_path requis"):
        export_to_abacus_xml(
            cabinet_id="cab-a", conn=conn, output_path=None,
        )


def test_abacus_export_emits_audit_log_event_live(tmp_path: Path) -> None:
    """Mode live (dry_run=False, mark=True) doit append un event audit."""
    from fiduciaire_worker.abacus_export import export_to_abacus_xml

    conn, doc_id = _setup_db(tmp_path)
    audit_log.init_audit_schema(conn)
    _insert_entry(conn, doc_id)

    before_events = audit_log.list_events(conn, "cab-a")
    assert len(before_events) == 0

    out = tmp_path / "live.xml"
    s = export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out,
    )
    assert s.rows_exported == 1

    after_events = audit_log.list_events(conn, "cab-a")
    export_events = [e for e in after_events if e.action == "exported"]
    assert len(export_events) == 1
    ev = export_events[0]
    assert ev.entity_type == "abacus_export"
    assert "cab-a" in ev.entity_id
    assert "live.xml" in ev.entity_id
    assert ev.after_json is not None
    # Pas de leak de PAT
    assert "key" not in (ev.after_json or "").lower() or "rows_count" in ev.after_json


def test_abacus_export_dry_run_does_not_emit_audit(tmp_path: Path) -> None:
    """Dry-run ne doit PAS appeler audit log (pas d'export réel)."""
    from fiduciaire_worker.abacus_export import export_to_abacus_xml

    conn, doc_id = _setup_db(tmp_path)
    audit_log.init_audit_schema(conn)
    _insert_entry(conn, doc_id)

    export_to_abacus_xml(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "dry.xml",
        dry_run=True,
    )
    events = audit_log.list_events(conn, "cab-a")
    assert len([e for e in events if e.action == "exported"]) == 0
