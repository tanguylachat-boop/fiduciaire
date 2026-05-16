"""Tests `fiduciaire_worker.bexio_history_import` — Sprint 2 Session 12.

Import paginé idempotent des écritures Bexio (N mois), rate-limit conservateur,
cross-mandant strict, dry-run, PAT jamais loggé.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import (  # noqa: E402
    accounting_schema, audit_log, bexio_client, db,
)


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "history.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    audit_log.init_audit_schema(conn)
    return conn


def _mock_handler_factory(
    accounts: list[dict],
    contacts: list[dict],
    entries: list[dict],
):
    """Mock Bexio API : accounts, contacts, manual_entries paginés.

    Page size simulé = `limit` query param. Si offset/page absent ⇒ page 1.
    """
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "/accounts" in url:
            return httpx.Response(200, json=accounts)
        if "/contact" in url:
            return httpx.Response(200, json=contacts)
        if "/accounting/manual_entries" in url:
            # Pagination simple : offset query param
            params = dict(req.url.params)
            offset = int(params.get("offset", "0"))
            limit = int(params.get("limit", "100"))
            page = entries[offset:offset + limit]
            return httpx.Response(200, json=page)
        return httpx.Response(404)
    return handler


def _bexio_with_handler(handler, cabinet_id="cab-a"):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url=bexio_client.DEFAULT_BASE_URL,
        headers={
            "Authorization": "Bearer FAKE_PAT",
            "Accept": "application/json",
        },
        transport=transport,
    )
    return bexio_client.BexioReadOnlyClient(
        client_id=cabinet_id, pat="FAKE_PAT", http_client=http,
    )


# --- Fixtures ----------------------------------------------------------------


def _sample_accounts():
    return [
        {"id": 1, "account_no": "1020", "name": "Banque",
         "account_type": "actif"},
        {"id": 2, "account_no": "6510", "name": "Telecom",
         "account_type": "charge"},
    ]


def _sample_contacts():
    return [
        {"id": 10, "name_1": "Swisscom (Suisse) SA",
         "contact_type": "company"},
    ]


def _sample_entries(n: int):
    """Génère n écritures avec contact_id alterné."""
    return [
        {
            "id": 1000 + i,
            "date": f"2026-{(i % 12) + 1:02d}-15",
            "description": "Swisscom abo internet" if i % 2 == 0
                           else "Romande Energie",
            "reference_nr": f"BX-{1000 + i}",
            "contact_id": "10" if i % 2 == 0 else "11",
            "entries": [
                {
                    "debit_account_id": "6510" if i % 2 == 0 else "6400",
                    "credit_account_id": "2000",
                    "amount": 100.0 + i,
                    "tax_id": "TN_NORM",
                }
            ],
        }
        for i in range(n)
    ]


# --- Tests -------------------------------------------------------------------


def test_history_import_paginates_and_persists(tmp_path: Path) -> None:
    """Pull 250 entries paginé en 3 pages, persisté dans bexio_sync."""
    from fiduciaire_worker.bexio_history_import import import_bexio_history

    conn = _setup_db(tmp_path)
    handler = _mock_handler_factory(
        _sample_accounts(), _sample_contacts(), _sample_entries(250),
    )
    cli = _bexio_with_handler(handler)

    summary = import_bexio_history(
        client=cli, conn=conn,
        cabinet_id="cab-a", mandant_id="cab-a",
        months=12, page_size=100, sleep_between_pages_s=0.0,
    )
    assert summary.entries_imported == 250
    assert summary.accounts_synced == 2
    assert summary.contacts_synced == 1

    rows = conn.execute(
        "SELECT COUNT(*) FROM bexio_sync "
        "WHERE client_id=? AND entity_type='manual_entry'",
        ("cab-a",),
    ).fetchone()[0]
    assert rows == 250


def test_history_import_idempotent_re_run_no_dupes(tmp_path: Path) -> None:
    from fiduciaire_worker.bexio_history_import import import_bexio_history

    conn = _setup_db(tmp_path)
    handler = _mock_handler_factory(
        _sample_accounts(), _sample_contacts(), _sample_entries(50),
    )
    cli = _bexio_with_handler(handler)

    import_bexio_history(
        client=cli, conn=conn,
        cabinet_id="cab-a", mandant_id="cab-a",
        months=12, page_size=100, sleep_between_pages_s=0.0,
    )
    s2 = import_bexio_history(
        client=cli, conn=conn,
        cabinet_id="cab-a", mandant_id="cab-a",
        months=12, page_size=100, sleep_between_pages_s=0.0,
    )
    # entries_imported = ce que la page a renvoyé. La dédup est via PK
    # bexio_sync donc le COUNT ne bouge pas.
    rows = conn.execute(
        "SELECT COUNT(*) FROM bexio_sync "
        "WHERE client_id=? AND entity_type='manual_entry'",
        ("cab-a",),
    ).fetchone()[0]
    assert rows == 50


def test_history_import_cross_mandant_isolation(tmp_path: Path) -> None:
    """Deux pull séparés cab-a / cab-b ⇒ pas de leak."""
    from fiduciaire_worker.bexio_history_import import import_bexio_history

    conn = _setup_db(tmp_path)
    handler = _mock_handler_factory(
        _sample_accounts(), _sample_contacts(), _sample_entries(30),
    )
    cli_a = _bexio_with_handler(handler, cabinet_id="cab-a")
    cli_b = _bexio_with_handler(handler, cabinet_id="cab-b")

    import_bexio_history(
        client=cli_a, conn=conn,
        cabinet_id="cab-a", mandant_id="cab-a",
        months=12, page_size=100, sleep_between_pages_s=0.0,
    )
    import_bexio_history(
        client=cli_b, conn=conn,
        cabinet_id="cab-b", mandant_id="cab-b",
        months=12, page_size=100, sleep_between_pages_s=0.0,
    )
    rows_a = conn.execute(
        "SELECT COUNT(*) FROM bexio_sync "
        "WHERE client_id='cab-a' AND entity_type='manual_entry'"
    ).fetchone()[0]
    rows_b = conn.execute(
        "SELECT COUNT(*) FROM bexio_sync "
        "WHERE client_id='cab-b' AND entity_type='manual_entry'"
    ).fetchone()[0]
    assert rows_a == 30
    assert rows_b == 30
    # Aucun row "orphelin"
    leak = conn.execute(
        "SELECT COUNT(*) FROM bexio_sync "
        "WHERE client_id NOT IN ('cab-a','cab-b') "
        "AND entity_type='manual_entry'"
    ).fetchone()[0]
    assert leak == 0


def test_history_import_dry_run_no_write_no_audit(tmp_path: Path) -> None:
    from fiduciaire_worker.bexio_history_import import import_bexio_history

    conn = _setup_db(tmp_path)
    handler = _mock_handler_factory(
        _sample_accounts(), _sample_contacts(), _sample_entries(20),
    )
    cli = _bexio_with_handler(handler)

    summary = import_bexio_history(
        client=cli, conn=conn,
        cabinet_id="cab-a", mandant_id="cab-a",
        months=12, page_size=100, sleep_between_pages_s=0.0,
        dry_run=True,
    )
    assert summary.entries_imported == 20  # count des pages parcourues
    assert summary.dry_run is True

    rows = conn.execute(
        "SELECT COUNT(*) FROM bexio_sync WHERE client_id='cab-a'"
    ).fetchone()[0]
    assert rows == 0
    events = audit_log.list_events(conn, "cab-a")
    assert [e for e in events if e.action == "bexio_history_imported"] == []


def test_history_import_emits_audit_event(tmp_path: Path) -> None:
    from fiduciaire_worker.bexio_history_import import import_bexio_history

    conn = _setup_db(tmp_path)
    handler = _mock_handler_factory(
        _sample_accounts(), _sample_contacts(), _sample_entries(15),
    )
    cli = _bexio_with_handler(handler)

    import_bexio_history(
        client=cli, conn=conn,
        cabinet_id="cab-a", mandant_id="cab-a",
        months=12, page_size=100, sleep_between_pages_s=0.0,
    )
    events = audit_log.list_events(conn, "cab-a")
    imports = [e for e in events if e.action == "bexio_history_imported"]
    assert len(imports) == 1
    ev = imports[0]
    assert ev.entity_type == "bexio_sync"
    assert ev.entity_id == "cab-a:cab-a"
    payload = json.loads(ev.after_json)
    assert payload["entries_count"] == 15
    assert payload["accounts_count"] == 2
    assert payload["contacts_count"] == 1
    assert payload["months"] == 12
    # PAT jamais dans le payload
    assert "pat" not in (ev.after_json or "").lower()
    assert "FAKE_PAT" not in (ev.after_json or "")


def test_history_import_builds_vendor_history(tmp_path: Path) -> None:
    """Après import, vendor_account_history doit contenir des recos."""
    from fiduciaire_worker.bexio_history_import import import_bexio_history

    conn = _setup_db(tmp_path)
    handler = _mock_handler_factory(
        _sample_accounts(), _sample_contacts(), _sample_entries(20),
    )
    cli = _bexio_with_handler(handler)

    summary = import_bexio_history(
        client=cli, conn=conn,
        cabinet_id="cab-a", mandant_id="cab-a",
        months=12, page_size=100, sleep_between_pages_s=0.0,
    )
    assert summary.vendor_recs_built >= 1

    rows = conn.execute(
        "SELECT COUNT(*) FROM vendor_account_history WHERE client_id='cab-a'"
    ).fetchone()[0]
    assert rows >= 1


def test_history_import_pat_not_logged(
    tmp_path: Path, caplog,
) -> None:
    """Aucun log ne doit contenir FAKE_PAT après import."""
    from fiduciaire_worker.bexio_history_import import import_bexio_history

    conn = _setup_db(tmp_path)
    handler = _mock_handler_factory(
        _sample_accounts(), _sample_contacts(), _sample_entries(5),
    )
    cli = _bexio_with_handler(handler)

    with caplog.at_level("DEBUG", logger="fiduciaire"):
        import_bexio_history(
            client=cli, conn=conn,
            cabinet_id="cab-a", mandant_id="cab-a",
            months=12, page_size=100, sleep_between_pages_s=0.0,
        )
    full_text = "\n".join(r.message for r in caplog.records)
    assert "FAKE_PAT" not in full_text
    assert "bearer" not in full_text.lower()
