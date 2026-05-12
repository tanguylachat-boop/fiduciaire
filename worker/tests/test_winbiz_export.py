"""Tests `fiduciaire_worker.winbiz_export` — Sprint 1 §3.8.

CSV / XML export avec idempotence via `winbiz_exported_at`,
multi-mandant strict, decrypt des descriptions chiffrées.
"""

from __future__ import annotations

import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.winbiz_export import (  # noqa: E402
    CSV_HEADERS,
    DEFAULT_JOURNAL,
    ExportSummary,
    export_to_winbiz_csv,
    export_to_winbiz_xml,
)


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "wb.sqlite")
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


# --- CSV ---------------------------------------------------------------------


def test_csv_export_writes_headers_and_rows(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, description="Facture Swisscom")
    _insert_entry(conn, doc_id, description="Facture Romande", date="2026-04-16")

    output = tmp_path / "export.csv"
    summary = export_to_winbiz_csv(
        cabinet_id="cab-a", conn=conn, output_path=output,
    )

    assert summary.rows_exported == 2
    assert output.exists()
    with open(output, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)
        assert reader.fieldnames == CSV_HEADERS
    assert len(rows) == 2
    assert rows[0]["Description"] == "Facture Swisscom"
    assert rows[0]["Compte_Debit"] == "6510"
    assert rows[0]["Code_TVA"] == "TN_NORM"
    assert rows[0]["Montant"] == "100.00"
    assert rows[0]["Journal"] == DEFAULT_JOURNAL


def test_csv_export_idempotence_marks_exported(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    eid = _insert_entry(conn, doc_id)
    output = tmp_path / "e1.csv"
    s1 = export_to_winbiz_csv(cabinet_id="cab-a", conn=conn, output_path=output)
    assert s1.rows_exported == 1
    # 2e run : skip
    output2 = tmp_path / "e2.csv"
    s2 = export_to_winbiz_csv(cabinet_id="cab-a", conn=conn, output_path=output2)
    assert s2.rows_exported == 0


def test_csv_export_date_range_filter(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, date="2026-03-01")
    _insert_entry(conn, doc_id, date="2026-04-15")
    _insert_entry(conn, doc_id, date="2026-05-30")

    output = tmp_path / "april.csv"
    s = export_to_winbiz_csv(
        cabinet_id="cab-a", conn=conn, output_path=output,
        date_from="2026-04-01", date_to="2026-04-30",
    )
    assert s.rows_exported == 1


def test_csv_export_only_validated_state(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, description="OK", state="validated")
    _insert_entry(conn, doc_id, description="NOPE prop", state="proposed")
    _insert_entry(conn, doc_id, description="NOPE rej", state="rejected")

    output = tmp_path / "v.csv"
    s = export_to_winbiz_csv(cabinet_id="cab-a", conn=conn, output_path=output)
    assert s.rows_exported == 1


def test_csv_export_multi_mandant_isolation(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, client_id="cab-a", description="A only")
    _insert_entry(conn, doc_id, client_id="cab-b", description="B only")

    out_a = tmp_path / "a.csv"
    s_a = export_to_winbiz_csv(cabinet_id="cab-a", conn=conn, output_path=out_a)
    assert s_a.rows_exported == 1
    with open(out_a, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert rows[0]["Description"] == "A only"

    # cab-b's entry n'a pas été marquée exportée
    row_b = conn.execute(
        "SELECT winbiz_exported_at FROM accounting_entries WHERE client_id='cab-b'"
    ).fetchone()
    assert row_b["winbiz_exported_at"] is None


def test_csv_export_dry_run_no_file_no_mark(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    eid = _insert_entry(conn, doc_id)

    s = export_to_winbiz_csv(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "dryrun.csv",
        dry_run=True,
    )
    assert s.rows_exported == 1
    # Pas de fichier créé
    assert not (tmp_path / "dryrun.csv").exists()
    # Pas de mark
    row = conn.execute(
        "SELECT winbiz_exported_at FROM accounting_entries WHERE id=?",
        (eid,),
    ).fetchone()
    assert row["winbiz_exported_at"] is None


def test_csv_export_include_already_exported(tmp_path: Path) -> None:
    """Avec include_already_exported=True, on ré-exporte tout."""
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id)
    export_to_winbiz_csv(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "1.csv",
    )
    # 2e run avec include
    s = export_to_winbiz_csv(
        cabinet_id="cab-a", conn=conn, output_path=tmp_path / "2.csv",
        include_already_exported=True,
    )
    assert s.rows_exported == 1


def test_csv_export_no_path_when_not_dry_raises(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id)
    with pytest.raises(ValueError, match="output_path requis"):
        export_to_winbiz_csv(cabinet_id="cab-a", conn=conn, output_path=None)


# --- XML ---------------------------------------------------------------------


def test_xml_export_basic_structure(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, description="Facture 1")
    _insert_entry(conn, doc_id, description="Facture 2", date="2026-04-20")

    out = tmp_path / "ex.xml"
    s = export_to_winbiz_xml(cabinet_id="cab-a", conn=conn, output_path=out)
    assert s.rows_exported == 2
    assert out.exists()

    tree = ET.parse(out)
    root = tree.getroot()
    assert root.tag == "winbiz_export"
    assert root.attrib["cabinet_id"] == "cab-a"
    entries = root.findall("entry")
    assert len(entries) == 2
    desc_els = [e.find("description").text for e in entries]
    assert "Facture 1" in desc_els
    assert "Facture 2" in desc_els


def test_xml_export_multi_mandant_isolation(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    _insert_entry(conn, doc_id, client_id="cab-a")
    _insert_entry(conn, doc_id, client_id="cab-b")
    out = tmp_path / "iso.xml"
    s = export_to_winbiz_xml(cabinet_id="cab-a", conn=conn, output_path=out)
    assert s.rows_exported == 1


def test_xml_export_limit_cap(tmp_path: Path) -> None:
    conn, doc_id = _setup_db(tmp_path)
    for i in range(5):
        _insert_entry(conn, doc_id, description=f"e{i}")
    out = tmp_path / "lim.xml"
    s = export_to_winbiz_xml(
        cabinet_id="cab-a", conn=conn, output_path=out, limit=2,
    )
    assert s.rows_exported == 2
