"""CLI : restaure un backup chiffré vers un dossier de destination.

⚠️  Ne touche PAS à la DB de prod. Restaure dans un dossier tmp pour audit
ou recovery sélectif.

Usage :
  python worker/scripts/restore_from_backup.py \\
    --backup data/backups/backup-2026-05-12-030000.tar.gz.fid \\
    --restore-dir /tmp/restored
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker.backup import restore_backup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restaure un backup chiffré.",
    )
    parser.add_argument("--backup", type=Path, required=True,
                        help="Path du fichier backup .tar.gz.fid")
    parser.add_argument("--restore-dir", type=Path, required=True,
                        help="Dossier destination (sera créé).")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.backup.exists():
        print(f"✗ backup introuvable : {args.backup}", file=sys.stderr)
        return 2

    try:
        result = restore_backup(args.backup, args.restore_dir)
    except Exception as exc:
        print(f"✗ restore failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    print(f"✓ restored")
    print(f"  db          : {result.db_path}")
    print(f"  archive     : {result.archive_path}")
    print(f"  db rows     : {result.db_rows_total}")
    print(f"  archive     : {result.archive_files} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
