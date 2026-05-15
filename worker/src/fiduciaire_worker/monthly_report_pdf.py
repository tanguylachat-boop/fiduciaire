"""Reporting mensuel PDF via WeasyPrint — Sprint 2 Session 11.

Réutilise `monthly_report.py` (génération Markdown KPIs + annexe) sans la
dupliquer. Pipeline : MD existant → HTML stylé (CSS print A4) → PDF
WeasyPrint à côté du .md.

Cf decision doc `docs/decisions/2026-05-15-pdf-reporting-weasyprint.md`.

Multi-mandant strict : `cabinet_id == client_id` requis (hérité de
`monthly_report.generate_monthly_report`).

⚠️  Decrypt des descriptions chiffrées : déjà fait en amont par le rendu
Markdown. Aucune valeur déchiffrée n'est loguée.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .monthly_report import ReportSummary, generate_monthly_report

_log = logging.getLogger("fiduciaire.monthly_report_pdf")

PDF_VERSION = "1.0"


# --- WeasyPrint guard ------------------------------------------------------


def _import_weasyprint():
    """Import isolé pour pouvoir monkeypatcher (test : weasyprint absent)."""
    import weasyprint  # noqa: WPS433 — import local volontaire
    return weasyprint


# --- Markdown → HTML -------------------------------------------------------


_PRINT_CSS = """
@page {
    size: A4 portrait;
    margin: 1.5cm 1.5cm 2cm 1.5cm;
    @bottom-left {
        content: "Généré le " string(generated-date);
        font-size: 8pt;
        color: #888;
    }
    @bottom-right {
        content: "Page " counter(page) " / " counter(pages);
        font-size: 8pt;
        color: #888;
    }
}

html { font-family: 'Inter', 'Helvetica', system-ui, sans-serif; }
body { color: #111; font-size: 10pt; line-height: 1.4; }

header.cabinet {
    border-bottom: 1px solid #888;
    padding-bottom: 6px;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
header.cabinet .left { font-size: 13pt; font-weight: 600; color: #222; }
header.cabinet .right { font-size: 10pt; color: #555; }
header.cabinet .meta-period { string-set: generated-date attr(data-generated); }

h1 { font-size: 18pt; color: #111; margin-top: 4pt; margin-bottom: 8pt; }
h2 { font-size: 13pt; color: #333; margin-top: 14pt; margin-bottom: 6pt;
     border-bottom: 1px solid #ccc; padding-bottom: 2pt; }

table { border-collapse: collapse; width: 100%; margin-bottom: 12pt; }
th, td {
    border: 1px solid #888;
    padding: 4px 6px;
    font-size: 10pt;
    vertical-align: top;
}
th { background: #f3f3f3; color: #222; text-align: left; font-weight: 600; }
td:last-child, th:last-child { text-align: right; }

table.annex { font-size: 9pt; }
table.annex th, table.annex td { padding: 3px 5px; }

hr { border: 0; border-top: 1px solid #ccc; margin: 12pt 0; }
strong { color: #111; }
em { color: #555; }
"""


def _md_to_html_document(
    md_text: str,
    *,
    cabinet_label: str | None,
    period_label: str,
    logo_path: Path | None = None,
) -> str:
    """Convertit le MD en HTML complet stylé pour impression.

    Args:
        md_text: contenu Markdown généré par `monthly_report`.
        cabinet_label: nom cabinet affiché dans le header (None ⇒ vide).
        period_label: ex. "avril 2026", affiché en header right.
        logo_path: chemin logo PNG/JPG ; placeholder si None.
    """
    import markdown  # noqa: WPS433

    body_html = markdown.markdown(
        md_text,
        extensions=["tables", "nl2br", "sane_lists"],
        output_format="html5",
    )
    # On veut classer la dernière table "annex" (font-size 9pt). Heuristique :
    # toutes les tables ayant >= 6 colonnes (Date | Débit | Crédit | … |
    # Description) sont l'annexe.
    body_html = _mark_annex_tables(body_html)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    logo_html = ""
    if logo_path is not None and logo_path.exists():
        logo_html = f'<img src="{logo_path.as_uri()}" alt="logo" height="32" />'
    cabinet = cabinet_label or ""

    return f"""<!doctype html>
<html lang="fr-CH">
<head>
<meta charset="utf-8">
<title>Rapport mensuel — {cabinet} — {period_label}</title>
<style>{_PRINT_CSS}</style>
</head>
<body>
<header class="cabinet">
  <div class="left">{logo_html} {cabinet}</div>
  <div class="right meta-period" data-generated="{generated}">
    Période : {period_label}
  </div>
</header>
{body_html}
</body>
</html>
"""


def _mark_annex_tables(html: str) -> str:
    """Ajoute class="annex" aux tables longues (>= 6 colonnes en header).

    Heuristique simple : compte le nombre de <th> dans la première ligne
    de chaque table. Pas de parser HTML lourd ; les tables MD générées
    par monthly_report ont des en-têtes constants.
    """
    out_parts: list[str] = []
    idx = 0
    while True:
        start = html.find("<table>", idx)
        if start == -1:
            out_parts.append(html[idx:])
            break
        out_parts.append(html[idx:start])
        end = html.find("</table>", start)
        if end == -1:
            out_parts.append(html[start:])
            break
        end += len("</table>")
        table_html = html[start:end]
        # Compte les <th> du premier <tr>
        first_tr = table_html.find("<tr>")
        if first_tr != -1:
            first_tr_end = table_html.find("</tr>", first_tr)
            header_block = table_html[first_tr:first_tr_end]
            th_count = header_block.count("<th>")
            if th_count >= 6:
                table_html = table_html.replace(
                    "<table>", '<table class="annex">', 1,
                )
        out_parts.append(table_html)
        idx = end
    return "".join(out_parts)


# --- Summary extension -----------------------------------------------------


@dataclass
class PdfReportSummary:
    """Wrapper enrichi : inclut le ReportSummary MD + pdf_path."""
    base: ReportSummary
    pdf_path: Path | None = None
    pdf_duration_s: float = 0.0

    # Délègue les attributs courants pour ergonomie / compat tests
    @property
    def md_path(self) -> Path | None:  # noqa: D401
        return self.base.md_path

    @property
    def cabinet_id(self) -> str:
        return self.base.cabinet_id

    @property
    def client_id(self) -> str:
        return self.base.client_id

    @property
    def year(self) -> int:
        return self.base.year

    @property
    def month(self) -> int:
        return self.base.month

    @property
    def kpis(self):
        return self.base.kpis


_FR_MONTHS_PDF = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


# --- Public API ------------------------------------------------------------


def generate_monthly_report_pdf(
    *,
    cabinet_id: str,
    client_id: str,
    year: int,
    month: int,
    output_dir: Path,
    conn: sqlite3.Connection,
    cabinet_label: str | None = None,
    logo_path: Path | None = None,
) -> PdfReportSummary:
    """Génère MD + PDF pour 1 mandant / 1 mois.

    Multi-mandant strict : `cabinet_id == client_id` requis (hérité de
    `generate_monthly_report` qui raise `PermissionError` sinon).

    Args:
        cabinet_id: cabinet propriétaire.
        client_id: sous-mandant (Sprint 2 : == cabinet_id).
        year, month: période.
        output_dir: dossier de sortie.
        conn: connexion SQLite.
        cabinet_label: nom affiché dans le header PDF (défaut = cabinet_id).
        logo_path: logo PNG/JPG cabinet (placeholder si None).

    Raises:
        RuntimeError: si `weasyprint` n'est pas installé. Message clair,
            pas de stack trace.
        PermissionError: si cross-mandant.
    """
    # On vérifie weasyprint d'abord pour échouer vite (avant de toucher la DB).
    try:
        weasyprint = _import_weasyprint()
    except ImportError as exc:
        raise RuntimeError(
            "weasyprint non installé. Installer via : "
            "pip install weasyprint",
        ) from exc

    md_summary = generate_monthly_report(
        cabinet_id=cabinet_id, client_id=client_id,
        year=year, month=month, output_dir=output_dir, conn=conn,
    )

    t0 = time.perf_counter()
    md_text = md_summary.md_path.read_text(encoding="utf-8")
    period_label = f"{_FR_MONTHS_PDF[month]} {year}"
    html_doc = _md_to_html_document(
        md_text,
        cabinet_label=cabinet_label or cabinet_id,
        period_label=period_label,
        logo_path=logo_path,
    )
    pdf_path = md_summary.md_path.with_suffix(".pdf")
    # WeasyPrint base_url permet de résoudre les paths relatifs (logo).
    weasyprint.HTML(
        string=html_doc, base_url=str(output_dir),
    ).write_pdf(pdf_path)

    duration = time.perf_counter() - t0
    _log.info(
        "monthly_report_pdf cabinet=%s client=%s %04d-%02d pdf=%s dur=%.2fs",
        cabinet_id, client_id, year, month, pdf_path, duration,
    )
    return PdfReportSummary(base=md_summary, pdf_path=pdf_path,
                            pdf_duration_s=duration)
