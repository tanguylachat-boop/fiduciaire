"""Export écritures validées → WinBIZ (CSV générique / XML) — Sprint 1 §3.8.

Fallback CSV/XML si l'API WinBIZ native n'est pas accessible (partenariat
en cours). Format CSV générique avec headers explicites, ajustable selon
la version WinBIZ du cabinet (import manuel WinBIZ accepte ce format).

Cf decision doc `docs/decisions/2026-05-12-winbiz-export-format.md`.

Multi-mandant first-class : filtre par `cabinet_id` (= client_id en DB).
Idempotent via `accounting_entries.winbiz_exported_at` : re-run ne
ré-exporte pas les entries déjà exportées.

⚠️  Decrypt `description` avant écriture export (lien §3.4-bis).
"""

from __future__ import annotations

import csv
import logging
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import encryption as _enc
from .accounting_schema import ENTRY_STATE_VALIDATED

_log = logging.getLogger("fiduciaire.winbiz_export")

CSV_HEADERS = [
    "Date",
    "Compte_Debit",
    "Compte_Credit",
    "Montant",
    "Description",
    "Code_TVA",
    "Journal",
    "Reference_Bexio",
]

DEFAULT_JOURNAL = "ACH"  # Achats fournisseurs (par défaut Sprint 1)


@dataclass
class ExportSummary:
    cabinet_id: str
    format: str  # "csv" | "xml"
    output_path: Path | None
    rows_exported: int = 0
    rows_skipped_already_exported: int = 0
    rows_skipped_no_match: int = 0
    duration_s: float = 0.0
    dry_run: bool = False


# --- Query ------------------------------------------------------------------


def _fetch_validated_entries(
    conn: sqlite3.Connection,
    cabinet_id: str,
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
    if date_from:
        sql += " AND date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date <= ?"
        params.append(date_to)
    if not include_already_exported:
        sql += " AND (winbiz_exported_at IS NULL OR winbiz_exported_at = '')"
    sql += " ORDER BY date ASC, id ASC"
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def _row_to_dict(row: sqlite3.Row, cabinet_id: str) -> dict[str, str]:
    description_plain = _enc.decrypt_column_value(
        row["description"], cabinet_id,
    ) or ""
    return {
        "Date": row["date"] or "",
        "Compte_Debit": str(row["debit_account"] or ""),
        "Compte_Credit": str(row["credit_account"] or ""),
        "Montant": f"{float(row['amount_chf'] or 0):.2f}",
        "Description": description_plain[:200],
        "Code_TVA": row["vat_code"] or "",
        "Journal": DEFAULT_JOURNAL,
        "Reference_Bexio": row["bexio_id"] or "",
    }


def _mark_exported(conn: sqlite3.Connection, entry_ids: list[int]) -> None:
    if not entry_ids:
        return
    qmarks = ",".join("?" for _ in entry_ids)
    conn.execute(
        f"UPDATE accounting_entries SET "
        f"winbiz_exported_at=datetime('now'), updated_at=datetime('now') "
        f"WHERE id IN ({qmarks})",
        entry_ids,
    )


# --- Export CSV --------------------------------------------------------------


def export_to_winbiz_csv(
    *,
    cabinet_id: str,
    conn: sqlite3.Connection,
    output_path: Path | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    state_filter: str = ENTRY_STATE_VALIDATED,
    dry_run: bool = False,
    mark_exported: bool = True,
    include_already_exported: bool = False,
    limit: int | None = None,
) -> ExportSummary:
    """Export CSV format générique WinBIZ-compatible.

    Args:
        cabinet_id: filtre multi-mandant (= client_id en DB).
        output_path: chemin CSV. Si None et dry_run=False, raise.
        date_from / date_to: ISO YYYY-MM-DD inclus.
        state_filter: défaut 'validated'.
        dry_run: si True, ne crée pas le fichier ni n'updateworkflow.
        mark_exported: si True (défaut), persiste `winbiz_exported_at` après écriture.
        include_already_exported: si True, ré-exporte entries déjà marquées.
        limit: cap max d'entries.
    """
    t0 = time.perf_counter()
    summary = ExportSummary(
        cabinet_id=cabinet_id, format="csv", output_path=output_path,
        dry_run=dry_run,
    )

    if not dry_run and output_path is None:
        raise ValueError("output_path requis quand dry_run=False")

    rows = _fetch_validated_entries(
        conn, cabinet_id, date_from, date_to, state_filter,
        include_already_exported, limit,
    )

    exported_ids: list[int] = []
    payload_rows: list[dict[str, str]] = []
    for row in rows:
        # Si include_already_exported=False, on a déjà filtré au SQL,
        # mais re-check par safety (idempotence)
        if not include_already_exported and row["winbiz_exported_at"]:
            summary.rows_skipped_already_exported += 1
            continue
        payload_rows.append(_row_to_dict(row, cabinet_id))
        exported_ids.append(int(row["id"]))

    if dry_run:
        summary.rows_exported = len(payload_rows)
        summary.duration_s = time.perf_counter() - t0
        return summary

    # Écriture CSV
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, delimiter=";")
        writer.writeheader()
        writer.writerows(payload_rows)

    if mark_exported:
        _mark_exported(conn, exported_ids)

    summary.rows_exported = len(payload_rows)
    summary.duration_s = time.perf_counter() - t0
    _log.info(
        "winbiz CSV export cabinet=%s path=%s rows=%d dur=%.2fs",
        cabinet_id, output_path, summary.rows_exported, summary.duration_s,
    )
    return summary


# --- Export XML --------------------------------------------------------------


def export_to_winbiz_xml(
    *,
    cabinet_id: str,
    conn: sqlite3.Connection,
    output_path: Path | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    state_filter: str = ENTRY_STATE_VALIDATED,
    dry_run: bool = False,
    mark_exported: bool = True,
    include_already_exported: bool = False,
    limit: int | None = None,
) -> ExportSummary:
    """Export XML générique. Format : <winbiz_export><entry>...</entry></winbiz_export>.

    Note : pas de XSD officiel WinBIZ public en Sprint 1. Le format est
    documenté dans la decision doc et ajustable.
    """
    t0 = time.perf_counter()
    summary = ExportSummary(
        cabinet_id=cabinet_id, format="xml", output_path=output_path,
        dry_run=dry_run,
    )

    if not dry_run and output_path is None:
        raise ValueError("output_path requis quand dry_run=False")

    rows = _fetch_validated_entries(
        conn, cabinet_id, date_from, date_to, state_filter,
        include_already_exported, limit,
    )

    exported_ids: list[int] = []
    payload_rows: list[dict[str, str]] = []
    for row in rows:
        if not include_already_exported and row["winbiz_exported_at"]:
            summary.rows_skipped_already_exported += 1
            continue
        payload_rows.append(_row_to_dict(row, cabinet_id))
        exported_ids.append(int(row["id"]))

    if dry_run:
        summary.rows_exported = len(payload_rows)
        summary.duration_s = time.perf_counter() - t0
        return summary

    # Build XML
    root = ET.Element("winbiz_export", attrib={
        "cabinet_id": cabinet_id, "format_version": "1",
    })
    for r in payload_rows:
        entry_el = ET.SubElement(root, "entry")
        for key in CSV_HEADERS:
            sub = ET.SubElement(entry_el, key.lower())
            sub.text = r[key]

    tree = ET.ElementTree(root)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    if mark_exported:
        _mark_exported(conn, exported_ids)

    summary.rows_exported = len(payload_rows)
    summary.duration_s = time.perf_counter() - t0
    return summary
