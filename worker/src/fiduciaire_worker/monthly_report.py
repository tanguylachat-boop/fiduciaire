"""Reporting mensuel basique — Sprint 2.

Génère un rapport mensuel (Markdown) par mandant avec :
- KPIs : CA HT du mois, cumul YTD, top 5 fournisseurs, position TVA estimée,
  trésorerie estimée (banque + créances - dettes)
- Annexe : 50 dernières écritures validées du mois

Multi-mandant first-class : un cabinet ne peut générer le rapport d'un
mandant qu'il possède (via filtre client_id).

PDF report reporté Session 11 (weasyprint pas critique pour install Gravosig
début juin : le Markdown reste lisible/imprimable).

⚠️  Decrypt automatique des colonnes chiffrées avant inclusion dans le rapport.
"""

from __future__ import annotations

import calendar
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import encryption as _enc
from .accounting_schema import ENTRY_STATE_VALIDATED

_log = logging.getLogger("fiduciaire.monthly_report")

REPORT_VERSION = "1.0"


@dataclass
class ReportKPIs:
    revenue_chf_month: float = 0.0  # CA HT du mois
    revenue_chf_ytd: float = 0.0  # cumul YTD
    vat_collected_chf: float = 0.0  # TVA collectée (compte 2200/2202)
    vat_deductible_chf: float = 0.0  # TVA déductible (compte 1170)
    vat_position_chf: float = 0.0  # collected - deductible
    treasury_estimated_chf: float = 0.0  # banque + créances - dettes
    top_vendors: list[tuple[str, float]] = field(default_factory=list)
    entries_count: int = 0


@dataclass
class ReportSummary:
    cabinet_id: str
    client_id: str
    year: int
    month: int
    md_path: Path | None = None
    pdf_path: Path | None = None
    kpis: ReportKPIs = field(default_factory=ReportKPIs)
    entries_in_annex: int = 0
    duration_s: float = 0.0


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return (
        f"{year:04d}-{month:02d}-01",
        f"{year:04d}-{month:02d}-{last_day:02d}",
    )


def _ytd_start(year: int) -> str:
    return f"{year:04d}-01-01"


# --- KPIs ------------------------------------------------------------------


def _fetch_revenue(
    conn: sqlite3.Connection,
    cabinet_id: str,
    date_from: str,
    date_to: str,
) -> float:
    """CA HT = somme amount_chf des écritures validated avec credit_account
    en 3xxx (produits) sur la période, pour ce mandant."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount_chf), 0) AS total
        FROM accounting_entries
        WHERE client_id = ?
          AND state = ?
          AND date BETWEEN ? AND ?
          AND credit_account LIKE '3%'
        """,
        (cabinet_id, ENTRY_STATE_VALIDATED, date_from, date_to),
    ).fetchone()
    return float(row["total"] or 0.0)


def _fetch_vat_collected(
    conn: sqlite3.Connection,
    cabinet_id: str,
    date_from: str,
    date_to: str,
) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(vat_amount), 0) AS total
        FROM accounting_entries
        WHERE client_id = ?
          AND state = ?
          AND date BETWEEN ? AND ?
          AND credit_account LIKE '3%'
          AND vat_code IN ('TN_NORM', 'TN_REDUC', 'TN_HEBERG')
        """,
        (cabinet_id, ENTRY_STATE_VALIDATED, date_from, date_to),
    ).fetchone()
    return float(row["total"] or 0.0)


def _fetch_vat_deductible(
    conn: sqlite3.Connection,
    cabinet_id: str,
    date_from: str,
    date_to: str,
) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(vat_amount), 0) AS total
        FROM accounting_entries
        WHERE client_id = ?
          AND state = ?
          AND date BETWEEN ? AND ?
          AND debit_account LIKE '4%' OR debit_account LIKE '6%'
        """,
        (cabinet_id, ENTRY_STATE_VALIDATED, date_from, date_to),
    ).fetchone()
    return float(row["total"] or 0.0)


def _fetch_treasury(
    conn: sqlite3.Connection,
    cabinet_id: str,
    date_to: str,
) -> float:
    """Trésorerie estimée = solde banque (1020) + créances clients (1100)
    - dettes fournisseurs (2000). Approximation simple, à raffiner Sprint 3."""
    # Solde banque : sum(debit-credit) pour comptes 102x
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN debit_account LIKE '102%'
                            THEN amount_chf ELSE 0 END), 0) AS bank_in,
          COALESCE(SUM(CASE WHEN credit_account LIKE '102%'
                            THEN amount_chf ELSE 0 END), 0) AS bank_out,
          COALESCE(SUM(CASE WHEN debit_account LIKE '1100'
                            THEN amount_chf ELSE 0 END), 0) AS receivables,
          COALESCE(SUM(CASE WHEN credit_account LIKE '2000'
                            THEN amount_chf ELSE 0 END), 0) AS payables
        FROM accounting_entries
        WHERE client_id = ?
          AND state = ?
          AND date <= ?
        """,
        (cabinet_id, ENTRY_STATE_VALIDATED, date_to),
    ).fetchone()
    return float(
        (row["bank_in"] - row["bank_out"])
        + row["receivables"]
        - row["payables"]
    )


def _fetch_top_vendors(
    conn: sqlite3.Connection,
    cabinet_id: str,
    date_from: str,
    date_to: str,
    limit: int = 5,
) -> list[tuple[str, float]]:
    """Top fournisseurs par montant total achats sur la période.

    Heuristique : utilise documents.classification_json LIKE pour extraire
    le creditor, ou fallback sur source_document_id agrégé par filename.
    Sprint 2 = approximation simple : on agrège par filename basename.
    """
    rows = conn.execute(
        """
        SELECT
          COALESCE(d.original_filename, 'inconnu') AS vendor_label,
          SUM(ae.amount_chf) AS total
        FROM accounting_entries ae
        LEFT JOIN documents d ON d.id = ae.source_document_id
        WHERE ae.client_id = ?
          AND ae.state = ?
          AND ae.date BETWEEN ? AND ?
          AND (ae.debit_account LIKE '4%' OR ae.debit_account LIKE '6%')
        GROUP BY vendor_label
        ORDER BY total DESC
        LIMIT ?
        """,
        (cabinet_id, ENTRY_STATE_VALIDATED, date_from, date_to, limit),
    ).fetchall()
    return [(r["vendor_label"], float(r["total"] or 0.0)) for r in rows]


def _fetch_entries_count(
    conn: sqlite3.Connection,
    cabinet_id: str,
    date_from: str,
    date_to: str,
) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM accounting_entries
        WHERE client_id = ?
          AND state = ?
          AND date BETWEEN ? AND ?
        """,
        (cabinet_id, ENTRY_STATE_VALIDATED, date_from, date_to),
    ).fetchone()
    return int(row["n"] or 0)


def _fetch_annex_entries(
    conn: sqlite3.Connection,
    cabinet_id: str,
    date_from: str,
    date_to: str,
    limit: int = 50,
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, date, debit_account, credit_account,
               amount_chf, vat_code, description
        FROM accounting_entries
        WHERE client_id = ?
          AND state = ?
          AND date BETWEEN ? AND ?
        ORDER BY date DESC, id DESC
        LIMIT ?
        """,
        (cabinet_id, ENTRY_STATE_VALIDATED, date_from, date_to, limit),
    ).fetchall()


# --- Rendu Markdown -------------------------------------------------------


def _fmt_chf(value: float) -> str:
    sign = "-" if value < 0 else ""
    abs_v = abs(value)
    return f"{sign}{abs_v:,.2f} CHF".replace(",", "'")


_FR_MONTHS = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _render_markdown(
    summary: ReportSummary,
    annex_rows: list[sqlite3.Row],
    cabinet_id: str,
) -> str:
    k = summary.kpis
    month_label = _FR_MONTHS[summary.month]
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = [
        f"# Rapport mensuel — {summary.client_id}",
        "",
        f"**Période :** {month_label} {summary.year}",
        f"**Mandant :** `{summary.client_id}`",
        f"**Généré le :** {generated}",
        f"**Version rapport :** {REPORT_VERSION}",
        "",
        "---",
        "",
        "## KPIs",
        "",
        f"| Indicateur | Valeur |",
        f"|---|---:|",
        f"| **CA HT du mois** | {_fmt_chf(k.revenue_chf_month)} |",
        f"| **Cumul YTD** | {_fmt_chf(k.revenue_chf_ytd)} |",
        f"| TVA collectée (mois) | {_fmt_chf(k.vat_collected_chf)} |",
        f"| TVA déductible (mois) | {_fmt_chf(k.vat_deductible_chf)} |",
        f"| **Position TVA estimée** | {_fmt_chf(k.vat_position_chf)} |",
        f"| **Trésorerie estimée** | {_fmt_chf(k.treasury_estimated_chf)} |",
        f"| Écritures validées (mois) | {k.entries_count} |",
        "",
    ]

    # Top fournisseurs
    lines += [
        "## Top 5 fournisseurs du mois",
        "",
    ]
    if not k.top_vendors:
        lines += ["_Aucune donnée fournisseur sur cette période._", ""]
    else:
        lines += [
            "| # | Fournisseur (libellé doc) | Montant |",
            "|---:|---|---:|",
        ]
        for i, (label, amount) in enumerate(k.top_vendors, 1):
            lines.append(f"| {i} | {label} | {_fmt_chf(amount)} |")
        lines.append("")

    # Annexe
    lines += [
        f"## Annexe — 50 dernières écritures validées du mois",
        "",
    ]
    if not annex_rows:
        lines += ["_Aucune écriture sur cette période._", ""]
    else:
        lines += [
            "| Date | Débit | Crédit | Montant | TVA | Description |",
            "|---|---|---|---:|---|---|",
        ]
        for r in annex_rows:
            desc = _enc.decrypt_column_value(
                r["description"], cabinet_id,
            ) or ""
            # Trim description pour table lisible
            desc_clean = desc.replace("|", "/").strip()[:80]
            lines.append(
                f"| {r['date']} | {r['debit_account']} | "
                f"{r['credit_account']} | "
                f"{_fmt_chf(float(r['amount_chf'] or 0))} | "
                f"{r['vat_code']} | {desc_clean} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        f"_Rapport généré par fiduciaire-ai · Sprint 2 · "
        f"approximations à raffiner Sprint 3 (pré-bouclement complet)._",
    ]
    return "\n".join(lines) + "\n"


# --- Public API -----------------------------------------------------------


def generate_monthly_report(
    *,
    cabinet_id: str,
    client_id: str,
    year: int,
    month: int,
    output_dir: Path,
    conn: sqlite3.Connection,
) -> ReportSummary:
    """Génère rapport Markdown pour 1 mandant / 1 mois.

    Multi-mandant strict : `cabinet_id` doit correspondre à `client_id` en
    DB (Sprint 2 convention 1 cabinet = 1 sous-mandant). Si un cabinet
    veut générer le rapport d'un mandant qui n'est pas le sien, les
    queries retourneront 0 lignes (filtre `WHERE client_id = cabinet_id`).

    Args:
        cabinet_id: cabinet propriétaire (filtre owner).
        client_id: sous-mandant ciblé pour le rapport. Doit == cabinet_id
                   en Sprint 2.
        year, month: période (mois calendaire).
        output_dir: dossier de sortie. Créé si absent.
        conn: connexion SQLite.
    """
    t0 = time.perf_counter()

    if not 1 <= month <= 12:
        raise ValueError(f"month invalide : {month}")

    # Multi-mandant strict : un cabinet ne peut générer que pour son propre
    # client_id. Si différent, on raise. (Le cas multi-sous-mandant viendra
    # quand la table mandants/clients distingue cabinet_id vs client_id.)
    if cabinet_id != client_id:
        raise PermissionError(
            f"Cabinet '{cabinet_id}' n'a pas accès au mandant "
            f"'{client_id}' (multi-mandant strict).",
        )

    date_from, date_to = _month_bounds(year, month)
    ytd_from = _ytd_start(year)

    summary = ReportSummary(
        cabinet_id=cabinet_id, client_id=client_id, year=year, month=month,
    )

    k = summary.kpis
    k.revenue_chf_month = _fetch_revenue(conn, cabinet_id, date_from, date_to)
    k.revenue_chf_ytd = _fetch_revenue(conn, cabinet_id, ytd_from, date_to)
    k.vat_collected_chf = _fetch_vat_collected(
        conn, cabinet_id, date_from, date_to,
    )
    k.vat_deductible_chf = _fetch_vat_deductible(
        conn, cabinet_id, date_from, date_to,
    )
    k.vat_position_chf = k.vat_collected_chf - k.vat_deductible_chf
    k.treasury_estimated_chf = _fetch_treasury(conn, cabinet_id, date_to)
    k.top_vendors = _fetch_top_vendors(conn, cabinet_id, date_from, date_to)
    k.entries_count = _fetch_entries_count(
        conn, cabinet_id, date_from, date_to,
    )

    annex = _fetch_annex_entries(conn, cabinet_id, date_from, date_to)
    summary.entries_in_annex = len(annex)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{client_id}_{year:04d}-{month:02d}_report.md"
    md_path = output_dir / filename
    md_content = _render_markdown(summary, annex, cabinet_id)
    md_path.write_text(md_content, encoding="utf-8")
    summary.md_path = md_path

    summary.duration_s = time.perf_counter() - t0
    _log.info(
        "monthly_report cabinet=%s client=%s %04d-%02d entries=%d "
        "revenue=%.2f dur=%.2fs",
        cabinet_id, client_id, year, month, k.entries_count,
        k.revenue_chf_month, summary.duration_s,
    )
    return summary
