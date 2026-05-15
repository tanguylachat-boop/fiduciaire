"""Tests `fiduciaire_worker.monthly_report_pdf` — Sprint 2 Session 11.

PDF reporting via WeasyPrint (HTML/CSS print). Réutilise `monthly_report.py`
(génération Markdown) sans dupliquer. Tests :
1. PDF généré non vide (taille > 1KB)
2. KPIs identiques en MD et PDF (vérification sur HTML intermédiaire)
3. Cross-mandant strict (PermissionError)
4. Decrypt automatique des descriptions chiffrées
5. Erreur explicite si weasyprint absent
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "report.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    return conn


def _doc(conn, filename: str = "vendor.pdf") -> int:
    doc_id, _ = db.insert_document(
        conn, f"sha-{filename}", filename, f"/arch/{filename}",
    )
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


def test_pdf_generated_non_empty(tmp_path: Path) -> None:
    """PDF généré, taille > 1KB, extension .pdf à côté du .md."""
    from fiduciaire_worker.monthly_report_pdf import generate_monthly_report_pdf

    conn = _setup_db(tmp_path)
    d = _doc(conn, "swisscom.pdf")
    _entry(conn, "cab-a", d, "2026-04-05", "6510", "2000", 100.0,
           description="Swisscom abo")
    _entry(conn, "cab-a", d, "2026-04-20", "1100", "3000", 1500.0,
           description="Facture client X")

    out_dir = tmp_path / "out"
    summary = generate_monthly_report_pdf(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=out_dir, conn=conn,
    )
    assert summary.pdf_path is not None
    assert summary.pdf_path.exists()
    assert summary.pdf_path.name == "cab-a_2026-04_report.pdf"
    # PDF binaire commence par %PDF-
    head = summary.pdf_path.read_bytes()[:5]
    assert head == b"%PDF-", f"not a PDF: {head!r}"
    # Non vide
    assert summary.pdf_path.stat().st_size > 1024, (
        f"PDF trop petit : {summary.pdf_path.stat().st_size} bytes"
    )
    # MD aussi généré (réutilise monthly_report.py)
    assert summary.md_path is not None
    assert summary.md_path.exists()


def test_pdf_contains_same_kpis_as_md(tmp_path: Path) -> None:
    """Vérifie que l'HTML intermédiaire contient les mêmes KPIs que le MD.

    On extrait le HTML via le helper interne `_md_to_html_document` pour
    éviter d'avoir à parser le PDF.
    """
    from fiduciaire_worker.monthly_report_pdf import (
        _md_to_html_document,
        generate_monthly_report_pdf,
    )

    conn = _setup_db(tmp_path)
    d = _doc(conn, "vendor.pdf")
    _entry(conn, "cab-a", d, "2026-04-05", "6510", "2000", 100.0,
           description="Swisscom abo")
    _entry(conn, "cab-a", d, "2026-04-20", "1100", "3000", 1500.0,
           description="Facture client X")

    summary = generate_monthly_report_pdf(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
    )
    md_text = summary.md_path.read_text(encoding="utf-8")
    html = _md_to_html_document(
        md_text, cabinet_label="Cabinet Test", period_label="avril 2026",
    )
    # KPIs présents en MD ET en HTML
    for needle in (
        "CA HT du mois",
        "Cumul YTD",
        "Position TVA estim",
        "Tr\u00e9sorerie estim",
        "Top 5 fournisseurs",
        "Annexe",
        "Swisscom abo",
        "Facture client X",
    ):
        assert needle in md_text, f"manquant en MD : {needle}"
        assert needle in html, f"manquant en HTML : {needle}"


def test_pdf_cross_mandant_strict(tmp_path: Path) -> None:
    """Cabinet ≠ client_id → PermissionError (hérité de monthly_report)."""
    from fiduciaire_worker.monthly_report_pdf import generate_monthly_report_pdf

    conn = _setup_db(tmp_path)
    with pytest.raises(PermissionError, match="(?i)cabinet"):
        generate_monthly_report_pdf(
            cabinet_id="cab-a", client_id="cab-b",
            year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
        )


def test_pdf_decrypts_descriptions(tmp_path: Path, monkeypatch) -> None:
    """Description chiffrée doit apparaître déchiffrée dans le PDF / HTML.

    On vérifie sur l'HTML intermédiaire (pdf parsing fragile).
    """
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_DISABLED", "false")
    from fiduciaire_worker import encryption as enc
    from fiduciaire_worker.monthly_report_pdf import (
        _md_to_html_document,
        generate_monthly_report_pdf,
    )

    conn = _setup_db(tmp_path)
    d = _doc(conn)
    key = enc.MasterKey.generate("cab-a")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_CAB_A", key.value.decode())

    encrypted = enc.encrypt_column_value("Secret libellé pdf", "cab-a")
    assert encrypted is not None and encrypted.startswith("enc:v1:")
    _entry(conn, "cab-a", d, "2026-04-15", "1100", "3000", 100.0,
           description=encrypted)

    summary = generate_monthly_report_pdf(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
    )
    md = summary.md_path.read_text(encoding="utf-8")
    html = _md_to_html_document(md, cabinet_label="X", period_label="avril 2026")
    assert "Secret libellé pdf" in md
    assert "Secret libellé pdf" in html
    assert "enc:v1:" not in md
    assert "enc:v1:" not in html


def test_pdf_explicit_error_when_weasyprint_missing(
    tmp_path: Path, monkeypatch,
) -> None:
    """Si weasyprint absent du sys.modules, on raise RuntimeError clair."""
    # Force ré-import propre
    import importlib
    import fiduciaire_worker.monthly_report_pdf as mod
    importlib.reload(mod)

    # Simule absence : monkeypatche _import_weasyprint pour qu'il raise ImportError
    def boom():
        raise ImportError("No module named 'weasyprint'")

    monkeypatch.setattr(mod, "_import_weasyprint", boom)

    conn = _setup_db(tmp_path)
    d = _doc(conn)
    _entry(conn, "cab-a", d, "2026-04-15", "1100", "3000", 100.0)

    with pytest.raises(RuntimeError, match="(?i)weasyprint"):
        mod.generate_monthly_report_pdf(
            cabinet_id="cab-a", client_id="cab-a",
            year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
        )


def test_pdf_includes_cabinet_label_and_period_header(tmp_path: Path) -> None:
    """Header avec nom cabinet + période doit apparaître en HTML."""
    from fiduciaire_worker.monthly_report_pdf import (
        _md_to_html_document,
        generate_monthly_report_pdf,
    )

    conn = _setup_db(tmp_path)
    d = _doc(conn)
    _entry(conn, "cab-a", d, "2026-04-15", "1100", "3000", 500.0)

    summary = generate_monthly_report_pdf(
        cabinet_id="cab-a", client_id="cab-a",
        year=2026, month=4, output_dir=tmp_path / "out", conn=conn,
        cabinet_label="Fiduciaire du Jura SA",
    )
    html = _md_to_html_document(
        summary.md_path.read_text(encoding="utf-8"),
        cabinet_label="Fiduciaire du Jura SA",
        period_label="avril 2026",
    )
    assert "Fiduciaire du Jura SA" in html
    assert "avril 2026" in html
