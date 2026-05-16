"""CLI : import N mois d'historique Bexio pour 1 mandant.

Usage :
  python worker/scripts/import_bexio_history.py \\
    --cabinet-id gravosig-fiduciaire-01 \\
    --mandant-id mandant-pme-01 \\
    --months 12

  # Dry-run preview
  ... --dry-run

  # Force refresh (purge entries existantes avant pull)
  ... --force-refresh

⚠️  Rate limit Bexio : 60 req/min PAT standard. Sleep 1.2s/page par défaut.
⚠️  PAT chargé depuis Keychain macOS (cf secrets.py) ; jamais loggé en clair.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, audit_log, db  # noqa: E402
from fiduciaire_worker.bexio_client import BexioReadOnlyClient  # noqa: E402
from fiduciaire_worker.bexio_history_import import (  # noqa: E402
    import_bexio_history,
)
from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker import secrets as _secrets  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import N mois d'historique Bexio pour 1 mandant.",
    )
    parser.add_argument("--cabinet-id", required=True,
                        help="= client_id en DB (= cabinet propriétaire).")
    parser.add_argument("--mandant-id", required=True,
                        help="Sprint 2 : doit == cabinet-id.")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--sleep-s", type=float, default=1.2,
                        help="Pause entre pages (rate limit).")
    parser.add_argument("--rate-limit-req-per-min", type=int, default=None,
                        help="Override conservateur (PAT Pro = 300).")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Purge entries existantes avant pull.")
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
    if not db_path.exists():
        print(f"✗ DB introuvable : {db_path}", file=sys.stderr)
        return 2

    # Charge PAT depuis Keychain / env. Convention : 1 PAT par mandant.
    # Le user keyring est `bexio-pat-<mandant-id>` ; fallback global cabinet.
    try:
        pat = _secrets.get_bexio_pat(
            keyring_user=f"bexio-pat-{args.mandant_id}",
        )
    except RuntimeError:
        try:
            pat = _secrets.get_bexio_pat(
                keyring_user=f"bexio-pat-{args.cabinet_id}",
            )
        except RuntimeError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 5

    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    audit_log.init_audit_schema(conn)

    # Override rate limit si demandé
    sleep_s = args.sleep_s
    if args.rate_limit_req_per_min is not None and args.rate_limit_req_per_min > 0:
        sleep_s = max(0.0, 60.0 / args.rate_limit_req_per_min)

    print("BEXIO HISTORY IMPORT")
    print(f"  cabinet-id   : {args.cabinet_id}")
    print(f"  mandant-id   : {args.mandant_id}")
    print(f"  months       : {args.months}")
    print(f"  page-size    : {args.page_size}")
    print(f"  sleep        : {sleep_s:.2f}s")
    print(f"  force-refresh: {args.force_refresh}")
    print(f"  dry-run      : {args.dry_run}")
    print()

    user_id = os.environ.get("USER") or "system"

    t0 = time.perf_counter()
    with BexioReadOnlyClient(client_id=args.cabinet_id, pat=pat) as cli:
        summary = import_bexio_history(
            client=cli, conn=conn,
            cabinet_id=args.cabinet_id, mandant_id=args.mandant_id,
            months=args.months, page_size=args.page_size,
            sleep_between_pages_s=sleep_s,
            force_refresh=args.force_refresh,
            dry_run=args.dry_run, user_id=user_id,
        )
    wall = time.perf_counter() - t0

    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  accounts     : {summary.accounts_synced}")
    print(f"  contacts     : {summary.contacts_synced}")
    print(f"  entries      : {summary.entries_imported}")
    print(f"  vendor recs  : {summary.vendor_recs_built}")
    print(f"  dry-run      : {summary.dry_run}")
    print(f"  duration     : {wall:.2f}s")
    print(f"─────────────────────────────────────────────────────")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
