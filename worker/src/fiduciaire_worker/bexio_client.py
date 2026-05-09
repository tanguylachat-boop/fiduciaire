"""Client Bexio strictement read-only (PAT auth).

Décision architecturale (cf docs/decisions/2026-05-08-bexio-auth-pat-vs-oauth2.md) :
- Sprint 0a/1 : Personal Access Token chargé depuis Keychain macOS
- Sprint 2+ multi-cabinet : OAuth2 avec callback hébergé

CONTRAINTE DESIGN : aucune méthode d'écriture exposée. Le `__getattr__` sentinel
bloque toute tentative d'appel `create_*`, `update_*`, `delete_*`, `post_*`,
`put_*`, `patch_*` avec une AttributeError explicite.

Tests : worker/tests/test_bexio_client.py — utilise httpx MockTransport,
zéro appel réseau réel.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.bexio.com/2.0"

_log = logging.getLogger("fiduciaire.bexio")


@dataclass
class BexioAccount:
    id: str
    account_no: str
    name: str
    type: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BexioContact:
    id: str
    name: str
    contact_type: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BexioEntry:
    id: str
    date: str
    debit_account: str | None
    credit_account: str | None
    amount: float
    description: str
    reference_id: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncReport:
    accounts_count: int
    contacts_count: int
    entries_count: int
    ok: bool
    error: str | None = None


class BexioReadOnlyClient:
    """Client Bexio lecture seule. Initialisation explicite (pas d'env var fallback)."""

    def __init__(
        self,
        client_id: str,
        pat: str,
        base_url: str = DEFAULT_BASE_URL,
        http_client: httpx.Client | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        if not pat:
            raise ValueError("PAT Bexio requis (vide non accepté)")
        self.client_id = client_id
        self._pat = pat
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {pat}", "Accept": "application/json"},
            timeout=timeout_s,
        )

    def __enter__(self) -> "BexioReadOnlyClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # --- Fetchers (read-only) -------------------------------------------------

    def fetch_account_plan(self) -> list[BexioAccount]:
        r = self._http.get("/accounts", params={"limit": 2000})
        r.raise_for_status()
        return [
            BexioAccount(
                id=str(a.get("id")),
                account_no=str(a.get("account_no", "")),
                name=str(a.get("name", "")),
                type=str(a.get("account_type", "")),
                raw=a,
            )
            for a in r.json()
        ]

    def fetch_contacts(self, limit: int = 1000) -> list[BexioContact]:
        r = self._http.get("/contact", params={"limit": limit})
        r.raise_for_status()
        return [
            BexioContact(
                id=str(c.get("id")),
                name=str(c.get("name_1") or c.get("name", "")),
                contact_type=str(c.get("contact_type") or "unknown"),
                raw=c,
            )
            for c in r.json()
        ]

    def fetch_recent_manual_entries(self, limit: int = 100) -> list[BexioEntry]:
        r = self._http.get(
            "/accounting/manual_entries",
            params={"limit": limit, "order_by": "date_desc"},
        )
        r.raise_for_status()
        return [self._parse_entry(e) for e in r.json()]

    @staticmethod
    def _parse_entry(payload: dict[str, Any]) -> BexioEntry:
        first_line = (payload.get("entries") or [{}])[0] if payload.get("entries") else {}
        return BexioEntry(
            id=str(payload.get("id")),
            date=str(payload.get("date", "")),
            debit_account=str(first_line.get("debit_account_id") or "") or None,
            credit_account=str(first_line.get("credit_account_id") or "") or None,
            amount=float(first_line.get("amount", 0) or 0),
            description=str(payload.get("description", "")),
            reference_id=str(payload.get("reference_nr") or "") or None,
            raw=payload,
        )

    # --- Sync to local cache --------------------------------------------------

    def sync_to_local_cache(self, conn: sqlite3.Connection) -> SyncReport:
        run_id = self._start_run(conn)
        try:
            accounts = self.fetch_account_plan()
            contacts = self.fetch_contacts()
            entries = self.fetch_recent_manual_entries()

            self._upsert_many(
                conn, "account", accounts,
                key=lambda a: a.account_no or a.id, raw=lambda a: a.raw,
            )
            self._upsert_many(
                conn, "contact", contacts, key=lambda c: c.id, raw=lambda c: c.raw
            )
            self._upsert_many(
                conn, "manual_entry", entries, key=lambda e: e.id, raw=lambda e: e.raw
            )

            report = SyncReport(len(accounts), len(contacts), len(entries), ok=True)
            self._finish_run(conn, run_id, report)
            return report
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            # PAT jamais loggé : on n'inclut que le type d'erreur, pas les headers ni la query.
            _log.error("Bexio sync failed for client %s: %s", self.client_id, err)
            report = SyncReport(0, 0, 0, ok=False, error=err)
            self._finish_run(conn, run_id, report)
            raise

    def _upsert_many(self, conn, entity_type, items, key, raw) -> None:
        for item in items:
            conn.execute(
                "INSERT OR REPLACE INTO bexio_sync "
                "(client_id, entity_type, entity_id, payload_json, synced_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (
                    self.client_id,
                    entity_type,
                    str(key(item)),
                    json.dumps(raw(item), ensure_ascii=False),
                ),
            )

    def _start_run(self, conn) -> int:
        cur = conn.execute(
            "INSERT INTO bexio_sync_runs (client_id, started_at) "
            "VALUES (?, datetime('now'))",
            (self.client_id,),
        )
        return int(cur.lastrowid)

    def _finish_run(self, conn, run_id: int, report: SyncReport) -> None:
        conn.execute(
            "UPDATE bexio_sync_runs "
            "SET finished_at=datetime('now'), accounts_count=?, contacts_count=?, "
            "    entries_count=?, ok=?, error=? WHERE id=?",
            (
                report.accounts_count,
                report.contacts_count,
                report.entries_count,
                1 if report.ok else 0,
                report.error,
                run_id,
            ),
        )

    # --- Sentinel anti-écriture ----------------------------------------------

    _FORBIDDEN_PREFIXES = ("create_", "update_", "delete_", "post_", "put_", "patch_")

    def __getattr__(self, name: str):
        # Ne se déclenche QUE pour les attributs absents (Python __getattr__ vs __getattribute__).
        if name.startswith(self._FORBIDDEN_PREFIXES):
            raise AttributeError(
                f"BexioReadOnlyClient: méthode '{name}' interdite par design. "
                "La classe est strictement read-only (cf decisions/2026-05-08-bexio-auth-pat-vs-oauth2.md)."
            )
        raise AttributeError(name)
