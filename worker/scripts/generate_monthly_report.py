"""CLI : génère un rapport mensuel (Markdown et/ou PDF) pour 1 mandant.

Usage :
  # MD + PDF (défaut)
  python worker/scripts/generate_monthly_report.py \\
    --cabinet-id pilote-jura-01 \\
    --client-id pilote-jura-01 \\
    --year 2026 --month 4 \\
    --output-dir reports/

  # MD seul (Sprint 2 Session 10 behavior)
  ... --format md

  # PDF seul (le MD est généré en interne puis effacé)
  ... --format pdf

⚠️  PDF requiert `weasyprint` installé. Message d'erreur explicite si absent.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker.monthly_report import (  # noqa: E402
    generate_monthly_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rapport mensuel (Markdown / PDF / les deux).",
    )
    parser.add_argument("--cabinet-id", required=True,
                        help="Cabinet propriétaire (owner).")
    parser.add_argument("--client-id", required=True,
                        help="Mandant ciblé. Doit == cabinet-id en Sprint 2.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True,
                        choices=range(1, 13))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--format", choices=["md", "pdf", "both"], default="both",
        help="Format de sortie (défaut : both).",
    )
    parser.add_argument("--cabinet-label", default=None,
                        help="Nom cabinet affiché dans le header PDF.")
    parser.add_argument("--logo", type=Path, default=None,
                        help="Chemin logo PNG/JPG pour header PDF.")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config(args.config)
    db_path = args.db if args.db is not None else config.paths.db
    if not db_path.exists():
        print(f"✗ DB introuvable : {db_path}", file=sys.stderr)
        return 2

    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    print("MONTHLY REPORT")
    print(f"  cabinet     : {args.cabinet_id}")
    print(f"  mandant     : {args.client_id}")
    print(f"  période     : {args.year:04d}-{args.month:02d}")
    print(f"  format      : {args.format}")
    print(f"  output-dir  : {args.output_dir}")
    print()

    t0 = time.perf_counter()
    md_path: Path | None = None
    pdf_path: Path | None = None
    summary = None
    try:
        if args.format in ("md", "both"):
            summary = generate_monthly_report(
                cabinet_id=args.cabinet_id,
                client_id=args.client_id,
                year=args.year,
                month=args.month,
                output_dir=args.output_dir,
                conn=conn,
            )
            md_path = summary.md_path
        if args.format in ("pdf", "both"):
            # Import tardif pour ne pas exiger weasyprint si --format md
            from fiduciaire_worker.monthly_report_pdf import (
                generate_monthly_report_pdf,
            )
            try:
                pdf_summary = generate_monthly_report_pdf(
                    cabinet_id=args.cabinet_id,
                    client_id=args.client_id,
                    year=args.year,
                    month=args.month,
                    output_dir=args.output_dir,
                    conn=conn,
                    cabinet_label=args.cabinet_label,
                    logo_path=args.logo,
                )
            except RuntimeError as exc:
                print(f"✗ {exc}", file=sys.stderr)
                conn.close()
                return 4
            md_path = pdf_summary.md_path
            pdf_path = pdf_summary.pdf_path
            summary = pdf_summary.base
            if args.format == "pdf" and md_path and md_path.exists():
                # PDF seul demandé : on supprime le MD intermédiaire.
                md_path.unlink()
                md_path = None
    except PermissionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        conn.close()
        return 3
    finally:
        conn.close()

    wall = time.perf_counter() - t0
    print(f"─── SUMMARY ─────────────────────────────────────────")
    if summary is not None:
        print(f"  CA HT mois  : {summary.kpis.revenue_chf_month:.2f} CHF")
        print(f"  Cumul YTD   : {summary.kpis.revenue_chf_ytd:.2f} CHF")
        print(f"  écritures   : {summary.kpis.entries_count}")
        print(f"  annexe rows : {summary.entries_in_annex}")
    print(f"  duration    : {wall:.2f}s")
    if md_path is not None:
        print(f"  md path     : {md_path}")
    if pdf_path is not None:
        print(f"  pdf path    : {pdf_path}")
    print(f"─────────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    sys.exit(main())
