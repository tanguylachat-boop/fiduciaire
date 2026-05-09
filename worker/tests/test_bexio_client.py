"""Tests BexioReadOnlyClient — pas d'appel réseau réel, MockTransport."""

from __future__ import annotations

import logging

import httpx
import pytest

from fiduciaire_worker import accounting_schema, bexio_client, db


def _client_with_handler(handler) -> bexio_client.BexioReadOnlyClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url=bexio_client.DEFAULT_BASE_URL,
        headers={"Authorization": "Bearer FAKE_PAT", "Accept": "application/json"},
        transport=transport,
    )
    return bexio_client.BexioReadOnlyClient(
        client_id="pilote-jura-01", pat="FAKE_PAT", http_client=http
    )


def test_pat_required():
    with pytest.raises(ValueError):
        bexio_client.BexioReadOnlyClient(client_id="x", pat="")


def test_auth_header_set_on_real_init():
    """Un client init normal (sans http_client mock) configure bien le bearer."""
    cli = bexio_client.BexioReadOnlyClient(client_id="x", pat="SECRET")
    assert cli._http.headers.get("authorization") == "Bearer SECRET"


def test_fetch_account_plan_parses():
    def handler(req: httpx.Request) -> httpx.Response:
        if "/accounts" in str(req.url):
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "account_no": "1020", "name": "Banque", "account_type": "actif"},
                    {"id": 2, "account_no": "6510", "name": "Telecom", "account_type": "charge"},
                ],
            )
        return httpx.Response(404)

    cli = _client_with_handler(handler)
    accounts = cli.fetch_account_plan()
    assert len(accounts) == 2
    assert accounts[0].account_no == "1020"
    assert accounts[1].name == "Telecom"


def test_fetch_contacts_parses():
    def handler(req):
        return httpx.Response(
            200,
            json=[{"id": 10, "name_1": "Swisscom (Suisse) SA", "contact_type": "company"}],
        )

    cli = _client_with_handler(handler)
    contacts = cli.fetch_contacts()
    assert len(contacts) == 1
    assert contacts[0].name == "Swisscom (Suisse) SA"
    assert contacts[0].contact_type == "company"


def test_sync_to_local_cache_idempotent(tmp_path):
    def handler(req):
        url = str(req.url)
        if "/accounts" in url:
            return httpx.Response(
                200,
                json=[{"id": 1, "account_no": "1020", "name": "Banque", "account_type": "actif"}],
            )
        if "/contact" in url:
            return httpx.Response(
                200, json=[{"id": 10, "name_1": "Swisscom", "contact_type": "company"}]
            )
        if "/manual_entries" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 100,
                        "date": "2026-04-01",
                        "description": "Swisscom abo",
                        "entries": [
                            {"debit_account_id": "6510", "credit_account_id": "2000", "amount": 50.0}
                        ],
                    }
                ],
            )
        return httpx.Response(404)

    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    cli = _client_with_handler(handler)
    cli.sync_to_local_cache(conn)
    cli.sync_to_local_cache(conn)  # 2e sync : upsert, pas duplication

    rows = conn.execute("SELECT COUNT(*) AS n FROM bexio_sync").fetchone()
    assert rows["n"] == 3  # 1 account + 1 contact + 1 entry

    runs = conn.execute("SELECT COUNT(*) AS n FROM bexio_sync_runs").fetchone()
    assert runs["n"] == 2  # 2 runs distincts dans le journal


def test_write_methods_blocked():
    cli = bexio_client.BexioReadOnlyClient(client_id="x", pat="FAKE")
    for forbidden in ("create_invoice", "update_account", "delete_contact",
                      "post_anything", "put_x", "patch_y"):
        with pytest.raises(AttributeError, match="interdite"):
            getattr(cli, forbidden)


def test_pat_never_logged_on_error(caplog, tmp_path):
    """Le PAT en clair ne doit JAMAIS apparaître dans les logs, même en cas d'erreur."""
    caplog.set_level(logging.DEBUG)

    def handler(req):
        return httpx.Response(500, text="boom")

    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url=bexio_client.DEFAULT_BASE_URL,
        headers={"Authorization": "Bearer VERYSECRETPAT", "Accept": "application/json"},
        transport=transport,
    )
    cli = bexio_client.BexioReadOnlyClient(
        client_id="x", pat="VERYSECRETPAT", http_client=http
    )
    with pytest.raises(httpx.HTTPStatusError):
        cli.sync_to_local_cache(conn)
    full_log = "\n".join(record.getMessage() for record in caplog.records)
    assert "VERYSECRETPAT" not in full_log


def test_multi_mandant_isolation(tmp_path):
    """Sync client-a puis client-b : zéro fuite cross-mandant."""
    def handler(req):
        url = str(req.url)
        if "/accounts" in url:
            return httpx.Response(
                200, json=[{"id": 1, "account_no": "1020", "name": "Banque", "account_type": "actif"}]
            )
        if "/contact" in url:
            return httpx.Response(200, json=[])
        if "/manual_entries" in url:
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    transport = httpx.MockTransport(handler)
    for client_id in ("client-a", "client-b"):
        http = httpx.Client(
            base_url=bexio_client.DEFAULT_BASE_URL,
            headers={"Authorization": "Bearer FAKE", "Accept": "application/json"},
            transport=transport,
        )
        cli = bexio_client.BexioReadOnlyClient(
            client_id=client_id, pat="FAKE", http_client=http
        )
        cli.sync_to_local_cache(conn)

    rows_a = conn.execute(
        "SELECT COUNT(*) AS n FROM bexio_sync WHERE client_id = 'client-a'"
    ).fetchone()
    rows_b = conn.execute(
        "SELECT COUNT(*) AS n FROM bexio_sync WHERE client_id = 'client-b'"
    ).fetchone()
    assert rows_a["n"] == 1
    assert rows_b["n"] == 1
