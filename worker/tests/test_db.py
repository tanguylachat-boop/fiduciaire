"""Tests unitaires couche SQLite."""

from __future__ import annotations

from pathlib import Path

from fiduciaire_worker import db


def test_init_schema_idempotent(tmp_path: Path):
    p = tmp_path / "x.sqlite"
    conn = db.connect(p)
    db.init_schema(conn)
    db.init_schema(conn)  # 2e appel ne doit pas planter
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert {"documents", "actions"}.issubset(names)


def test_insert_document_idempotent(tmp_path: Path):
    conn = db.connect(tmp_path / "y.sqlite")
    db.init_schema(conn)
    a, new_a = db.insert_document(conn, "abc123", "f.pdf", "/arch/abc123.pdf")
    b, new_b = db.insert_document(conn, "abc123", "f.pdf", "/arch/abc123.pdf")
    assert new_a is True
    assert new_b is False
    assert a == b


def test_update_and_log(tmp_path: Path):
    conn = db.connect(tmp_path / "z.sqlite")
    db.init_schema(conn)
    doc_id, _ = db.insert_document(conn, "h1", "x.pdf", "/arch/h1.pdf")
    db.update_document(conn, doc_id, status=db.STATUS_ROUTED, type="facture_fournisseur")
    db.log_action(conn, doc_id, action="route", payload={"final": "/x"}, duration_ms=12)
    row = db.get_document(conn, doc_id)
    assert row["status"] == "routed"
    assert row["type"] == "facture_fournisseur"
    actions = conn.execute("SELECT action FROM actions WHERE document_id = ?", (doc_id,)).fetchall()
    assert {a["action"] for a in actions} == {"route"}
