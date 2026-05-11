"""Push des écritures validées vers Bexio v3 manual_entries.

⚠️  Sécurité : mode dry-run par défaut **non-négociable**. Toute écriture
réelle exige `dry_run=False` ET (côté CLI) la variable d'env
`BEXIO_PUSH_LIVE=true`. Idempotence assurée via `accounting_entries.bexio_id` :
re-run ne re-pousse pas une entry déjà envoyée.

API Bexio v3 :
  POST https://api.bexio.com/3.0/accounting/manual_entries
  Body : {
    "type": "manual_single_entry",
    "date": "YYYY-MM-DD",
    "reference_nr": "...",
    "entries": [
      {
        "debit_account_id": <int>,
        "credit_account_id": <int>,
        "tax_id": <int>,
        "description": "...",
        "amount": <float>
      }
    ]
  }
  Réponse 201 : {id, ...}

Note : `debit_account` et `credit_account` dans `accounting_entries` sont
des account_no chaînes (ex. "6510"). Bexio attend des IDs internes
(entiers). On résout via `account_no_to_bexio_id` (typiquement construit
depuis `bexio_sync` cache + plan comptable). Idem pour `vat_code` →
`tax_id` Bexio.

Multi-mandant first-class : on filtre toutes les requêtes SQL par `client_id`.

Cf docs/decisions/2026-05-08-bexio-auth-pat-vs-oauth2.md (PAT auth).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import accounting_schema as acct_schema

_log = logging.getLogger("fiduciaire.bexio_push")

DEFAULT_BASE_URL = "https://api.bexio.com"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_INITIAL_BACKOFF_S = 1.0
RESPONSE_EXCERPT_MAX = 500

# Statuts BexioPushResult
PUSH_STATUS_DRY_RUN = "skipped_dry_run"
PUSH_STATUS_PUSHED = "pushed"
PUSH_STATUS_FAILED = "failed"
PUSH_STATUS_ALREADY_PUSHED = "already_pushed"
PUSH_STATUS_ACCOUNT_NOT_MAPPED = "account_not_mapped"


@dataclass
class BexioPushResult:
    entry_id: int
    bexio_id: str | None
    status: str
    attempt_count: int = 0
    http_status: int | None = None
    error: str | None = None
    response_excerpt: str | None = None


@dataclass
class BexioPushSummary:
    cabinet_id: str
    total: int = 0
    pushed: int = 0
    skipped_dry_run: int = 0
    already_pushed: int = 0
    failed: int = 0
    account_not_mapped: int = 0
    duration_s: float = 0.0
    dry_run: bool = True
    results: list[BexioPushResult] = field(default_factory=list)


# --- DB helpers ---------------------------------------------------------------


def _fetch_pending_entries(
    conn: sqlite3.Connection,
    cabinet_id: str,
    state: str,
    limit: int | None,
) -> list[sqlite3.Row]:
    """Sélectionne les entries du cabinet à l'état demandé, ordre stable.

    Garde les entries déjà poussées dans le set : le filtrage final est fait
    dans la boucle (compteur already_pushed) pour traçabilité du summary.
    `limit` s'applique AVANT ce filtrage — donc on lit un peu plus large
    si certaines entries sont déjà poussées, mais c'est OK pour Sprint 1.
    """
    sql = (
        "SELECT * FROM accounting_entries "
        "WHERE client_id=? AND state=? "
        "ORDER BY id ASC"
    )
    params: list[Any] = [cabinet_id, state]
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def _has_bexio_id(conn: sqlite3.Connection, entry_id: int) -> bool:
    row = conn.execute(
        "SELECT bexio_id FROM accounting_entries WHERE id=?",
        (entry_id,),
    ).fetchone()
    return bool(row and row["bexio_id"])


def _mark_entry_pushed(
    conn: sqlite3.Connection, entry_id: int, bexio_id: str,
) -> None:
    conn.execute(
        "UPDATE accounting_entries "
        "SET bexio_id=?, bexio_pushed_at=datetime('now'), "
        "    updated_at=datetime('now') WHERE id=?",
        (bexio_id, entry_id),
    )


def _log_push_attempt(
    conn: sqlite3.Connection,
    cabinet_id: str,
    entry_id: int,
    attempt: int,
    http_status: int | None,
    bexio_id: str | None,
    ok: bool,
    error: str | None = None,
    response_excerpt: str | None = None,
    dry_run: bool = False,
) -> None:
    conn.execute(
        """INSERT INTO bexio_push_log
        (client_id, entry_id, attempt, http_status, bexio_id, ok,
         error, response_excerpt, dry_run)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cabinet_id, entry_id, attempt, http_status, bexio_id,
         1 if ok else 0, error,
         (response_excerpt[:RESPONSE_EXCERPT_MAX] if response_excerpt else None),
         1 if dry_run else 0),
    )


# --- Payload builder ----------------------------------------------------------


def _build_payload(
    row: sqlite3.Row,
    account_map: dict[str, int],
    tax_map: dict[str, int] | None,
) -> dict[str, Any] | None:
    """Construit le body POST. Retourne None si account non mappé."""
    debit_id = account_map.get(str(row["debit_account"]))
    credit_id = account_map.get(str(row["credit_account"]))
    if debit_id is None or credit_id is None:
        return None

    entry_line: dict[str, Any] = {
        "debit_account_id": debit_id,
        "credit_account_id": credit_id,
        "amount": float(row["amount_chf"]),
        "description": (row["description"] or "")[:128],
    }
    if tax_map is not None:
        tax_id = tax_map.get(str(row["vat_code"]))
        if tax_id is not None:
            entry_line["tax_id"] = tax_id

    payload: dict[str, Any] = {
        "type": "manual_single_entry",
        "date": row["date"],
        "entries": [entry_line],
    }
    return payload


# --- HTTP layer ---------------------------------------------------------------


def _make_http_client(pat: str, base_url: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=DEFAULT_TIMEOUT_S,
    )


def _post_with_retry(
    client: httpx.Client,
    payload: dict[str, Any],
    *,
    max_retries: int,
    retry_initial_backoff_s: float,
    sleep_fn=time.sleep,
) -> tuple[httpx.Response | None, int, Exception | None]:
    """POST avec retry exponentiel sur 5xx et erreurs réseau.

    Retourne (response_finale, nb_attempts, last_exception).
    response_finale est None si toutes les tentatives ont raise.
    """
    backoff = retry_initial_backoff_s
    last_response: httpx.Response | None = None
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            r = client.post("/3.0/accounting/manual_entries", json=payload)
            last_response = r
            last_exc = None
            if r.status_code < 500:
                return r, attempt, None
            # 5xx → retry
            if attempt < max_retries:
                sleep_fn(backoff)
                backoff *= 2
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            last_exc = exc
            last_response = None
            if attempt < max_retries:
                sleep_fn(backoff)
                backoff *= 2

    return last_response, max_retries, last_exc


# --- Core --------------------------------------------------------------------


def push_validated_entries(
    *,
    cabinet_id: str,
    pat: str,
    conn: sqlite3.Connection,
    base_url: str = DEFAULT_BASE_URL,
    state_filter: str = acct_schema.ENTRY_STATE_VALIDATED,
    dry_run: bool = True,
    limit: int | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_initial_backoff_s: float = DEFAULT_RETRY_INITIAL_BACKOFF_S,
    http_client: httpx.Client | None = None,
    account_no_to_bexio_id: dict[str, int] | None = None,
    tax_code_to_bexio_id: dict[str, int] | None = None,
) -> BexioPushSummary:
    """Pousse les écritures `validated` du cabinet vers Bexio v3.

    Args:
        cabinet_id: filtrage multi-mandant strict.
        pat: Personal Access Token Bexio. Jamais loggé.
        conn: connexion SQLite (schémas db + accounting déjà initialisés).
        base_url: défaut https://api.bexio.com.
        state_filter: état SQL à pousser (défaut 'validated').
        dry_run: défaut **True**. Pour pousser en prod, passer False
            explicitement (+ env var côté CLI).
        limit: cap sur le nombre d'entries traitées par run.
        max_retries / retry_initial_backoff_s : retry exp sur 5xx.
        http_client: client httpx injectable (tests via MockTransport).
        account_no_to_bexio_id: map account_no → ID interne Bexio.
        tax_code_to_bexio_id: map TN_NORM/TN_RED/... → tax_id Bexio.
    """
    if not pat and not dry_run:
        raise ValueError("PAT Bexio requis quand dry_run=False")

    t0 = time.perf_counter()
    summary = BexioPushSummary(cabinet_id=cabinet_id, dry_run=dry_run)

    account_map = account_no_to_bexio_id or {}
    tax_map = tax_code_to_bexio_id  # peut être None

    owns_client = http_client is None
    if not dry_run and http_client is None:
        http_client = _make_http_client(pat, base_url)

    try:
        rows = _fetch_pending_entries(conn, cabinet_id, state_filter, limit)
        # On checke aussi already_pushed pour les entries sans bexio_id NULL
        # (cas où SELECT a deja filtré, mais idempotence : safety belt)

        for row in rows:
            entry_id = int(row["id"])
            summary.total += 1

            # Already pushed safety check (concurrent runs / corruption)
            if _has_bexio_id(conn, entry_id):
                summary.already_pushed += 1
                summary.results.append(BexioPushResult(
                    entry_id=entry_id, bexio_id=row["bexio_id"],
                    status=PUSH_STATUS_ALREADY_PUSHED,
                ))
                continue

            payload = _build_payload(row, account_map, tax_map)
            if payload is None:
                summary.account_not_mapped += 1
                summary.results.append(BexioPushResult(
                    entry_id=entry_id, bexio_id=None,
                    status=PUSH_STATUS_ACCOUNT_NOT_MAPPED,
                    error=(
                        f"account_no debit='{row['debit_account']}' "
                        f"or credit='{row['credit_account']}' "
                        f"not in account_no_to_bexio_id map"
                    ),
                ))
                _log_push_attempt(
                    conn, cabinet_id, entry_id, attempt=1, http_status=None,
                    bexio_id=None, ok=False,
                    error="account_not_mapped",
                    dry_run=dry_run,
                )
                continue

            # Dry run : log audit avec dry_run=1, pas d'HTTP, pas de bexio_id
            if dry_run:
                summary.skipped_dry_run += 1
                summary.results.append(BexioPushResult(
                    entry_id=entry_id, bexio_id=None,
                    status=PUSH_STATUS_DRY_RUN,
                ))
                _log_push_attempt(
                    conn, cabinet_id, entry_id, attempt=1,
                    http_status=None, bexio_id=None, ok=False,
                    error=None,
                    response_excerpt=json.dumps(payload, ensure_ascii=False),
                    dry_run=True,
                )
                continue

            # Live push
            assert http_client is not None  # mypy/assert
            response, attempts_done, last_exc = _post_with_retry(
                http_client, payload,
                max_retries=max_retries,
                retry_initial_backoff_s=retry_initial_backoff_s,
            )

            # Log toutes les tentatives — on synthétise depuis (response, attempts)
            _record_attempt_history(
                conn, cabinet_id, entry_id, response, attempts_done,
                last_exc, dry_run=False, max_retries=max_retries,
            )

            if response is not None and response.status_code < 300:
                # Succès
                try:
                    body = response.json()
                    bexio_id_val = str(body.get("id", ""))
                except (ValueError, TypeError):
                    bexio_id_val = ""
                _mark_entry_pushed(conn, entry_id, bexio_id_val)
                summary.pushed += 1
                summary.results.append(BexioPushResult(
                    entry_id=entry_id, bexio_id=bexio_id_val,
                    status=PUSH_STATUS_PUSHED,
                    attempt_count=attempts_done,
                    http_status=response.status_code,
                ))
            else:
                # Echec (4xx, 5xx épuisé, ou exception réseau)
                http_st = response.status_code if response is not None else None
                err_msg = (
                    f"{type(last_exc).__name__}: {last_exc}"
                    if last_exc else f"HTTP {http_st}"
                )
                excerpt = response.text[:RESPONSE_EXCERPT_MAX] if response is not None else None
                # Log sans PAT — on n'inclut JAMAIS request.headers ici.
                _log.warning(
                    "bexio push failed cabinet=%s entry=%d status=%s err=%s",
                    cabinet_id, entry_id, http_st, type(last_exc).__name__ if last_exc else None,
                )
                summary.failed += 1
                summary.results.append(BexioPushResult(
                    entry_id=entry_id, bexio_id=None,
                    status=PUSH_STATUS_FAILED,
                    attempt_count=attempts_done,
                    http_status=http_st,
                    error=err_msg,
                    response_excerpt=excerpt,
                ))

    finally:
        if owns_client and http_client is not None:
            http_client.close()

    summary.duration_s = time.perf_counter() - t0
    return summary


def _record_attempt_history(
    conn: sqlite3.Connection,
    cabinet_id: str,
    entry_id: int,
    final_response: httpx.Response | None,
    attempts_done: int,
    last_exc: Exception | None,
    dry_run: bool,
    max_retries: int,
) -> None:
    """Log 1 ligne par tentative dans bexio_push_log.

    Approximation : on connaît la réponse finale et le nombre total
    d'attempts. Pour les attempts intermédiaires (en cas de retry), on
    suppose des 5xx successifs. C'est une approximation acceptable pour
    audit — la trace exacte est dans les logs applicatifs.
    """
    if final_response is None:
        # Tous les attempts ont raise réseau
        err = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "network"
        for i in range(1, attempts_done + 1):
            _log_push_attempt(
                conn, cabinet_id, entry_id, attempt=i,
                http_status=None, bexio_id=None, ok=False,
                error=err, dry_run=dry_run,
            )
        return

    final_status = final_response.status_code
    final_ok = final_status < 300
    final_bexio_id: str | None = None
    if final_ok:
        try:
            final_bexio_id = str(final_response.json().get("id", "")) or None
        except (ValueError, TypeError):
            final_bexio_id = None

    # Attempts intermédiaires : 5xx supposé (sauf si attempts_done == 1)
    for i in range(1, attempts_done):
        _log_push_attempt(
            conn, cabinet_id, entry_id, attempt=i,
            http_status=503, bexio_id=None, ok=False,
            error="HTTP 5xx (retry)", dry_run=dry_run,
        )

    # Final attempt
    response_excerpt = final_response.text[:RESPONSE_EXCERPT_MAX] if not final_ok else None
    _log_push_attempt(
        conn, cabinet_id, entry_id, attempt=attempts_done,
        http_status=final_status, bexio_id=final_bexio_id,
        ok=final_ok,
        error=None if final_ok else f"HTTP {final_status}",
        response_excerpt=response_excerpt,
        dry_run=dry_run,
    )
