"""Tests `fiduciaire_worker.bank_matcher` — Sprint 1 §3.9."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, audit_log, db  # noqa: E402
from fiduciaire_worker.bank_camt import init_bank_schema  # noqa: E402
from fiduciaire_worker.bank_matcher import (  # noqa: E402
    CONFIDENCE_AMOUNT_DATE,
    CONFIDENCE_FUZZY,
    CONFIDENCE_QR,
    DEFAULT_AUTO_APPLY_THRESHOLD,
    MatchReport,
    STRATEGY_AMOUNT_DATE,
    STRATEGY_FUZZY,
    STRATEGY_QR_EXACT,
    manually_link_transaction,
    match_bank_transactions,
    unlink_transaction,
)


def _setup(tmp_path: Path):
    conn = db.connect(tmp_path / "match.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    init_bank_schema(conn)
    return conn


def _insert_doc(conn, qr_ref: str | None = None, sha: str = "sha1") -> int:
    classif = {"qr_reference": qr_ref} if qr_ref else {}
    doc_id, _ = db.insert_document(conn, sha, "f.pdf", "/arch/f.pdf")
    conn.execute(
        "UPDATE documents SET classification_json=? WHERE id=?",
        (json.dumps(classif), doc_id),
    )
    return doc_id


def _insert_entry(conn, doc_id: int, client_id="cab-a", amount=100.0,
                  date="2026-04-15", state="validated") -> int:
    cur = conn.execute(
        "INSERT INTO accounting_entries "
        "(client_id, source_document_id, date, debit_account, credit_account, "
        " amount_chf, vat_code, vat_amount, description, "
        " confidence_account, confidence_vat, state) "
        "VALUES (?, ?, ?, '6510', '2000', ?, 'TN_NORM', 8.1, "
        "        'Facture', 0.9, 0.9, ?)",
        (client_id, doc_id, date, amount, state),
    )
    return int(cur.lastrowid)


def _insert_bank_tx(conn, cabinet_id="cab-a", client_id="cab-a",
                    amount=100.0, value_date="2026-04-15",
                    qr_ref=None, credit_debit="CRDT",
                    creditor_name=None, bank_ref="REF-1") -> int:
    cur = conn.execute(
        "INSERT INTO bank_transactions "
        "(cabinet_id, client_id, iban, value_date, amount_chf, currency, "
        " credit_debit, description, qr_reference, creditor_name, bank_ref) "
        "VALUES (?, ?, 'CH...', ?, ?, 'CHF', ?, '', ?, ?, ?)",
        (cabinet_id, client_id, value_date, amount, credit_debit,
         qr_ref, creditor_name, bank_ref),
    )
    return int(cur.lastrowid)


# --- Strategy 1 : QR-ref exact ----------------------------------------------


def test_qr_exact_match_auto_applies(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    qr = "210000000000003139471433000"
    doc_id = _insert_doc(conn, qr_ref=qr)
    entry_id = _insert_entry(conn, doc_id)
    tx_id = _insert_bank_tx(conn, qr_ref=qr, amount=287.00,
                            value_date="2026-04-20")

    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn,
    )
    assert isinstance(report, MatchReport)
    assert report.auto_matched == 1
    assert report.candidates[0].strategy == STRATEGY_QR_EXACT
    assert report.candidates[0].confidence == CONFIDENCE_QR

    row = conn.execute(
        "SELECT matched_document_id, match_strategy, match_confidence "
        "FROM bank_transactions WHERE id=?", (tx_id,),
    ).fetchone()
    assert row["matched_document_id"] == doc_id
    assert row["match_strategy"] == STRATEGY_QR_EXACT


def test_qr_no_match_when_qr_not_in_docs(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    _insert_doc(conn, qr_ref="OTHER-REF-123")
    _insert_bank_tx(conn, qr_ref="NOT-MATCHING-987",
                    amount=99.0, value_date="2026-04-20")
    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn,
    )
    # Pas de QR match, mais peut-être match amount/date
    # On crée pas d'entry dans ce test, donc no_match
    assert report.no_match >= 1 or report.auto_matched == 0


# --- Strategy 2 : amount + date ±3j -----------------------------------------


def test_amount_date_exact_match_auto_applies(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    doc_id = _insert_doc(conn)
    entry_id = _insert_entry(conn, doc_id, amount=287.00, date="2026-04-15")
    tx_id = _insert_bank_tx(conn, amount=287.00, value_date="2026-04-17")

    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn,
    )
    assert report.auto_matched == 0  # 0.85 < 0.9 default threshold
    assert report.suggestions_above_threshold == 1
    assert report.candidates[0].strategy == STRATEGY_AMOUNT_DATE


def test_amount_date_apply_below_threshold(tmp_path: Path) -> None:
    """Si auto_apply_threshold=0.8, le strategy 2 (0.85) passe en auto."""
    conn = _setup(tmp_path)
    doc_id = _insert_doc(conn)
    _insert_entry(conn, doc_id, amount=287.00, date="2026-04-15")
    tx_id = _insert_bank_tx(conn, amount=287.00, value_date="2026-04-17")

    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn,
        auto_apply_threshold=0.8,
    )
    assert report.auto_matched == 1
    row = conn.execute(
        "SELECT match_strategy, match_confidence "
        "FROM bank_transactions WHERE id=?", (tx_id,),
    ).fetchone()
    assert row["match_strategy"] == STRATEGY_AMOUNT_DATE


def test_amount_date_outside_window_no_match(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    doc_id = _insert_doc(conn)
    _insert_entry(conn, doc_id, amount=100.0, date="2026-04-01")
    # 30 jours d'écart > 3j window
    _insert_bank_tx(conn, amount=100.0, value_date="2026-05-01")

    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn,
    )
    # Pourrait quand même hit strategy 3 (fuzzy ±5j) ? Non, 30j > 5j aussi
    assert report.candidates == [] or all(
        c.strategy != STRATEGY_AMOUNT_DATE for c in report.candidates
    )


# --- Strategy 3 : fuzzy ±2% ±5j ---------------------------------------------


def test_fuzzy_match_with_amount_tolerance(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    doc_id = _insert_doc(conn)
    _insert_entry(conn, doc_id, amount=100.00, date="2026-04-15")
    # Montant ±2% (98-102), date ±5j
    _insert_bank_tx(conn, amount=101.50, value_date="2026-04-19")

    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn,
        auto_apply_threshold=0.5,
    )
    # Strategy 2 (amount exact) ne matche pas car 101.50 ≠ 100.00
    # Strategy 3 (fuzzy ±2%) doit matcher
    assert len(report.candidates) >= 1
    fz = [c for c in report.candidates if c.strategy == STRATEGY_FUZZY]
    assert len(fz) == 1


# --- Multi-mandant isolation ------------------------------------------------


def test_multi_mandant_no_cross_matching(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    doc_a = _insert_doc(conn, qr_ref="QR-A", sha="sha-A")
    doc_b = _insert_doc(conn, qr_ref="QR-B", sha="sha-B")
    _insert_entry(conn, doc_a, client_id="cab-a")
    _insert_entry(conn, doc_b, client_id="cab-b")

    # bank_tx pour cab-a avec QR-B (du mandant B)
    tx_id = _insert_bank_tx(
        conn, cabinet_id="cab-a", client_id="cab-a",
        qr_ref="QR-B", amount=999, value_date="2026-04-15",
    )

    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn,
    )
    # Ne doit PAS matcher avec doc_b (cab-b)
    row = conn.execute(
        "SELECT matched_document_id FROM bank_transactions WHERE id=?",
        (tx_id,),
    ).fetchone()
    assert row["matched_document_id"] is None


# --- Dry run ----------------------------------------------------------------


def test_dry_run_no_persist(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    qr = "QR-DR-1"
    doc_id = _insert_doc(conn, qr_ref=qr)
    _insert_entry(conn, doc_id)
    tx_id = _insert_bank_tx(conn, qr_ref=qr, amount=100, value_date="2026-04-15")

    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn, dry_run=True,
    )
    assert report.auto_matched == 1  # comptabilisé dans le report
    row = conn.execute(
        "SELECT matched_document_id FROM bank_transactions WHERE id=?",
        (tx_id,),
    ).fetchone()
    assert row["matched_document_id"] is None  # mais non persisté


# --- Manual link / unlink ---------------------------------------------------


def test_manually_link_transaction(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    doc_id = _insert_doc(conn)
    entry_id = _insert_entry(conn, doc_id)
    tx_id = _insert_bank_tx(conn, amount=999, value_date="2026-04-15")

    manually_link_transaction(
        transaction_id=tx_id, document_id=doc_id,
        accounting_entry_id=entry_id, conn=conn,
        user_id="tanguy", reason="lien manuel via UI",
    )
    row = conn.execute(
        "SELECT matched_document_id, match_strategy, matched_by "
        "FROM bank_transactions WHERE id=?", (tx_id,),
    ).fetchone()
    assert row["matched_document_id"] == doc_id
    assert row["match_strategy"] == "manual"
    assert row["matched_by"] == "tanguy"


def test_unlink_transaction(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    doc_id = _insert_doc(conn)
    entry_id = _insert_entry(conn, doc_id)
    tx_id = _insert_bank_tx(conn)

    manually_link_transaction(
        transaction_id=tx_id, document_id=doc_id,
        accounting_entry_id=entry_id, conn=conn, user_id="t",
    )
    unlink_transaction(
        transaction_id=tx_id, conn=conn, user_id="t", reason="erreur match",
    )
    row = conn.execute(
        "SELECT matched_document_id, match_strategy "
        "FROM bank_transactions WHERE id=?", (tx_id,),
    ).fetchone()
    assert row["matched_document_id"] is None
    assert row["match_strategy"] is None


# --- Audit log hooks --------------------------------------------------------


def test_audit_log_on_auto_match(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    qr = "QR-AUDIT"
    doc_id = _insert_doc(conn, qr_ref=qr)
    _insert_entry(conn, doc_id)
    tx_id = _insert_bank_tx(conn, qr_ref=qr, amount=100, value_date="2026-04-15")

    match_bank_transactions(cabinet_id="cab-a", client_id=None, conn=conn)

    events = audit_log.get_events_for_entity(
        conn, "cab-a", "bank_transaction", tx_id,
    )
    assert len(events) == 1
    assert events[0].action == "matched"


def test_audit_log_on_manual_link(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    doc_id = _insert_doc(conn)
    entry_id = _insert_entry(conn, doc_id)
    tx_id = _insert_bank_tx(conn)

    manually_link_transaction(
        transaction_id=tx_id, document_id=doc_id,
        accounting_entry_id=entry_id, conn=conn, user_id="tanguy",
    )
    events = audit_log.get_events_for_entity(
        conn, "cab-a", "bank_transaction", tx_id,
    )
    assert any(e.action == "matched" for e in events)


# --- Report ------------------------------------------------------------------


def test_report_shape(tmp_path: Path) -> None:
    conn = _setup(tmp_path)
    report = match_bank_transactions(
        cabinet_id="cab-a", client_id=None, conn=conn,
    )
    assert isinstance(report, MatchReport)
    assert report.cabinet_id == "cab-a"
    assert report.duration_s >= 0
