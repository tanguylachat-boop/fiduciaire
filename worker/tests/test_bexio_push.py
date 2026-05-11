"""Tests `fiduciaire_worker.bexio_push` — push écritures validées vers Bexio v3.

Pattern : httpx.MockTransport (zéro appel réseau), table accounting_entries
peuplée manuellement, vérifie bexio_id/bexio_pushed_at + bexio_push_log.

Mode dry-run par défaut **non-négociable** — toute écriture en prod doit
passer un flag explicite (`dry_run=False`).

Cf docs/specs/bexio-push.md (créé en parallèle).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.bexio_push import (  # noqa: E402
    BexioPushResult,
    BexioPushSummary,
    PUSH_STATUS_ACCOUNT_NOT_MAPPED,
    PUSH_STATUS_ALREADY_PUSHED,
    PUSH_STATUS_DRY_RUN,
    PUSH_STATUS_FAILED,
    PUSH_STATUS_PUSHED,
    push_validated_entries,
)


# --- DB fixtures --------------------------------------------------------------


def _seed_db(tmp_path: Path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    # 1 document factice
    conn.execute(
        "INSERT INTO documents (sha256, original_filename, archive_path, status) "
        "VALUES ('sha-1', 'f.pdf', 'archive/f.pdf', 'routed')"
    )
    doc_row = conn.execute("SELECT id FROM documents").fetchone()
    return conn, doc_row["id"]


def _insert_entry(
    conn,
    client_id: str = "pilote-jura-01",
    doc_id: int = 1,
    debit: str = "6510",
    credit: str = "2000",
    amount: float = 100.0,
    vat_code: str = "TN_NORM",
    description: str = "Test entry",
    state: str = "validated",
    date: str = "2026-04-15",
) -> int:
    cur = conn.execute(
        """INSERT INTO accounting_entries
        (client_id, source_document_id, date, debit_account, credit_account,
         amount_chf, vat_code, vat_amount, description,
         confidence_account, confidence_vat, reasoning, state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, doc_id, date, debit, credit, amount, vat_code,
         amount * 0.081, description, 0.95, 0.9, "test", state),
    )
    return int(cur.lastrowid)


# --- HTTP helpers -------------------------------------------------------------


def _http_with_handler(handler, base_url: str = "https://api.bexio.com"):
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": "Bearer FAKE_PAT", "Accept": "application/json"},
        transport=transport,
    )


_ACCOUNT_MAP_DEFAULT = {"6510": 9510, "2000": 9200}
_TAX_MAP_DEFAULT = {"TN_NORM": 12, "TN_RED": 13, "EXO": 30}


# --- Tests --------------------------------------------------------------------


def test_dry_run_default_no_http_call(tmp_path: Path) -> None:
    """Par défaut dry_run=True → aucun appel HTTP émis."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id)

    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(500)

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01",
        pat="FAKE_PAT",
        conn=conn,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    assert calls == []
    assert summary.dry_run is True
    assert summary.skipped_dry_run == 1
    assert summary.pushed == 0


def test_live_push_marks_bexio_id_and_timestamp(tmp_path: Path) -> None:
    """dry_run=False : POST envoyé, bexio_id + bexio_pushed_at persisted."""
    conn, doc_id = _seed_db(tmp_path)
    entry_id = _insert_entry(conn, doc_id=doc_id, description="Facture Swisscom")

    received_payloads: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        received_payloads.append(json.loads(req.content.decode()))
        return httpx.Response(201, json={"id": 42, "date": "2026-04-15"})

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01",
        pat="FAKE_PAT",
        conn=conn,
        dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    assert len(received_payloads) == 1
    assert summary.pushed == 1
    row = conn.execute(
        "SELECT bexio_id, bexio_pushed_at, state FROM accounting_entries WHERE id=?",
        (entry_id,),
    ).fetchone()
    assert row["bexio_id"] == "42"
    assert row["bexio_pushed_at"] is not None
    # State reste validated, pas de transition automatique (humain valide aussi le push)
    assert row["state"] == "validated"


def test_payload_format_v3_manual_entries(tmp_path: Path) -> None:
    """Le body POST doit suivre le format v3 manual_entries."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id, debit="6510", credit="2000",
                  amount=120.50, vat_code="TN_NORM",
                  description="Achat materiel", date="2026-04-15")

    received: list[Any] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        received.append((str(req.url), req.method, json.loads(req.content.decode())))
        return httpx.Response(201, json={"id": 100})

    push_validated_entries(
        cabinet_id="pilote-jura-01",
        pat="FAKE",
        conn=conn,
        dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id={"6510": 9510, "2000": 9200},
        tax_code_to_bexio_id={"TN_NORM": 12},
    )

    url, method, body = received[0]
    assert method == "POST"
    assert "manual_entries" in url
    assert body["date"] == "2026-04-15"
    assert len(body["entries"]) == 1
    entry_line = body["entries"][0]
    assert entry_line["debit_account_id"] == 9510
    assert entry_line["credit_account_id"] == 9200
    assert entry_line["amount"] == 120.50
    assert entry_line["tax_id"] == 12


def test_already_pushed_skipped(tmp_path: Path) -> None:
    """Entry avec bexio_id non null → skip (idempotence)."""
    conn, doc_id = _seed_db(tmp_path)
    entry_id = _insert_entry(conn, doc_id=doc_id)
    conn.execute(
        "UPDATE accounting_entries SET bexio_id='99', "
        "bexio_pushed_at=datetime('now') WHERE id=?",
        (entry_id,),
    )

    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(500)

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01",
        pat="FAKE_PAT",
        conn=conn,
        dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    assert calls == []
    assert summary.already_pushed == 1
    assert summary.pushed == 0


def test_retry_on_5xx_then_succeeds(tmp_path: Path) -> None:
    """503 puis 201 → succès au 2e essai, 1 entry pushed."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id)

    attempts = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503, text="service unavailable")
        return httpx.Response(201, json={"id": 7})

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01",
        pat="FAKE",
        conn=conn,
        dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
        retry_initial_backoff_s=0.001,
    )

    assert attempts["n"] == 2
    assert summary.pushed == 1
    assert summary.failed == 0


def test_retry_exhausted_after_max_retries(tmp_path: Path) -> None:
    """3 retries → 3 fails → entry reste state='validated', bexio_id null."""
    conn, doc_id = _seed_db(tmp_path)
    entry_id = _insert_entry(conn, doc_id=doc_id)

    attempts = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(502, text="bad gateway")

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01",
        pat="FAKE",
        conn=conn,
        dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
        max_retries=3,
        retry_initial_backoff_s=0.001,
    )

    assert attempts["n"] == 3
    assert summary.failed == 1
    assert summary.pushed == 0
    row = conn.execute(
        "SELECT bexio_id, state FROM accounting_entries WHERE id=?", (entry_id,),
    ).fetchone()
    assert row["bexio_id"] is None
    assert row["state"] == "validated"


def test_4xx_no_retry(tmp_path: Path) -> None:
    """4xx (ex. validation Bexio refuse) → pas de retry, fail immédiat."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id)

    attempts = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(400, json={"error": "invalid date"})

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01",
        pat="FAKE",
        conn=conn,
        dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
        max_retries=3,
        retry_initial_backoff_s=0.001,
    )

    assert attempts["n"] == 1  # pas de retry sur 4xx
    assert summary.failed == 1


def test_idempotence_second_run_no_duplicates(tmp_path: Path) -> None:
    """Push 1 entry, re-run → la 2e fois on skip (already_pushed)."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id)

    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(201, json={"id": calls["n"]})

    s1 = push_validated_entries(
        cabinet_id="pilote-jura-01", pat="FAKE", conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )
    s2 = push_validated_entries(
        cabinet_id="pilote-jura-01", pat="FAKE", conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    assert calls["n"] == 1
    assert s1.pushed == 1
    assert s2.already_pushed == 1
    assert s2.pushed == 0


def test_multi_mandant_isolation(tmp_path: Path) -> None:
    """Push pour cabinet-a ne pousse pas les entries de cabinet-b."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id, client_id="cabinet-a",
                  description="A only")
    _insert_entry(conn, doc_id=doc_id, client_id="cabinet-b",
                  description="B only")

    received: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        received.append(json.loads(req.content.decode()))
        return httpx.Response(201, json={"id": len(received) + 1000})

    summary = push_validated_entries(
        cabinet_id="cabinet-a", pat="FAKE", conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    assert len(received) == 1
    assert "A only" in received[0]["entries"][0]["description"]
    assert summary.pushed == 1

    # Vérifier que cabinet-b n'a pas été touché
    row_b = conn.execute(
        "SELECT bexio_id FROM accounting_entries WHERE client_id='cabinet-b'"
    ).fetchone()
    assert row_b["bexio_id"] is None


def test_only_validated_state_pushed(tmp_path: Path) -> None:
    """state='proposed' ou 'rejected' → ignorés. Seul 'validated' poussé."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id, state="proposed", description="prop")
    _insert_entry(conn, doc_id=doc_id, state="validated", description="val")
    _insert_entry(conn, doc_id=doc_id, state="rejected", description="rej")

    received: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        received.append(json.loads(req.content.decode()))
        return httpx.Response(201, json={"id": 1})

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01", pat="FAKE", conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    assert len(received) == 1
    assert received[0]["entries"][0]["description"] == "val"
    assert summary.pushed == 1


def test_account_no_not_mapped_skipped(tmp_path: Path) -> None:
    """Si account_no n'est pas dans la map → skip avec status spécifique."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id, debit="9999", credit="2000")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": 1})

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01", pat="FAKE", conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id={"6510": 9510, "2000": 9200},  # 9999 absent
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    assert summary.account_not_mapped == 1
    assert summary.pushed == 0


def test_pat_never_logged(tmp_path: Path, caplog) -> None:
    """Erreur 5xx → PAT n'apparaît jamais en logs."""
    caplog.set_level(logging.DEBUG)
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    push_validated_entries(
        cabinet_id="pilote-jura-01",
        pat="VERYSECRETPAT_NEVERLOG",
        conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
        max_retries=2, retry_initial_backoff_s=0.001,
    )

    log_text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "VERYSECRETPAT_NEVERLOG" not in log_text


def test_audit_log_records_all_attempts(tmp_path: Path) -> None:
    """1 push avec 2 attempts (retry) → 2 lignes dans bexio_push_log."""
    conn, doc_id = _seed_db(tmp_path)
    entry_id = _insert_entry(conn, doc_id=doc_id)

    n = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        n["n"] += 1
        if n["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(201, json={"id": 555})

    push_validated_entries(
        cabinet_id="pilote-jura-01", pat="FAKE", conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
        retry_initial_backoff_s=0.001,
    )

    rows = conn.execute(
        "SELECT attempt, http_status, ok, bexio_id FROM bexio_push_log "
        "WHERE entry_id=? ORDER BY attempt", (entry_id,),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["attempt"] == 1
    assert rows[0]["http_status"] == 503
    assert rows[0]["ok"] == 0
    assert rows[1]["attempt"] == 2
    assert rows[1]["http_status"] == 201
    assert rows[1]["ok"] == 1
    assert rows[1]["bexio_id"] == "555"


def test_dry_run_logs_to_audit_with_dry_run_flag(tmp_path: Path) -> None:
    """dry_run=True : pas d'HTTP, mais audit log marque dry_run=1."""
    conn, doc_id = _seed_db(tmp_path)
    entry_id = _insert_entry(conn, doc_id=doc_id)

    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("ne doit pas être appelé en dry-run")

    push_validated_entries(
        cabinet_id="pilote-jura-01", pat="FAKE", conn=conn, dry_run=True,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    row = conn.execute(
        "SELECT dry_run, ok FROM bexio_push_log WHERE entry_id=?",
        (entry_id,),
    ).fetchone()
    assert row is not None
    assert row["dry_run"] == 1


def test_limit_caps_processing(tmp_path: Path) -> None:
    """limit=2 sur 5 entries → seulement 2 pushed."""
    conn, doc_id = _seed_db(tmp_path)
    for i in range(5):
        _insert_entry(conn, doc_id=doc_id, description=f"e{i}")

    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(201, json={"id": calls["n"]})

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01", pat="FAKE", conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
        limit=2,
    )

    assert calls["n"] == 2
    assert summary.pushed == 2


def test_summary_shape_and_results(tmp_path: Path) -> None:
    """Smoke : Summary contient les bons champs + results list."""
    conn, doc_id = _seed_db(tmp_path)
    _insert_entry(conn, doc_id=doc_id)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": 1})

    summary = push_validated_entries(
        cabinet_id="pilote-jura-01", pat="FAKE", conn=conn, dry_run=False,
        http_client=_http_with_handler(handler),
        account_no_to_bexio_id=_ACCOUNT_MAP_DEFAULT,
        tax_code_to_bexio_id=_TAX_MAP_DEFAULT,
    )

    assert isinstance(summary, BexioPushSummary)
    assert summary.cabinet_id == "pilote-jura-01"
    assert summary.total == 1
    assert summary.duration_s > 0
    assert len(summary.results) == 1
    assert isinstance(summary.results[0], BexioPushResult)
    assert summary.results[0].status == PUSH_STATUS_PUSHED


def test_dry_run_status_constants_exposed() -> None:
    """Constantes status accessibles depuis le module pour CLI / introspection."""
    assert PUSH_STATUS_DRY_RUN == "skipped_dry_run"
    assert PUSH_STATUS_PUSHED == "pushed"
    assert PUSH_STATUS_FAILED == "failed"
    assert PUSH_STATUS_ALREADY_PUSHED == "already_pushed"
    assert PUSH_STATUS_ACCOUNT_NOT_MAPPED == "account_not_mapped"
