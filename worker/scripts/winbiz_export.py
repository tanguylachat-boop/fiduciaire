"""CLI : export écritures validées → CSV/XML WinBIZ.

Usage :
  # CSV (défaut)
  python worker/scripts/winbiz_export.py \\
    --client-id pilote-jura-01 \\
    --output exports/pilote-jura-01-2026-q2.csv \\
    --date-from 2026-04-01 --date-to 2026-06-30

  # XML
  python worker/scripts/winbiz_export.py \\
    --client-id pilote-jura-01 \\
    --output exports/pilote-jura-01-2026-q2.xml --format xml

  # Dry-run (preview, pas de fichier ni mark)
  python worker/scripts/winbiz_export.py \\
    --client-id pilote-jura-01 --dry-run

⚠️  Idempotent : entries déjà exportées sont skippées sauf --include-already-exported.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker.winbiz_export import (  # noqa: E402
    export_to_winbiz_csv,
    export_to_winbiz_xml,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export entries validées → CSV/XML WinBIZ-compatible.",
    )
    parser.add_argument("--client-id", required=True,
                        help="Cabinet ID multi-mandant (= client_id en DB).")
    parser.add_argument("--output", type=Path,
                        help="Path du fichier export (requis sauf --dry-run).")
    parser.add_argument("--format", choices=["csv", "xml"], default="csv")
    parser.add_argument("--date-from", help="ISO YYYY-MM-DD inclus.")
    parser.add_argument("--date-to", help="ISO YYYY-MM-DD inclus.")
    parser.add_argument("--state", default="validated",
                        choices=["validated", "proposed"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-mark", action="store_true",
                        help="N'écrit pas winbiz_exported_at après export.")
    parser.add_argument("--include-already-exported", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
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

    conn: sqlite3.Connection = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    if not args.dry_run and args.output is None:
        print("✗ --output requis quand --dry-run absent.", file=sys.stderr)
        conn.close()
        return 2

    print(f"WINBIZ EXPORT")
    print(f"  cabinet     : {args.client_id}")
    print(f"  format      : {args.format}")
    print(f"  output      : {args.output if not args.dry_run else '(dry-run)'}")
    print(f"  state       : {args.state}")
    if args.date_from or args.date_to:
        print(f"  dates       : {args.date_from or '*'} → {args.date_to or '*'}")
    print()

    fn = export_to_winbiz_csv if args.format == "csv" else export_to_winbiz_xml

    t0 = time.perf_counter()
    try:
        summary = fn(
            cabinet_id=args.client_id,
            conn=conn,
            output_path=args.output,
            date_from=args.date_from,
            date_to=args.date_to,
            state_filter=args.state,
            dry_run=args.dry_run,
            mark_exported=not args.no_mark,
            include_already_exported=args.include_already_exported,
            limit=args.limit,
        )
    finally:
        conn.close()

    wall = time.perf_counter() - t0
    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  exported : {summary.rows_exported}")
    if summary.rows_skipped_already_exported:
        print(f"  skipped  : {summary.rows_skipped_already_exported} (déjà exportées)")
    print(f"  duration : {wall:.2f}s")
    if summary.output_path and not args.dry_run:
        print(f"  file     : {summary.output_path}")
    print(f"─────────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    sys.exit(main())
