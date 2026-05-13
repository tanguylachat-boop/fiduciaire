"""CLI : importe un fichier CAMT.053 → table bank_transactions.

Usage :
  python worker/scripts/import_camt.py \\
    --client-id pilote-jura-01 \\
    --mandant pilote-jura-01 \\
    --file data/inbox/camt053-2026-04.xml
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
from fiduciaire_worker.bank_camt import (  # noqa: E402
    import_camt053_file,
    init_bank_schema,
)
from fiduciaire_worker.config import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import CAMT.053 → bank_transactions.",
    )
    parser.add_argument("--client-id", required=True, help="Cabinet ID.")
    parser.add_argument("--mandant", required=True,
                        help="Mandant client_id (sous-cabinet).")
    parser.add_argument("--file", type=Path, required=True,
                        help="Path du fichier CAMT.053 XML.")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.file.exists():
        print(f"✗ fichier introuvable : {args.file}", file=sys.stderr)
        return 2

    config = load_config(args.config)
    db_path = args.db if args.db is not None else config.paths.db
    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    init_bank_schema(conn)

    print(f"CAMT.053 IMPORT")
    print(f"  cabinet : {args.client_id}")
    print(f"  mandant : {args.mandant}")
    print(f"  file    : {args.file}")
    print(f"  db      : {db_path}")
    print()

    try:
        summary = import_camt053_file(
            path=args.file, cabinet_id=args.client_id,
            client_id=args.mandant, conn=conn,
        )
    except Exception as exc:
        print(f"✗ import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        conn.close()
        return 1

    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  IBAN          : {summary.iban}")
    print(f"  transactions  : {summary.transactions_total}")
    print(f"  ↳ inserted    : {summary.transactions_inserted}")
    print(f"  ↳ duplicates  : {summary.transactions_duplicates}")
    print(f"  duration      : {summary.duration_s:.2f}s")
    print(f"─────────────────────────────────────────────────────")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
