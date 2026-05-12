"""CLI : scan des anomalies + persistance dans table `anomalies`.

Usage :
  python worker/scripts/scan_anomalies.py --client-id pilote-jura-01
  python worker/scripts/scan_anomalies.py --client-id pilote-jura-01 \\
    --rules vat_no_evidence potential_duplicate

Idempotent : ré-exécution ne crée pas de doublons (UNIQUE constraint).
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
from fiduciaire_worker.missing_docs_detector import (  # noqa: E402
    init_anomalies_schema,
    list_open_anomalies,
    scan_anomalies,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scanne et persiste les anomalies du cabinet.",
    )
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--rules", nargs="+", default=None,
        help="Types d'anomalies à scanner. Défaut: toutes.",
    )
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
    init_anomalies_schema(conn)

    print(f"SCAN ANOMALIES")
    print(f"  cabinet     : {args.client_id}")
    print(f"  db          : {db_path}")
    print(f"  rules       : {args.rules or '(toutes)'}")
    print()

    t0 = time.perf_counter()
    report = scan_anomalies(
        cabinet_id=args.client_id, conn=conn, rules=args.rules,
    )
    wall = time.perf_counter() - t0

    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  rules run     : {', '.join(report.rules_run)}")
    print(f"  new anomalies : {report.new_anomalies}")
    print(f"  total open    : {report.existing_open}")
    print(f"  duration      : {wall:.2f}s")
    print(f"─────────────────────────────────────────────────────")

    if report.existing_open > 0:
        print()
        print("Open anomalies (10 premières) :")
        for ano in list_open_anomalies(conn, args.client_id)[:10]:
            print(f"  [{ano.severity}] {ano.type} {ano.subject_entity_type}#"
                  f"{ano.subject_entity_id} — {ano.details}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
