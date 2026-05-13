"""Tests `fiduciaire_worker.monthly_report` — Sprint 2.

Génération rapport Markdown : KPIs (CA, top vendors, TVA, trésorerie),
annexe avec decrypt automatique, multi-mandant strict, mois vide propre.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.monthly_report import generate_monthly_report  # noqa: E402


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "report.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    return conn


def _doc(conn, filename: str = "vendor.pdf") -> int:
    doc_id, _ = db.insert_document(conn, f"sha-{filename}", filename, f"/arch/{filename}")
    return doc_id


def _entry(conn, client_id, doc_id, date, debit, credit, amount,
           vat_code="TN_NORM", vat_amount=None, description="op",
           state="validated"):
    if vat_amount is None:
        vat_amount = round(amount * 0.081, 2)
    conn.execute(
        "INSERT INTO accounting_entries "
        "(client_id, source_document_id, date, debit_account, credit_account, "
        " amount_chf, vat_code, vat_amount, description, "
        " confidence_account, confidence_vat, state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.9, 0.9, ?)",
        (client_id, doc_id, date, debit, credit, amount, vat_code,
         vat_amount, description, state),
    )


# --- Tests -----------------------------------------------------------------


def test_monthly_report_writes_markdown_with_kpis(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    d_swiss = _doc(conn, "swisscom.pdf")
    d_rom = _doc(conn, "romande.pdf")
    d_sales = _doc(conn, "sales.pdf")
    # Achats avril (deductible TVA)
    _entry(conn, "cab-a", d_swiss, "2026-04-05", "6510", "2000", 100.0,
           description="Swisscom abo")
    _entry(conn, "cab-a", d_rom, "2026-04-15", "4000", "2000", 200.0,
           description="Romande Energie")
    # Vente avril (CA + TVA collectée)
    _entry(conn, "cab-a", d_sales, "2026-04-20", "1100", "3000", 1500.0,
           description="Facture client X")

    out_dir = tmp_path / "out"
    summary = generate_monthly_report(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=out_dir, conn=conn,
    )
    assert summary.md_path is not None
    assert summary.md_path.exists()
    assert summary.md_path.name == "cab-a_2026-04_report.md"

    md = summary.md_path.read_text(encoding="utf-8")
    # KPIs présents
    assert "CA HT du mois" in md
    assert "Cumul YTD" in md
    assert "Top 5 fournisseurs" in md
    assert "Position TVA estimée" in md
    assert "Trésorerie estimée" in md
    # Le CA HT mois vaut 1500 (compte 3000)
    assert "1'500.00 CHF" in md or "1,500.00" in md
    # Annexe contient les 3 lignes
    assert "Swisscom abo" in md
    assert "Romande Energie" in md
    assert "Facture client X" in md

    # KPIs calculés correctement
    assert summary.kpis.revenue_chf_month == pytest.approx(1500.0)
    assert summary.kpis.entries_count == 3
    # TVA collectée = vat_amount sur les ventes (3000 → 1500 * 0.081)
    assert summary.kpis.vat_collected_chf == pytest.approx(1500.0 * 0.081)


def test_monthly_report_top_vendors_ranked(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    d1 = _doc(conn, "vendor_A.pdf")
    d2 = _doc(conn, "vendor_B.pdf")
    d3 = _doc(conn, "vendor_C.pdf")
    _entry(conn, "cab-a", d1, "2026-04-01", "6510", "2000", 1000.0)
    _entry(conn, "cab-a", d1, "2026-04-02", "6510", "2000", 500.0)
    _entry(conn, "cab-a", d2, "2026-04-03", "4000", "2000", 800.0)
    _entry(conn, "cab-a", d3, "2026-04-04", "6510", "2000", 200.0)

    summary = generate_monthly_report(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
    )
    # Top 1 = vendor_A.pdf (1500 cumulé), top 2 = vendor_B.pdf (800)
    top = summary.kpis.top_vendors
    assert len(top) == 3
    assert top[0][0] == "vendor_A.pdf"
    assert top[0][1] == pytest.approx(1500.0)
    assert top[1][0] == "vendor_B.pdf"
    assert top[1][1] == pytest.approx(800.0)


def test_monthly_report_multi_mandant_strict_blocked(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    with pytest.raises(PermissionError, match="(?i)cabinet"):
        generate_monthly_report(
            cabinet_id="cab-a", client_id="cab-b",
            year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
        )


def test_monthly_report_isolates_data_between_cabinets(tmp_path: Path) -> None:
    """Si données existent pour cab-b mais report demandé pour cab-a, elles
    ne fuient pas même si le rapport est généré pour cab-a."""
    conn = _setup_db(tmp_path)
    d = _doc(conn)
    _entry(conn, "cab-a", d, "2026-04-15", "1100", "3000", 500.0,
           description="A revenue")
    _entry(conn, "cab-b", d, "2026-04-15", "1100", "3000", 9999.0,
           description="B revenue (leak?)")

    summary = generate_monthly_report(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
    )
    assert summary.kpis.revenue_chf_month == pytest.approx(500.0)
    md = summary.md_path.read_text(encoding="utf-8")
    assert "A revenue" in md
    assert "B revenue" not in md


def test_monthly_report_empty_month_produces_clean_sections(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    summary = generate_monthly_report(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
    )
    assert summary.kpis.entries_count == 0
    assert summary.kpis.revenue_chf_month == 0.0
    md = summary.md_path.read_text(encoding="utf-8")
    assert "Aucune donnée fournisseur" in md
    assert "Aucune écriture" in md


def test_monthly_report_decrypts_descriptions_in_annex(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_DISABLED", "false")
    from fiduciaire_worker import encryption as enc

    conn = _setup_db(tmp_path)
    d = _doc(conn)
    key = enc.MasterKey.generate("cab-a")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_CAB_A", key.value.decode())

    encrypted = enc.encrypt_column_value("Secret libellé", "cab-a")
    assert encrypted is not None and encrypted.startswith("enc:v1:")
    _entry(conn, "cab-a", d, "2026-04-15", "1100", "3000", 100.0,
           description=encrypted)

    summary = generate_monthly_report(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
    )
    md = summary.md_path.read_text(encoding="utf-8")
    assert "Secret libellé" in md
    assert "enc:v1:" not in md
