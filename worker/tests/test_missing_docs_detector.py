"""Tests `fiduciaire_worker.missing_docs_detector` — Sprint 1 §3.7."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.missing_docs_detector import (  # noqa: E402
    Anomaly,
    ScanReport,
    STATE_FALSE_POSITIVE,
    STATE_OPEN,
    STATE_RESOLVED,
    TYPE_POTENTIAL_DUPLICATE,
    TYPE_UNPAID_INVOICE,
    TYPE_VAT_NO_EVIDENCE,
    init_anomalies_schema,
    list_open_anomalies,
    mark_anomaly_false_positive,
    mark_anomaly_resolved,
    scan_anomalies,
)


def _setup(tmp_path: Path):
    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    init_anomalies_schema(conn)
    doc_id, _ = db.insert_document(conn, "sha1", "x.pdf", "/arch/x.pdf")
    # 2e document "placeholder" (archive_path vide) → simule justif manquant
    placeholder_id, _ = db.insert_document(conn, "sha-empty", "missing.pdf", "")
    return conn, doc_id, placeholder_id


def _insert(conn, doc_id, client_id="cab-a", date="2026-04-15",
            amount=100.0, vat="TN_NORM", vat_amount=8.1,
            state="validated", bexio_id=None, description="Facture"):
    cur = conn.execute(
        "INSERT INTO accounting_entries "
        "(client_id, source_document_id, date, debit_account, credit_account, "
        " amount_chf, vat_code, vat_amount, description, "
        " confidence_account, confidence_vat, state, bexio_id) "
        "VALUES (?, ?, ?, '6510', '2000', ?, ?, ?, ?, 0.9, 0.9, ?, ?)",
        (client_id, doc_id, date, amount, vat, vat_amount,
         description, state, bexio_id),
    )
    return int(cur.lastrowid)


# --- init schema -------------------------------------------------------------


def test_init_schema_idempotent(tmp_path: Path) -> None:
    conn, _doc, _ph = _setup(tmp_path)
    init_anomalies_schema(conn)  # 2x
    rows = conn.execute("SELECT COUNT(*) AS n FROM anomalies").fetchone()
    assert rows["n"] == 0


# --- vat_no_evidence ---------------------------------------------------------


def test_vat_no_evidence_detected(tmp_path: Path) -> None:
    conn, doc_id, ph_id = _setup(tmp_path)
    _insert(conn, ph_id, vat="TN_NORM", vat_amount=8.1)  # archive vide
    _insert(conn, doc_id, vat="TN_NORM", vat_amount=8.1)  # archive OK
    report = scan_anomalies(cabinet_id="cab-a", conn=conn,
                            rules=[TYPE_VAT_NO_EVIDENCE])
    assert report.new_anomalies == 1
    anos = list_open_anomalies(conn, "cab-a")
    assert len(anos) == 1
    assert anos[0].type == TYPE_VAT_NO_EVIDENCE


def test_vat_no_evidence_skips_exo(tmp_path: Path) -> None:
    conn, doc_id, ph_id = _setup(tmp_path)
    _insert(conn, ph_id, vat="EXO", vat_amount=0.0)
    report = scan_anomalies(cabinet_id="cab-a", conn=conn,
                            rules=[TYPE_VAT_NO_EVIDENCE])
    assert report.new_anomalies == 0


# --- potential_duplicate -----------------------------------------------------


def test_potential_duplicate_detected_within_window(tmp_path: Path) -> None:
    conn, doc_id, _ph = _setup(tmp_path)
    _insert(conn, doc_id, date="2026-04-15", amount=100.0,
            description="Swisscom AG")
    _insert(conn, doc_id, date="2026-04-17", amount=100.0,
            description="Swisscom AG")  # 2j d'écart
    report = scan_anomalies(cabinet_id="cab-a", conn=conn,
                            rules=[TYPE_POTENTIAL_DUPLICATE])
    assert report.new_anomalies == 1


def test_potential_duplicate_skipped_outside_window(tmp_path: Path) -> None:
    conn, doc_id, _ph = _setup(tmp_path)
    _insert(conn, doc_id, date="2026-04-01", amount=100.0,
            description="X")
    _insert(conn, doc_id, date="2026-05-01", amount=100.0,
            description="X")  # 30j d'écart
    report = scan_anomalies(cabinet_id="cab-a", conn=conn,
                            rules=[TYPE_POTENTIAL_DUPLICATE])
    assert report.new_anomalies == 0


# --- unpaid_invoice ----------------------------------------------------------


def test_unpaid_invoice_detected(tmp_path: Path, monkeypatch) -> None:
    conn, doc_id, _ph = _setup(tmp_path)
    # date il y a 90j, bexio_id null → flag
    old_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    _insert(conn, doc_id, date=old_date, bexio_id=None, state="validated")
    report = scan_anomalies(cabinet_id="cab-a", conn=conn,
                            rules=[TYPE_UNPAID_INVOICE])
    assert report.new_anomalies == 1


def test_unpaid_invoice_recent_skipped(tmp_path: Path) -> None:
    conn, doc_id, _ph = _setup(tmp_path)
    recent = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    _insert(conn, doc_id, date=recent, bexio_id=None, state="validated")
    report = scan_anomalies(cabinet_id="cab-a", conn=conn,
                            rules=[TYPE_UNPAID_INVOICE])
    assert report.new_anomalies == 0


def test_unpaid_invoice_with_bexio_id_skipped(tmp_path: Path) -> None:
    conn, doc_id, _ph = _setup(tmp_path)
    old = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    _insert(conn, doc_id, date=old, bexio_id="42", state="validated")
    report = scan_anomalies(cabinet_id="cab-a", conn=conn,
                            rules=[TYPE_UNPAID_INVOICE])
    assert report.new_anomalies == 0


# --- Idempotence -------------------------------------------------------------


def test_scan_idempotent_no_duplicates(tmp_path: Path) -> None:
    conn, doc_id, ph_id = _setup(tmp_path)
    _insert(conn, ph_id, vat="TN_NORM", vat_amount=8.1)
    s1 = scan_anomalies(cabinet_id="cab-a", conn=conn,
                        rules=[TYPE_VAT_NO_EVIDENCE])
    s2 = scan_anomalies(cabinet_id="cab-a", conn=conn,
                        rules=[TYPE_VAT_NO_EVIDENCE])
    assert s1.new_anomalies == 1
    assert s2.new_anomalies == 0
    assert s2.existing_open == 1


# --- Multi-mandant -----------------------------------------------------------


def test_multi_mandant_isolation(tmp_path: Path) -> None:
    conn, doc_id, ph_id = _setup(tmp_path)
    _insert(conn, ph_id, client_id="cab-a",
            vat="TN_NORM", vat_amount=8.1)
    _insert(conn, ph_id, client_id="cab-b",
            vat="TN_NORM", vat_amount=8.1)

    s_a = scan_anomalies(cabinet_id="cab-a", conn=conn,
                         rules=[TYPE_VAT_NO_EVIDENCE])
    s_b = scan_anomalies(cabinet_id="cab-b", conn=conn,
                         rules=[TYPE_VAT_NO_EVIDENCE])
    assert s_a.new_anomalies == 1
    assert s_b.new_anomalies == 1

    anos_a = list_open_anomalies(conn, "cab-a")
    anos_b = list_open_anomalies(conn, "cab-b")
    assert len(anos_a) == 1
    assert len(anos_b) == 1
    assert anos_a[0].cabinet_id == "cab-a"
    assert anos_b[0].cabinet_id == "cab-b"


# --- Workflow resolved / false_positive --------------------------------------


def test_mark_resolved(tmp_path: Path) -> None:
    conn, doc_id, ph_id = _setup(tmp_path)
    _insert(conn, ph_id, vat="TN_NORM", vat_amount=8.1)
    scan_anomalies(cabinet_id="cab-a", conn=conn,
                   rules=[TYPE_VAT_NO_EVIDENCE])
    anos = list_open_anomalies(conn, "cab-a")
    assert len(anos) == 1
    mark_anomaly_resolved(conn, anos[0].id, user_id="tanguy", reason="ok")
    # Plus dans open
    assert list_open_anomalies(conn, "cab-a") == []
    row = conn.execute(
        "SELECT state, resolved_by FROM anomalies WHERE id=?", (anos[0].id,),
    ).fetchone()
    assert row["state"] == STATE_RESOLVED
    assert row["resolved_by"] == "tanguy"


def test_mark_false_positive(tmp_path: Path) -> None:
    conn, doc_id, ph_id = _setup(tmp_path)
    _insert(conn, ph_id, vat="TN_NORM", vat_amount=8.1)
    scan_anomalies(cabinet_id="cab-a", conn=conn,
                   rules=[TYPE_VAT_NO_EVIDENCE])
    anos = list_open_anomalies(conn, "cab-a")
    mark_anomaly_false_positive(conn, anos[0].id, user_id="tanguy")
    assert list_open_anomalies(conn, "cab-a") == []


# --- ScanReport shape --------------------------------------------------------


def test_scan_report_shape(tmp_path: Path) -> None:
    conn, doc_id, ph_id = _setup(tmp_path)
    _insert(conn, ph_id, vat="TN_NORM", vat_amount=8.1)
    report = scan_anomalies(cabinet_id="cab-a", conn=conn)
    assert isinstance(report, ScanReport)
    assert report.cabinet_id == "cab-a"
    assert TYPE_VAT_NO_EVIDENCE in report.rules_run
    assert report.duration_s >= 0


# --- Sprint 1 §3.7 finition Session 7 (5 nouveaux tests) ---------------------


def _setup_with_bank(tmp_path: Path):
    from fiduciaire_worker.bank_camt import init_bank_schema
    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    init_anomalies_schema(conn)
    init_bank_schema(conn)
    doc_id, _ = db.insert_document(conn, "sha1", "x.pdf", "/arch/x.pdf")
    return conn, doc_id


def _insert_bank_tx(conn, cabinet_id="cab-a", client_id="cab-a",
                    amount=100.0, value_date="2026-04-15",
                    credit_debit="CRDT", matched_entry_id=None,
                    imported_offset_days=0):
    from datetime import datetime, timedelta
    imported_at = (datetime.now() - timedelta(days=imported_offset_days)).strftime(
        "%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO bank_transactions "
        "(cabinet_id, client_id, iban, value_date, amount_chf, currency, "
        " credit_debit, matched_accounting_entry_id, imported_at) "
        "VALUES (?, ?, 'CH...', ?, ?, 'CHF', ?, ?, ?)",
        (cabinet_id, client_id, value_date, amount, credit_debit,
         matched_entry_id, imported_at),
    )
    return int(cur.lastrowid)


def test_unpaid_invoice_overdue_detected_no_bank_match(tmp_path: Path) -> None:
    """Entry > 60j et aucune bank_transaction la matche → anomalie."""
    from fiduciaire_worker.missing_docs_detector import (
        TYPE_UNPAID_INVOICE_OVERDUE,
    )
    conn, doc_id = _setup_with_bank(tmp_path)
    old = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    _insert(conn, doc_id, date=old, state="validated")

    report = scan_anomalies(
        cabinet_id="cab-a", conn=conn, rules=[TYPE_UNPAID_INVOICE_OVERDUE],
    )
    assert report.new_anomalies == 1


def test_unpaid_invoice_overdue_skipped_when_matched(tmp_path: Path) -> None:
    """Si bank_transaction matche l'entry → pas d'anomalie."""
    from fiduciaire_worker.missing_docs_detector import (
        TYPE_UNPAID_INVOICE_OVERDUE,
    )
    conn, doc_id = _setup_with_bank(tmp_path)
    old = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    entry_id = _insert(conn, doc_id, date=old, state="validated")
    _insert_bank_tx(conn, matched_entry_id=entry_id)

    report = scan_anomalies(
        cabinet_id="cab-a", conn=conn, rules=[TYPE_UNPAID_INVOICE_OVERDUE],
    )
    assert report.new_anomalies == 0


def test_payment_without_invoice_detected_after_grace(tmp_path: Path) -> None:
    """Bank tx CRDT importée >7j sans match → anomalie."""
    from fiduciaire_worker.missing_docs_detector import (
        TYPE_PAYMENT_WITHOUT_INVOICE,
    )
    conn, doc_id = _setup_with_bank(tmp_path)
    _insert_bank_tx(
        conn, amount=500, credit_debit="CRDT", matched_entry_id=None,
        imported_offset_days=10,  # > 7j grace
    )
    report = scan_anomalies(
        cabinet_id="cab-a", conn=conn, rules=[TYPE_PAYMENT_WITHOUT_INVOICE],
    )
    assert report.new_anomalies == 1


def test_payment_without_invoice_skipped_within_grace(tmp_path: Path) -> None:
    """Bank tx récente (<7j) → pas encore flaggée (grace period)."""
    from fiduciaire_worker.missing_docs_detector import (
        TYPE_PAYMENT_WITHOUT_INVOICE,
    )
    conn, doc_id = _setup_with_bank(tmp_path)
    _insert_bank_tx(
        conn, amount=500, credit_debit="CRDT", matched_entry_id=None,
        imported_offset_days=3,
    )
    report = scan_anomalies(
        cabinet_id="cab-a", conn=conn, rules=[TYPE_PAYMENT_WITHOUT_INVOICE],
    )
    assert report.new_anomalies == 0


def test_finition_rules_silent_skip_when_no_bank_table(tmp_path: Path) -> None:
    """Si bank_transactions n'existe pas, les 2 nouvelles règles no-op."""
    from fiduciaire_worker.missing_docs_detector import (
        TYPE_UNPAID_INVOICE_OVERDUE, TYPE_PAYMENT_WITHOUT_INVOICE,
    )
    # Setup sans bank schema
    conn = db.connect(tmp_path / "no_bank.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    init_anomalies_schema(conn)
    doc_id, _ = db.insert_document(conn, "sha-x", "x.pdf", "/arch/x.pdf")
    old = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    _insert(conn, doc_id, date=old, state="validated")

    report = scan_anomalies(
        cabinet_id="cab-a", conn=conn,
        rules=[TYPE_UNPAID_INVOICE_OVERDUE, TYPE_PAYMENT_WITHOUT_INVOICE],
    )
    # No-op silent : 0 anomalies (pas de bank_transactions à scanner)
    assert report.new_anomalies == 0
