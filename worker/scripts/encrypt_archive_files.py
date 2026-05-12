"""Chiffre (in-place) tous les fichiers de `data/archive/<cabinet>/` via Fernet.

Idempotent : skip silencieusement les fichiers déjà chiffrés (magic FID1).

Usage :
  python worker/scripts/encrypt_archive_files.py --client-id pilote-jura-01
  python worker/scripts/encrypt_archive_files.py --client-id pilote-jura-01 \\
    --archive-root data/archive

⚠️  Avant prod, BACKUP la DB + les fichiers archive. Cette opération overwrite
les fichiers (même si idempotente sur les déjà chiffrés).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker.encryption import (  # noqa: E402
    encrypt_file,
    ensure_master_key,
    is_encrypted_file,
    is_encryption_disabled,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chiffre in-place les fichiers archive du cabinet.",
    )
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--archive-root", type=Path, default=None,
                        help="Dossier archive (défaut: config.paths.archive).")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if is_encryption_disabled():
        print("✗ FIDUCIAIRE_ENCRYPTION_DISABLED=true → no-op", file=sys.stderr)
        return 0

    config = load_config(args.config)
    archive_root = args.archive_root or config.paths.archive
    if not archive_root.exists():
        print(f"✗ archive_root introuvable: {archive_root}", file=sys.stderr)
        return 2

    # S'assure que la clé existe (Keychain ou env)
    key = ensure_master_key(args.client_id)
    print(f"✓ master key OK pour cabinet={args.client_id}")

    t0 = time.perf_counter()
    encrypted_count = 0
    skipped_count = 0
    error_count = 0

    files = sorted(p for p in archive_root.rglob("*") if p.is_file())
    print(f"Scanning {len(files)} files in {archive_root}")
    print()

    for path in files:
        if is_encrypted_file(path):
            skipped_count += 1
            continue
        if args.dry_run:
            print(f"  [DRY] would encrypt {path.relative_to(archive_root)}")
            encrypted_count += 1
            continue
        try:
            encrypt_file(path, path, cabinet_id=args.client_id)
            encrypted_count += 1
            print(f"  ✓ {path.relative_to(archive_root)}")
        except Exception as exc:
            error_count += 1
            print(f"  ✗ {path.relative_to(archive_root)}: {exc}",
                  file=sys.stderr)

    wall = time.perf_counter() - t0
    print()
    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  encrypted : {encrypted_count}")
    print(f"  skipped   : {skipped_count} (déjà chiffrés)")
    print(f"  errors    : {error_count}")
    print(f"  duration  : {wall:.1f}s")
    print(f"─────────────────────────────────────────────────────")

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
