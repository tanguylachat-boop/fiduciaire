"""CLI : lance le matcher facture↔paiement sur bank_transactions non matchées.

Usage :
  python worker/scripts/run_bank_matcher.py --client-id pilote-jura-01
  python worker/scripts/run_bank_matcher.py --client-id pilote-jura-01 \\
    --auto-apply-threshold 0.85
  python worker/scripts/run_bank_matcher.py --client-id pilote-jura-01 --dry-run
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
from fiduciaire_worker.bank_camt import init_bank_schema  # noqa: E402
from fiduciaire_worker.bank_matcher import match_bank_transactions  # noqa: E402
from fiduciaire_worker.config import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Match bank_transactions ↔ accounting_entries.",
    )
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--mandant", default=None,
                        help="Filtre par mandant. Défaut: tous.")
    parser.add_argument("--auto-apply-threshold", type=float, default=0.9)
    parser.add_argument("--dry-run", action="store_true")
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
    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    init_bank_schema(conn)

    print(f"BANK MATCHER")
    print(f"  cabinet     : {args.client_id}")
    print(f"  mandant     : {args.mandant or '(tous)'}")
    print(f"  threshold   : {args.auto_apply_threshold}")
    print(f"  dry_run     : {args.dry_run}")
    print()

    report = match_bank_transactions(
        cabinet_id=args.client_id, client_id=args.mandant, conn=conn,
        auto_apply_threshold=args.auto_apply_threshold,
        dry_run=args.dry_run,
    )

    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  scanned          : {report.transactions_scanned}")
    print(f"  auto-matched     : {report.auto_matched}")
    print(f"  suggestions      : {report.suggestions_above_threshold} (UI review)")
    print(f"  no match         : {report.no_match}")
    print(f"  duration         : {report.duration_s:.2f}s")
    print(f"─────────────────────────────────────────────────────")
    if report.candidates and args.log_level.upper() == "DEBUG":
        print("\nCandidates :")
        for c in report.candidates[:10]:
            print(f"  tx={c.transaction_id} → doc={c.document_id} "
                  f"strategy={c.strategy} conf={c.confidence:.2f}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
