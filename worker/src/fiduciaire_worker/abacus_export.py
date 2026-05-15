"""Export écritures validées → Abacus AbaConnect XML — Sprint 2 Session 11.

Abacus est un ERP suisse leader, particulièrement dominant en comptabilité.
AbaConnect est son format d'échange officiel (XML schémas par module).
Schéma `AccountingDocument` ; détail XSD signé via canal partenaire Abacus.

Sprint 2 : on émet un XML inspiré AbaConnect avec balises publiquement
documentées (CamelCase officiel), ajustable post-import cabinet réel.

Cf decision doc `docs/decisions/2026-05-15-abacus-export-format.md`.

Multi-mandant first-class : filtre par `cabinet_id` (= client_id en DB).
Idempotent via `accounting_entries.abacus_exported_at`.

⚠️  Decrypt `description` avant écriture export (lien §3.4-bis).
⚠️  Audit log : chaque export live = un événement `entity_type=abacus_export`.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from . import audit_log as _audit
from . import encryption as _enc
from .accounting_schema import (
    ENTRY_STATE_VALIDATED,
    _add_column_if_missing,
    init_accounting_schema,
)

_log = logging.getLogger("fiduciaire.abacus_export")

FORMAT_VERSION = "1.0"
CURRENCY = "CHF"
XML_ROOT_TAG = "Data"
XML_ENTRY_TAG = "AccountingDocument"


@dataclass
class ExportSummary:
    cabinet_id: str
    output_path: Path | None
    rows_exported: int = 0
    rows_skipped_already_exported: int = 0
    duration_s: float = 0.0
    dry_run: bool = False


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent : ajoute abacus_exported_at si absent."""
    init_accounting_schema(conn)
    _add_column_if_missing(
        conn, "accounting_entries", "abacus_exported_at", "TEXT",
    )


# --- Query -----------------------------------------------------------------


def _fetch_validated_entries(
    conn: sqlite3.Connection,
    cabinet_id: str,
    client_id: str | None,
    date_from: str | None,
    date_to: str | None,
    state_filter: str,
    include_already_exported: bool,
    limit: int | None,
) -> list[sqlite3.Row]:
    sql = (
        "SELECT * FROM accounting_entries "
        "WHERE client_id = ? AND state = ?"
    )
    params: list = [cabinet_id, state_filter]
    if client_id and client_id != cabinet_id:
        sql += " AND client_id = ?"
        params.append(client_id)
    if date_from:
        sql += " AND date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date <= ?"
        params.append(date_to)
    if not include_already_exported:
        sql += (
            " AND (abacus_exported_at IS NULL OR abacus_exported_at = '')"
        )
    sql += " ORDER BY date ASC, id ASC"
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def _row_to_payload(row: sqlite3.Row, cabinet_id: str) -> dict[str, str]:
    description_plain = _enc.decrypt_column_value(
        row["description"], cabinet_id,
    ) or ""
    return {
        "DocumentDate": row["date"] or "",
        "Currency": CURRENCY,
        "AccountNumber": str(row["debit_account"] or ""),
        "AccountNumberAgainst": str(row["credit_account"] or ""),
        "Amount": f"{float(row['amount_chf'] or 0):.2f}",
        "Text": description_plain[:500],
        "VatCode": row["vat_code"] or "",
        "OrderNumber": row["bexio_id"] or "",
        "ClientReference": cabinet_id,
    }


def _mark_exported(conn: sqlite3.Connection, entry_ids: list[int]) -> None:
    if not entry_ids:
        return
    qmarks = ",".join("?" for _ in entry_ids)
    conn.execute(
        f"UPDATE accounting_entries SET "
        f"abacus_exported_at=datetime('now'), updated_at=datetime('now') "
        f"WHERE id IN ({qmarks})",
        entry_ids,
    )


# --- Public API ------------------------------------------------------------


def export_to_abacus_xml(
    *,
    cabinet_id: str,
    conn: sqlite3.Connection,
    output_path: Path | None = None,
    client_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    state_filter: str = ENTRY_STATE_VALIDATED,
    dry_run: bool = False,
    mark_exported: bool = True,
    include_already_exported: bool = False,
    limit: int | None = None,
    user_id: str | None = None,
) -> ExportSummary:
    """Export Abacus AbaConnect XML (module AccountingDocument).

    Args:
        cabinet_id: filtre multi-mandant (= client_id en DB).
        output_path: chemin XML. Requis sauf dry_run.
        client_id: sous-mandant facultatif (Sprint 2 : == cabinet_id).
        date_from / date_to: ISO YYYY-MM-DD inclus.
        state_filter: défaut 'validated'.
        dry_run: pas de fichier ni de mark ni d'audit log.
        mark_exported: si True (défaut), persiste `abacus_exported_at`.
        include_already_exported: ré-exporte entries marquées.
        limit: cap max d'entries.
        user_id: optionnel, propagé à l'audit log.
    """
    t0 = time.perf_counter()
    summary = ExportSummary(
        cabinet_id=cabinet_id, output_path=output_path, dry_run=dry_run,
    )

    if not dry_run and output_path is None:
        raise ValueError("output_path requis quand dry_run=False")

    _ensure_schema(conn)

    rows = _fetch_validated_entries(
        conn, cabinet_id, client_id, date_from, date_to, state_filter,
        include_already_exported, limit,
    )

    exported_ids: list[int] = []
    payload_rows: list[dict[str, str]] = []
    for row in rows:
        if not include_already_exported and row["abacus_exported_at"]:
            summary.rows_skipped_already_exported += 1
            continue
        payload_rows.append(_row_to_payload(row, cabinet_id))
        exported_ids.append(int(row["id"]))

    if dry_run:
        summary.rows_exported = len(payload_rows)
        summary.duration_s = time.perf_counter() - t0
        return summary

    # Build XML
    root = ET.Element(XML_ROOT_TAG, attrib={
        "cabinet_id": cabinet_id,
        "abacs_export_version": FORMAT_VERSION,
        "generator": "fiduciaire-ai/sprint-2",
    })
    for r in payload_rows:
        entry_el = ET.SubElement(root, XML_ENTRY_TAG)
        for key, value in r.items():
            sub = ET.SubElement(entry_el, key)
            sub.text = value

    tree = ET.ElementTree(root)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    if mark_exported:
        _mark_exported(conn, exported_ids)

    summary.rows_exported = len(payload_rows)
    summary.duration_s = time.perf_counter() - t0

    # Audit log live (pas en dry-run, déjà court-circuité plus haut)
    _audit.init_audit_schema(conn)
    _audit.log_audit_event(
        conn,
        cabinet_id=cabinet_id,
        entity_type="abacus_export",
        entity_id=f"{cabinet_id}:{output_path.name}",
        action="exported",
        user_id=user_id,
        after={
            "format": "abaconnect-xml",
            "client_id": client_id or cabinet_id,
            "rows_count": summary.rows_exported,
            "output_path": str(output_path),
        },
    )

    _log.info(
        "abacus XML export cabinet=%s path=%s rows=%d dur=%.2fs",
        cabinet_id, output_path, summary.rows_exported, summary.duration_s,
    )
    return summary
