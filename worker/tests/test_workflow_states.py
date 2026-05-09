"""Tests workflow_states — transitions états entries + traçage."""

from __future__ import annotations

from pathlib import Path

import pytest

from fiduciaire_worker import accounting_schema, db, workflow_states as ws


def _setup_entry(tmp_path: Path) -> tuple:
    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    doc_id, _ = db.insert_document(conn, "h1", "x.pdf", "/arch/h1.pdf")
    cur = conn.execute(
        "INSERT INTO accounting_entries "
        "(client_id, source_document_id, date, debit_account, credit_account, "
        " amount_chf, vat_code, vat_amount, description, "
        " confidence_account, confidence_vat) "
        "VALUES ('pilote-jura-01', ?, '2026-04-15', '6510', '2000', 145.50, "
        "        'TN_NORM', 10.91, 'test', 0.9, 0.95)",
        (doc_id,),
    )
    return conn, int(cur.lastrowid)


def test_transition_proposed_to_validated(tmp_path):
    conn, entry_id = _setup_entry(tmp_path)
    ws.transition(conn, entry_id, ws.ENTRY_STATE_VALIDATED, user_id="tanguy", reason="ok")
    row = conn.execute(
        "SELECT state FROM accounting_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row["state"] == "validated"
    h = ws.history(conn, entry_id)
    assert len(h) == 1
    assert h[0]["from_state"] == "proposed"
    assert h[0]["to_state"] == "validated"
    assert h[0]["user_id"] == "tanguy"


def test_transition_proposed_to_rejected_requires_no_target(tmp_path):
    conn, entry_id = _setup_entry(tmp_path)
    ws.transition(conn, entry_id, ws.ENTRY_STATE_REJECTED, reason="mauvais compte")
    row = conn.execute(
        "SELECT state FROM accounting_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row["state"] == "rejected"


def test_transition_rejected_is_terminal(tmp_path):
    conn, entry_id = _setup_entry(tmp_path)
    ws.transition(conn, entry_id, ws.ENTRY_STATE_REJECTED)
    with pytest.raises(ws.InvalidTransition):
        ws.transition(conn, entry_id, ws.ENTRY_STATE_PROPOSED)
    with pytest.raises(ws.InvalidTransition):
        ws.transition(conn, entry_id, ws.ENTRY_STATE_VALIDATED)


def test_transition_validated_can_reopen_to_proposed(tmp_path):
    conn, entry_id = _setup_entry(tmp_path)
    ws.transition(conn, entry_id, ws.ENTRY_STATE_VALIDATED)
    ws.transition(conn, entry_id, ws.ENTRY_STATE_PROPOSED, reason="erreur de saisie")
    h = ws.history(conn, entry_id)
    assert len(h) == 2
    assert h[1]["from_state"] == "validated"
    assert h[1]["to_state"] == "proposed"


def test_unknown_entry_raises(tmp_path):
    conn = db.connect(tmp_path / "y.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    with pytest.raises(ws.InvalidTransition):
        ws.transition(conn, 99999, ws.ENTRY_STATE_VALIDATED)
