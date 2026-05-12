"""Tests `fiduciaire_worker.audit_log` — Sprint 1 §3.6.

Append-only chain hash. Détection tampering. Hooks workflow_states +
entry_proposer + bexio_push.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))
sys.path.insert(0, str(REPO_ROOT / "worker" / "scripts"))

from fiduciaire_worker import accounting_schema, db, workflow_states as ws  # noqa: E402
from fiduciaire_worker.audit_log import (  # noqa: E402
    ACTION_PROPOSED,
    ACTION_PUSHED,
    ACTION_VALIDATED,
    GENESIS_HASH,
    AuditEvent,
    ChainVerificationResult,
    export_audit_text,
    get_events_for_entity,
    init_audit_schema,
    list_events,
    log_audit_event,
    verify_audit_chain,
)


# --- Fixtures ----------------------------------------------------------------


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "audit.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    return conn


def _insert_entry(conn, client_id: str = "cab-a", state: str = "proposed") -> int:
    doc_id, _ = db.insert_document(conn, f"sha-{client_id}", "x.pdf", "/arch/x.pdf")
    cur = conn.execute(
        "INSERT INTO accounting_entries "
        "(client_id, source_document_id, date, debit_account, credit_account, "
        " amount_chf, vat_code, vat_amount, description, "
        " confidence_account, confidence_vat, state) "
        "VALUES (?, ?, '2026-04-15', '6510', '2000', 100.0, 'TN_NORM', 8.1, "
        "        'test', 0.9, 0.9, ?)",
        (client_id, doc_id, state),
    )
    return int(cur.lastrowid)


# --- Append + chain ----------------------------------------------------------


def test_init_schema_idempotent(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "x.sqlite")
    init_audit_schema(conn)
    init_audit_schema(conn)  # 2x → no error
    rows = conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()
    assert rows["n"] == 0


def test_first_event_prev_hash_is_genesis(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    log_audit_event(
        conn, cabinet_id="cab-a", entity_type="accounting_entry",
        entity_id=1, action="proposed",
    )
    row = conn.execute("SELECT prev_hash FROM audit_log WHERE id=1").fetchone()
    assert row["prev_hash"] == GENESIS_HASH


def test_chain_links_consecutive_events(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    id1 = log_audit_event(
        conn, cabinet_id="cab-a", entity_type="x", entity_id=1, action="a",
    )
    id2 = log_audit_event(
        conn, cabinet_id="cab-a", entity_type="x", entity_id=2, action="b",
    )
    row1 = conn.execute("SELECT current_hash FROM audit_log WHERE id=?",
                        (id1,)).fetchone()
    row2 = conn.execute("SELECT prev_hash FROM audit_log WHERE id=?",
                        (id2,)).fetchone()
    assert row2["prev_hash"] == row1["current_hash"]


def test_verify_chain_valid_after_appends(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    for i in range(5):
        log_audit_event(
            conn, cabinet_id="cab-a", entity_type="x",
            entity_id=i, action="step",
        )
    result = verify_audit_chain(conn, "cab-a")
    assert isinstance(result, ChainVerificationResult)
    assert result.is_valid is True
    assert result.total_events == 5


def test_verify_chain_detects_field_tampering(tmp_path: Path) -> None:
    """Modifier `action` d'une row passée doit invalider la chain."""
    conn = _setup_db(tmp_path)
    log_audit_event(
        conn, cabinet_id="cab-a", entity_type="x", entity_id=1, action="a",
    )
    log_audit_event(
        conn, cabinet_id="cab-a", entity_type="x", entity_id=2, action="b",
    )

    # Tampering : on modifie action du row 1 directement
    conn.execute("UPDATE audit_log SET action='hacked' WHERE id=1")

    result = verify_audit_chain(conn, "cab-a")
    assert result.is_valid is False
    assert result.first_invalid_id == 1


def test_verify_chain_detects_prev_hash_tampering(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    log_audit_event(
        conn, cabinet_id="cab-a", entity_type="x", entity_id=1, action="a",
    )
    log_audit_event(
        conn, cabinet_id="cab-a", entity_type="x", entity_id=2, action="b",
    )
    conn.execute("UPDATE audit_log SET prev_hash='deadbeef' WHERE id=2")

    result = verify_audit_chain(conn, "cab-a")
    assert result.is_valid is False
    assert result.first_invalid_id == 2


def test_verify_chain_empty_is_valid(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    result = verify_audit_chain(conn, "cab-empty")
    assert result.is_valid is True
    assert result.total_events == 0


# --- Multi-mandant isolation -------------------------------------------------


def test_chains_isolated_per_cabinet(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    # Cabinet A : 3 events
    for i in range(3):
        log_audit_event(conn, cabinet_id="cab-a", entity_type="x",
                        entity_id=i, action="a")
    # Cabinet B : 2 events
    for i in range(2):
        log_audit_event(conn, cabinet_id="cab-b", entity_type="x",
                        entity_id=i, action="a")

    # Tampering uniquement sur cab-a
    conn.execute("UPDATE audit_log SET action='hacked' WHERE cabinet_id='cab-a' AND id=1")

    result_a = verify_audit_chain(conn, "cab-a")
    result_b = verify_audit_chain(conn, "cab-b")
    assert result_a.is_valid is False
    assert result_b.is_valid is True  # Pas affecté par la corruption de A


# --- Query API ---------------------------------------------------------------


def test_get_events_for_entity(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    log_audit_event(
        conn, cabinet_id="cab-a", entity_type="accounting_entry",
        entity_id=42, action="proposed",
    )
    log_audit_event(
        conn, cabinet_id="cab-a", entity_type="accounting_entry",
        entity_id=42, action="validated",
    )
    log_audit_event(
        conn, cabinet_id="cab-a", entity_type="email_message",
        entity_id=99, action="ingested",
    )

    events = get_events_for_entity(conn, "cab-a", "accounting_entry", 42)
    assert len(events) == 2
    assert events[0].action == "proposed"
    assert events[1].action == "validated"
    assert all(isinstance(e, AuditEvent) for e in events)


def test_list_events_filters(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    log_audit_event(conn, cabinet_id="cab-a", entity_type="t1",
                    entity_id=1, action="x",
                    timestamp="2026-04-01T10:00:00Z")
    log_audit_event(conn, cabinet_id="cab-a", entity_type="t2",
                    entity_id=2, action="y",
                    timestamp="2026-04-05T10:00:00Z")
    log_audit_event(conn, cabinet_id="cab-a", entity_type="t1",
                    entity_id=3, action="x",
                    timestamp="2026-04-10T10:00:00Z")

    # Filter par entity_type
    out = list_events(conn, "cab-a", entity_type="t1")
    assert len(out) == 2

    # Filter par dates
    out = list_events(conn, "cab-a", since="2026-04-03", until="2026-04-08")
    assert len(out) == 1
    assert out[0].entity_type == "t2"

    # Filter par action
    out = list_events(conn, "cab-a", action="y")
    assert len(out) == 1


# --- Hooks intégrés ----------------------------------------------------------


def test_hook_workflow_states_validated(tmp_path: Path) -> None:
    """Transition vers VALIDATED doit créer un event audit."""
    conn = _setup_db(tmp_path)
    entry_id = _insert_entry(conn, client_id="cab-a")

    ws.transition(conn, entry_id, ws.ENTRY_STATE_VALIDATED,
                  user_id="tanguy", reason="ok")

    events = get_events_for_entity(conn, "cab-a", "accounting_entry", entry_id)
    assert len(events) == 1
    assert events[0].action == ACTION_VALIDATED
    assert events[0].user_id == "tanguy"


def test_hook_entry_proposer_logs_proposed(tmp_path: Path) -> None:
    """entry_proposer.propose_entry → audit_log événement 'proposed'."""
    sys.path.insert(0, str(REPO_ROOT / "worker" / "scripts"))
    from seed_multi_mandant_test import seed_all  # noqa: E402
    from fiduciaire_worker.entry_proposer import propose_entry  # noqa: E402

    seeded = seed_all(conn := _setup_db(tmp_path))
    cabinet = "pilote-jura-01"
    doc_id = seeded[cabinet][0]

    def _llm_panic(p):
        raise AssertionError("LLM ne doit pas être appelé (vendor hist)")

    entry = propose_entry(
        conn, cabinet, doc_id, llm_caller=_llm_panic,
        vat_yaml_path=REPO_ROOT / "config" / "vat_codes_ch.yaml",
        plan_fallback_path=REPO_ROOT / "config" / "plan_comptable_pme_ch.yaml",
    )

    events = get_events_for_entity(
        conn, cabinet, "accounting_entry", entry.db_id,
    )
    assert len(events) == 1
    assert events[0].action == ACTION_PROPOSED
    assert events[0].after_json is not None


def test_hook_bexio_push_logs_pushed(tmp_path: Path) -> None:
    from fiduciaire_worker.bexio_push import push_validated_entries  # noqa: E402

    conn = _setup_db(tmp_path)
    entry_id = _insert_entry(conn, client_id="cab-a", state="validated")

    def handler(req):
        return httpx.Response(201, json={"id": 9999})

    http = httpx.Client(
        base_url="https://api.bexio.com",
        transport=httpx.MockTransport(handler),
    )

    push_validated_entries(
        cabinet_id="cab-a", pat="FAKE", conn=conn,
        http_client=http, dry_run=False,
        account_no_to_bexio_id={"6510": 1, "2000": 2},
        tax_code_to_bexio_id={"TN_NORM": 10},
    )

    events = get_events_for_entity(conn, "cab-a", "accounting_entry", entry_id)
    assert any(e.action == ACTION_PUSHED for e in events)
    pushed = [e for e in events if e.action == ACTION_PUSHED][0]
    assert pushed.after_json is not None
    assert "9999" in pushed.after_json


# --- Export ------------------------------------------------------------------


def test_export_audit_text_creates_file(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    for i in range(3):
        log_audit_event(
            conn, cabinet_id="cab-a", entity_type="accounting_entry",
            entity_id=i, action="proposed",
        )
    out = tmp_path / "audit.txt"
    result = export_audit_text(conn, "cab-a", out_path=out)
    assert result == out
    content = out.read_text()
    assert "AUDIT TRAIL — cab-a" in content
    assert "Total events : 3" in content
    assert "VALID" in content


def test_export_audit_text_marks_broken_chain(tmp_path: Path) -> None:
    conn = _setup_db(tmp_path)
    log_audit_event(conn, cabinet_id="cab-a", entity_type="x",
                    entity_id=1, action="a")
    log_audit_event(conn, cabinet_id="cab-a", entity_type="x",
                    entity_id=2, action="b")
    conn.execute("UPDATE audit_log SET action='hacked' WHERE id=1")

    out = tmp_path / "audit.txt"
    export_audit_text(conn, "cab-a", out_path=out)
    content = out.read_text()
    assert "BROKEN" in content


# --- Hash determinism --------------------------------------------------------


def test_same_inputs_produce_same_hash(tmp_path: Path) -> None:
    """Determinisme du hash : 2 events avec mêmes inputs → mêmes current_hash."""
    conn1 = _setup_db(tmp_path / "a")
    conn2 = _setup_db(tmp_path / "b")

    log_audit_event(
        conn1, cabinet_id="c", entity_type="t", entity_id=1, action="a",
        timestamp="2026-04-01T00:00:00Z",
    )
    log_audit_event(
        conn2, cabinet_id="c", entity_type="t", entity_id=1, action="a",
        timestamp="2026-04-01T00:00:00Z",
    )

    h1 = conn1.execute(
        "SELECT current_hash FROM audit_log WHERE id=1"
    ).fetchone()["current_hash"]
    h2 = conn2.execute(
        "SELECT current_hash FROM audit_log WHERE id=1"
    ).fetchone()["current_hash"]
    assert h1 == h2
