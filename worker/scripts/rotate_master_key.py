"""Rotation de la clé maître + re-chiffrement de tous les fichiers archive.

⚠️  À exécuter rarement (rotation annuelle ou en cas de compromission soupçonnée).
La nouvelle clé remplace l'ancienne dans le Keychain — backup l'ancienne avant !

Usage :
  python worker/scripts/rotate_master_key.py --client-id pilote-jura-01
  python worker/scripts/rotate_master_key.py --client-id pilote-jura-01 --dry-run
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
    is_encryption_disabled,
    rotate_key_and_re_encrypt,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rotate master encryption key + re-encrypt archive.",
    )
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--archive-root", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche ce qui SERAIT fait sans toucher aux fichiers.")
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

    if args.dry_run:
        files = [p for p in archive_root.rglob("*") if p.is_file()]
        print(f"[DRY-RUN] Aurait re-chiffré {len(files)} fichiers depuis {archive_root}.")
        print("[DRY-RUN] Aucune clé générée, aucun fichier modifié.")
        return 0

    print(f"⚠️  Rotation clé pour cabinet={args.client_id}")
    print(f"   archive_root: {archive_root}")
    confirm = input("   Tape 'ROTATE' pour confirmer: ")
    if confirm.strip() != "ROTATE":
        print("✗ annulé", file=sys.stderr)
        return 1

    t0 = time.perf_counter()
    result = rotate_key_and_re_encrypt(args.client_id, archive_root)
    wall = time.perf_counter() - t0

    print()
    print(f"─── ROTATION SUMMARY ────────────────────────────────")
    print(f"  re-encrypted    : {result.files_re_encrypted}")
    print(f"  skipped (plain) : {result.files_skipped_already_plain}")
    print(f"  errors          : {len(result.errors)}")
    print(f"  duration        : {wall:.1f}s")
    if result.errors:
        print()
        print("⚠️  Erreurs (clé Keychain PAS mise à jour — l'ancienne reste valide) :")
        for err in result.errors[:20]:
            print(f"   - {err}")
    else:
        print()
        print("✓ Clé Keychain mise à jour.")
    print(f"─────────────────────────────────────────────────────")
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
