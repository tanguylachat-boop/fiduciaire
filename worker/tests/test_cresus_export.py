"""Tests `fiduciaire_worker.cresus_export` — Sprint 2.

Export XML générique Crésus avec idempotence via `cresus_exported_at`,
multi-mandant strict, decrypt des descriptions chiffrées.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.cresus_export import (  # noqa: E402
    DEFAULT_JOURNAL,
    ExportSummary,
    FORMAT_VERSION,
    XML_ENTRY_TAG,
    XML_ROOT_TAG,
    export_to_cresus_xml,
)


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "cresus.sqlite")
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


def test_cresus_export_writes_xml_with_expected_structure(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, description="Facture Swisscom")
    _insert_entry(conn, doc_id, description="Facture Romande", date="2026-04-16",
                  amount=250.50)

    out = tmp_path / "cresus.xml"
    summary = export_to_cresus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out,
    )

    assert summary.rows_exported == 2
    assert out.exists()

    tree = ET.parse(out)
    root = tree.getroot()
    assert root.tag == XML_ROOT_TAG
    assert root.attrib["cabinet_id"] == "cab-a"
    assert root.attrib["format_version"] == FORMAT_VERSION
    entries = root.findall(XML_ENTRY_TAG)
    assert len(entries) == 2
    # Champs obligatoires présents
    e0 = entries[0]
    for tag in ("Date", "Mandant", "CompteDebit", "CompteCredit",
                "MontantCHF", "Description", "CodeTVA", "Journal"):
        assert e0.find(tag) is not None, f"missing tag {tag}"
    assert e0.find("Mandant").text == "cab-a"
    assert e0.find("CompteDebit").text == "6510"
    assert e0.find("Journal").text == DEFAULT_JOURNAL
    # Descriptions présentes
    descs = {e.find("Description").text for e in entries}
    assert "Facture Swisscom" in descs
    assert "Facture Romande" in descs


def test_cresus_export_idempotence_marks_and_skips(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id)

    out1 = tmp_path / "1.xml"
    s1 = export_to_cresus_xml(cabinet_id="cab-a", conn=conn, output_path=out1)
    assert s1.rows_exported == 1

    out2 = tmp_path / "2.xml"
    s2 = export_to_cresus_xml(cabinet_id="cab-a", conn=conn, output_path=out2)
    assert s2.rows_exported == 0
    # cresus_exported_at posé
    row = conn.execute(
        "SELECT cresus_exported_at FROM accounting_entries WHERE client_id='cab-a'"
    ).fetchone()
    assert row["cresus_exported_at"] is not None


def test_cresus_export_multi_mandant_isolation(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, client_id="cab-a", description="A only")
    _insert_entry(conn, doc_id, client_id="cab-b", description="B leak")

    out_a = tmp_path / "a.xml"
    s_a = export_to_cresus_xml(cabinet_id="cab-a", conn=conn, output_path=out_a)
    assert s_a.rows_exported == 1

    tree = ET.parse(out_a)
    descs = [e.find("Description").text for e in tree.getroot().findall(XML_ENTRY_TAG)]
    assert descs == ["A only"]
    # cab-b reste non exporté
    row_b = conn.execute(
        "SELECT cresus_exported_at FROM accounting_entries WHERE client_id='cab-b'"
    ).fetchone()
    assert row_b["cresus_exported_at"] is None


def test_cresus_export_dry_run_no_file_no_mark(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    eid = _insert_entry(conn, doc_id)

    out = tmp_path / "dryrun.xml"
    s = export_to_cresus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out, dry_run=True,
    )
    assert s.rows_exported == 1
    assert not out.exists()
    row = conn.execute(
        "SELECT cresus_exported_at FROM accounting_entries WHERE id=?",
        (eid,),
    ).fetchone()
    assert row["cresus_exported_at"] is None


def test_cresus_export_decrypts_description(tmp_path: Path, monkeypatch) -> None:
    """Decrypt automatique d'une description chiffrée (marker enc:v1:)."""
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_DISABLED", "false")
    from fiduciaire_worker import encryption as enc

    conn, doc_id = _setup_db(tmp_path)
    # Génère et installe une clé en env (via secrets.py fallback) pour cab-a
    key = enc.MasterKey.generate("cab-a")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_CAB_A", key.value.decode())

    encrypted = enc.encrypt_column_value("Secret description", "cab-a")
    assert encrypted is not None and encrypted.startswith("enc:v1:"), encrypted

    _insert_entry(conn, doc_id, client_id="cab-a", description=encrypted)

    out = tmp_path / "dec.xml"
    s = export_to_cresus_xml(cabinet_id="cab-a", conn=conn, output_path=out)
    assert s.rows_exported == 1

    tree = ET.parse(out)
    desc = tree.getroot().find(XML_ENTRY_TAG).find("Description").text
    assert desc == "Secret description"


def test_cresus_export_date_range_filter(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, date="2026-03-01")
    _insert_entry(conn, doc_id, date="2026-04-15")
    _insert_entry(conn, doc_id, date="2026-05-30")

    out = tmp_path / "apr.xml"
    s = export_to_cresus_xml(
        cabinet_id="cab-a", conn=conn, output_path=out,
        date_from="2026-04-01", date_to="2026-04-30",
    )
    assert s.rows_exported == 1


def test_cresus_export_only_validated_state(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, description="OK", state="validated")
    _insert_entry(conn, doc_id, description="NOPE p", state="proposed")
    _insert_entry(conn, doc_id, description="NOPE r", state="rejected")

    out = tmp_path / "v.xml"
    s = export_to_cresus_xml(cabinet_id="cab-a", conn=conn, output_path=out)
    assert s.rows_exported == 1


def test_cresus_export_include_already_exported(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id)
    export_to_cresus_xml(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "1.xml",
    )
    s = export_to_cresus_xml(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "2.xml",
        include_already_exported=True,
    )
    assert s.rows_exported == 1


def test_cresus_export_no_path_when_not_dry_raises(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id)
    with pytest.raises(ValueError, match="output_path requis"):
        export_to_cresus_xml(cabinet_id="cab-a", conn=conn, output_path=None)
