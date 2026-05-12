"""CLI : lance un backup chiffré + applique la politique de rétention 30/12/10.

À déclencher via launchd quotidien (cf deploy/backup.plist.template) ou
manuel pour test.

Usage :
  python worker/scripts/backup_now.py
  python worker/scripts/backup_now.py --backup-dir /Volumes/ExtBackup
  python worker/scripts/backup_now.py --skip-retention
  python worker/scripts/backup_now.py --verify
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker.backup import (  # noqa: E402
    apply_retention,
    create_backup,
    verify_backup_restorable,
)
from fiduciaire_worker.config import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crée un backup chiffré + applique rétention 30/12/10.",
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path,
                        default=REPO_ROOT / "data" / "backups")
    parser.add_argument("--skip-retention", action="store_true")
    parser.add_argument("--verify", action="store_true",
                        help="Lance verify_backup_restorable sur le backup créé.")
    parser.add_argument("--daily-keep", type=int, default=30)
    parser.add_argument("--monthly-keep", type=int, default=12)
    parser.add_argument("--yearly-keep", type=int, default=10)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config(args.config)
    config.paths.ensure()

    print(f"BACKUP")
    print(f"  db          : {config.paths.db}")
    print(f"  archive     : {config.paths.archive}")
    print(f"  backup_dir  : {args.backup_dir}")
    print()

    t0 = time.perf_counter()
    try:
        result = create_backup(
            db_path=config.paths.db,
            archive_root=config.paths.archive,
            backup_dir=args.backup_dir,
        )
    except Exception as exc:
        print(f"✗ backup failed: {exc}", file=sys.stderr)
        return 1

    print(f"✓ backup created")
    print(f"  path        : {result.path}")
    print(f"  size        : {result.size_bytes / (1024 * 1024):.1f} MB")
    print(f"  db rows     : {result.db_rows_total}")
    print(f"  archive     : {result.archive_files} files")
    print(f"  duration    : {result.duration_s:.1f}s")

    if args.verify:
        print()
        print("Verification restorabilité...")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = verify_backup_restorable(result.path, Path(tmp))
        if ok:
            print("✓ backup vérifié restorable")
        else:
            print(f"✗ backup NON restorable : {reason}", file=sys.stderr)
            return 1

    if not args.skip_retention:
        print()
        print(f"Rétention {args.daily_keep}d / {args.monthly_keep}m / "
              f"{args.yearly_keep}y...")
        ret = apply_retention(
            args.backup_dir,
            daily_keep=args.daily_keep,
            monthly_keep=args.monthly_keep,
            yearly_keep=args.yearly_keep,
        )
        print(f"  kept daily   : {len(ret.kept_daily)}")
        print(f"  kept monthly : {len(ret.kept_monthly)}")
        print(f"  kept yearly  : {len(ret.kept_yearly)}")
        print(f"  deleted      : {len(ret.deleted)}")

    wall = time.perf_counter() - t0
    print(f"\n total: {wall:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
