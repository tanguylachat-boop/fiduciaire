"""CLI : génère un rapport mensuel Markdown pour 1 mandant.

Usage :
  python worker/scripts/generate_monthly_report.py \\
    --cabinet-id pilote-jura-01 \\
    --client-id pilote-jura-01 \\
    --year 2026 --month 4 \\
    --output-dir reports/
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
        description="Rapport mensuel Markdown (KPIs + annexe).",
    )
    parser.add_argument("--cabinet-id", required=True,
                        help="Cabinet propriétaire (owner).")
    parser.add_argument("--client-id", required=True,
                        help="Mandant ciblé. Doit == cabinet-id en Sprint 2.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True, choices=range(1, 13))
    parser.add_argument("--output-dir", type=Path, required=True)
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
    print(f"  output-dir  : {args.output_dir}")
    print()

    t0 = time.perf_counter()
    try:
        summary = generate_monthly_report(
            cabinet_id=args.cabinet_id,
            client_id=args.client_id,
            year=args.year,
            month=args.month,
            output_dir=args.output_dir,
            conn=conn,
        )
    except PermissionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        conn.close()
        return 3
    finally:
        conn.close()

    wall = time.perf_counter() - t0
    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  CA HT mois  : {summary.kpis.revenue_chf_month:.2f} CHF")
    print(f"  Cumul YTD   : {summary.kpis.revenue_chf_ytd:.2f} CHF")
    print(f"  écritures   : {summary.kpis.entries_count}")
    print(f"  annexe rows : {summary.entries_in_annex}")
    print(f"  duration    : {wall:.2f}s")
    print(f"  md path     : {summary.md_path}")
    print(f"─────────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    sys.exit(main())
