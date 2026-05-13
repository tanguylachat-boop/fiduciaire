"""Export écritures validées → Crésus XML — Sprint 2.

Crésus (Epsitec SA) compte ~700 fiduciaires partenaires en Suisse, surtout
en Suisse romande. Le format XML est ouvert et documenté côté Crésus mais
varie selon la version du cabinet. On émet un format XML générique avec
balises explicites, ajustable au cas par cas selon le retour terrain.

Cf decision doc `docs/decisions/2026-05-13-cresus-export-format.md`.

Multi-mandant first-class : filtre par `cabinet_id` (= client_id en DB).
Idempotent via `accounting_entries.cresus_exported_at` : re-run ne
ré-exporte pas les entries déjà exportées.

⚠️  Decrypt `description` avant écriture export (lien §3.4-bis).
"""

from __future__ import annotations

import logging
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from . import encryption as _enc
from .accounting_schema import (
    ENTRY_STATE_VALIDATED,
    _add_column_if_missing,
    init_accounting_schema,
)

_log = logging.getLogger("fiduciaire.cresus_export")

FORMAT_VERSION = "1.0"
DEFAULT_JOURNAL = "ACH"
XML_ROOT_TAG = "EcrituresComptables"
XML_ENTRY_TAG = "Ecriture"


@dataclass
class ExportSummary:
    cabinet_id: str
    output_path: Path | None
    rows_exported: int = 0
    rows_skipped_already_exported: int = 0
    duration_s: float = 0.0
    dry_run: bool = False


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent : ajoute cresus_exported_at si absent."""
    init_accounting_schema(conn)
    _add_column_if_missing(
        conn, "accounting_entries", "cresus_exported_at", "TEXT",
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
        # Sous-mandant : si un cabinet groupe plusieurs sous-clients, on filtre
        # via une convention `client_id` ; à raffiner si le schéma évolue.
        sql += " AND client_id = ?"
        params.append(client_id)
    if date_from:
        sql += " AND date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date <= ?"
        params.append(date_to)
    if not include_already_exported:
        sql += " AND (cresus_exported_at IS NULL OR cresus_exported_at = '')"
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
        "Date": row["date"] or "",
        "Mandant": cabinet_id,
        "CompteDebit": str(row["debit_account"] or ""),
        "CompteCredit": str(row["credit_account"] or ""),
        "MontantCHF": f"{float(row['amount_chf'] or 0):.2f}",
        "Description": description_plain[:500],
        "CodeTVA": row["vat_code"] or "",
        "Journal": DEFAULT_JOURNAL,
        "ReferenceBexio": row["bexio_id"] or "",
    }


def _mark_exported(conn: sqlite3.Connection, entry_ids: list[int]) -> None:
    if not entry_ids:
        return
    qmarks = ",".join("?" for _ in entry_ids)
    conn.execute(
        f"UPDATE accounting_entries SET "
        f"cresus_exported_at=datetime('now'), updated_at=datetime('now') "
        f"WHERE id IN ({qmarks})",
        entry_ids,
    )


# --- Public API ------------------------------------------------------------


def export_to_cresus_xml(
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
) -> ExportSummary:
    """Export Crésus XML générique.

    Args:
        cabinet_id: filtre multi-mandant (= client_id en DB).
        output_path: chemin XML. Si None et dry_run=False, raise.
        client_id: sous-mandant facultatif (None = tout le cabinet).
        date_from / date_to: ISO YYYY-MM-DD inclus.
        state_filter: défaut 'validated'.
        dry_run: si True, pas de fichier ni de mark.
        mark_exported: si True (défaut), persiste `cresus_exported_at`.
        include_already_exported: ré-exporte entries marquées.
        limit: cap max d'entries.
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
        # Re-check par safety (race avec includes)
        if not include_already_exported and row["cresus_exported_at"]:
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
        "format_version": FORMAT_VERSION,
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
    _log.info(
        "cresus XML export cabinet=%s path=%s rows=%d dur=%.2fs",
        cabinet_id, output_path, summary.rows_exported, summary.duration_s,
    )
    return summary
