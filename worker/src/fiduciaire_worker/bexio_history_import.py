"""Import historique Bexio : pull N mois d'écritures pour bootstrap
vendor_account_history — Sprint 2 Session 12.

`fetch_recent_manual_entries(limit=100)` ne suffit pas en prod (=
~2 semaines d'activité par mandant). Ce module pull N mois par mandant,
paginé, rate-limité, idempotent (via PK bexio_sync), puis rebuild
`vendor_account_history`.

Cf decision doc `docs/decisions/2026-05-16-bexio-history-import.md`.

Multi-mandant strict : un cabinet ne pull que ses propres mandants
(filtre `client_id`). Test cross-mandant explicite.

⚠️  PAT jamais loggé. Aucun secret dans l'audit payload.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from . import audit_log as _audit
from .bexio_client import BexioReadOnlyClient
from .vendor_account_history import build_history_from_bexio_cache

_log = logging.getLogger("fiduciaire.bexio_history_import")

DEFAULT_PAGE_SIZE = 100
DEFAULT_SLEEP_BETWEEN_PAGES_S = 1.2  # ~50 req/min < limite PAT standard 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_S = 2.0


@dataclass
class ImportSummary:
    cabinet_id: str
    mandant_id: str
    months: int
    accounts_synced: int = 0
    contacts_synced: int = 0
    entries_imported: int = 0
    vendor_recs_built: int = 0
    dry_run: bool = False
    duration_s: float = 0.0


# --- Helpers ---------------------------------------------------------------


def _month_range_iso(months: int) -> tuple[str, str]:
    """Retourne (date_from, date_to) ISO YYYY-MM-DD pour les N derniers mois."""
    now = datetime.now()
    date_to = now.strftime("%Y-%m-%d")
    # Approximation : N mois = N * 30.5 jours, suffisant pour la limite Bexio.
    date_from = (now - timedelta(days=int(months * 30.5))).strftime("%Y-%m-%d")
    return date_from, date_to


def _fetch_manual_entries_page(
    client: BexioReadOnlyClient,
    *,
    offset: int,
    page_size: int,
    date_from: str,
    date_to: str,
    max_retries: int,
    backoff_base: float,
) -> list[dict]:
    """Pull 1 page d'écritures avec backoff sur 429.

    Retourne la list JSON brute Bexio (pas converti BexioEntry).
    """
    attempt = 0
    while True:
        try:
            r = client._http.get(  # noqa: SLF001 — accès interne volontaire
                "/3.0/accounting/manual_entries",
                params={
                    "limit": page_size,
                    "offset": offset,
                    "order_by": "date_desc",
                    "date_from": date_from,
                    "date_to": date_to,
                },
            )
            if r.status_code == 429:
                raise httpx.HTTPStatusError(
                    "rate limited", request=r.request, response=r,
                )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                attempt += 1
                if attempt > max_retries:
                    _log.warning(
                        "Bexio rate limit, max retries atteint offset=%d",
                        offset,
                    )
                    raise
                wait = backoff_base ** attempt
                _log.warning(
                    "Bexio 429 rate limit, retry %d/%d après %.1fs",
                    attempt, max_retries, wait,
                )
                time.sleep(wait)
                continue
            raise


def _persist_entry(
    conn: sqlite3.Connection, cabinet_id: str, payload: dict,
) -> None:
    """Upsert 1 manual_entry en bexio_sync (idempotent via PK)."""
    entity_id = str(payload.get("id"))
    conn.execute(
        "INSERT OR REPLACE INTO bexio_sync "
        "(client_id, entity_type, entity_id, payload_json, synced_at) "
        "VALUES (?, 'manual_entry', ?, ?, datetime('now'))",
        (cabinet_id, entity_id, json.dumps(payload, ensure_ascii=False)),
    )


def _persist_accounts(
    conn: sqlite3.Connection,
    cabinet_id: str,
    accounts,
) -> int:
    for a in accounts:
        key = a.account_no or a.id
        conn.execute(
            "INSERT OR REPLACE INTO bexio_sync "
            "(client_id, entity_type, entity_id, payload_json, synced_at) "
            "VALUES (?, 'account', ?, ?, datetime('now'))",
            (cabinet_id, str(key),
             json.dumps(a.raw, ensure_ascii=False)),
        )
    return len(accounts)


def _persist_contacts(
    conn: sqlite3.Connection,
    cabinet_id: str,
    contacts,
) -> int:
    for c in contacts:
        conn.execute(
            "INSERT OR REPLACE INTO bexio_sync "
            "(client_id, entity_type, entity_id, payload_json, synced_at) "
            "VALUES (?, 'contact', ?, ?, datetime('now'))",
            (cabinet_id, str(c.id),
             json.dumps(c.raw, ensure_ascii=False)),
        )
    return len(contacts)


# --- Public API ------------------------------------------------------------


def import_bexio_history(
    *,
    client: BexioReadOnlyClient,
    conn: sqlite3.Connection,
    cabinet_id: str,
    mandant_id: str,
    months: int = 12,
    page_size: int = DEFAULT_PAGE_SIZE,
    sleep_between_pages_s: float = DEFAULT_SLEEP_BETWEEN_PAGES_S,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE_S,
    force_refresh: bool = False,
    dry_run: bool = False,
    user_id: str | None = None,
) -> ImportSummary:
    """Pull N mois d'écritures Bexio + reconstruit vendor_account_history.

    Multi-mandant : `cabinet_id` est le filtre owner ; `mandant_id` est
    propagé à l'audit event. Sprint 2 ils sont == ; Sprint 3 ils
    différeront quand la table mandants distinguera cabinet vs mandant.

    Args:
        client: BexioReadOnlyClient configuré (PAT chargé en amont).
        conn: connexion SQLite.
        cabinet_id: filtre multi-mandant (= client_id en bexio_sync).
        mandant_id: identifiant du mandant ciblé (Sprint 2 : == cabinet_id).
        months: nombre de mois d'historique à pull (défaut 12).
        page_size: taille page Bexio (défaut 100).
        sleep_between_pages_s: pause entre pages (rate limit). 0 en test.
        max_retries: tentatives sur 429.
        backoff_base: base exponentielle.
        force_refresh: purge bexio_sync entity_type='manual_entry' avant pull.
        dry_run: pas d'écriture DB ni audit.
        user_id: propagé à l'audit event.
    """
    t0 = time.perf_counter()
    summary = ImportSummary(
        cabinet_id=cabinet_id, mandant_id=mandant_id,
        months=months, dry_run=dry_run,
    )

    date_from, date_to = _month_range_iso(months)
    _log.info(
        "bexio_history_import cabinet=%s mandant=%s months=%d "
        "range=%s..%s page=%d dry_run=%s",
        cabinet_id, mandant_id, months, date_from, date_to,
        page_size, dry_run,
    )

    # 1. Force refresh (purge avant pull)
    if force_refresh and not dry_run:
        conn.execute(
            "DELETE FROM bexio_sync WHERE client_id=? "
            "AND entity_type='manual_entry'",
            (cabinet_id,),
        )

    # 2. Plan comptable
    accounts = client.fetch_account_plan()
    if not dry_run:
        summary.accounts_synced = _persist_accounts(conn, cabinet_id, accounts)
    else:
        summary.accounts_synced = len(accounts)

    # 3. Contacts
    contacts = client.fetch_contacts(limit=1000)
    if not dry_run:
        summary.contacts_synced = _persist_contacts(conn, cabinet_id, contacts)
    else:
        summary.contacts_synced = len(contacts)

    # 4. Manual entries paginé
    offset = 0
    total = 0
    while True:
        page = _fetch_manual_entries_page(
            client, offset=offset, page_size=page_size,
            date_from=date_from, date_to=date_to,
            max_retries=max_retries, backoff_base=backoff_base,
        )
        if not page:
            break
        if not dry_run:
            for payload in page:
                _persist_entry(conn, cabinet_id, payload)
        total += len(page)
        if len(page) < page_size:
            break
        offset += page_size
        if sleep_between_pages_s > 0:
            time.sleep(sleep_between_pages_s)
    summary.entries_imported = total

    # 5. Reconstruit vendor_account_history (skip dry-run)
    if not dry_run:
        recs = build_history_from_bexio_cache(conn, cabinet_id)
        summary.vendor_recs_built = len(recs)

    # 6. Audit event (skip dry-run)
    if not dry_run:
        _audit.init_audit_schema(conn)
        _audit.log_audit_event(
            conn,
            cabinet_id=cabinet_id,
            entity_type="bexio_sync",
            entity_id=f"{cabinet_id}:{mandant_id}",
            action="bexio_history_imported",
            user_id=user_id,
            after={
                "accounts_count": summary.accounts_synced,
                "contacts_count": summary.contacts_synced,
                "entries_count": summary.entries_imported,
                "months": months,
                "vendor_rec_count": summary.vendor_recs_built,
            },
        )

    summary.duration_s = time.perf_counter() - t0
    _log.info(
        "bexio_history_import done cabinet=%s entries=%d vendors=%d "
        "dur=%.2fs",
        cabinet_id, summary.entries_imported, summary.vendor_recs_built,
        summary.duration_s,
    )
    return summary
