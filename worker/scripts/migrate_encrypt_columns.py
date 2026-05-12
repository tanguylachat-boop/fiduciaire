"""Migration : chiffre les colonnes texte sensibles d'une DB existante.

Sprint 1 §3.4-bis. Idempotent : skip silencieusement les valeurs déjà
préfixées `enc:v1:`. Multi-mandant strict : on filtre par cabinet_id.

Colonnes ciblées :
- accounting_entries.description
- accounting_entries.reasoning
- vendor_account_history.vendor_name
- email_messages.body_excerpt
- email_messages.from_addr

Usage :
  python worker/scripts/migrate_encrypt_columns.py \\
    --client-id pilote-jura-01 --dry-run
  python worker/scripts/migrate_encrypt_columns.py \\
    --client-id pilote-jura-01

⚠️  BACKUP la DB avant d'exécuter sans --dry-run.
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

from fiduciaire_worker import db  # noqa: E402
from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker.encryption import (  # noqa: E402
    ensure_master_key,
    is_encryption_disabled,
    migrate_column_in_place,
)

# (table, cabinet_id_column, target_column)
TARGETS: list[tuple[str, str, str]] = [
    ("accounting_entries", "client_id", "description"),
    ("accounting_entries", "client_id", "reasoning"),
    ("vendor_account_history", "client_id", "vendor_name"),
    ("email_messages", "cabinet_id", "body_excerpt"),
    ("email_messages", "cabinet_id", "from_addr"),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chiffre les colonnes texte sensibles d'une DB existante.",
    )
    parser.add_argument("--client-id", required=True,
                        help="Cabinet ID (filtre multi-mandant).")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None,
                        help="Path SQLite. Override config.paths.db.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if is_encryption_disabled():
        print("✗ FIDUCIAIRE_ENCRYPTION_DISABLED=true → no-op",
              file=sys.stderr)
        return 0

    config = load_config(args.config)
    db_path = args.db if args.db is not None else config.paths.db
    if not db_path.exists():
        print(f"✗ DB introuvable : {db_path}", file=sys.stderr)
        return 2

    conn: sqlite3.Connection = db.connect(db_path)

    # S'assure que la clé est dispo (sinon raise dès la 1ère ligne)
    try:
        ensure_master_key(args.client_id)
    except Exception as exc:
        print(f"✗ clé indisponible pour cabinet={args.client_id}: {exc}",
              file=sys.stderr)
        conn.close()
        return 2

    print(f"MIGRATION COLUMN ENCRYPTION")
    print(f"  cabinet     : {args.client_id}")
    print(f"  db          : {db_path}")
    print(f"  dry_run     : {args.dry_run}")
    print()

    t0 = time.perf_counter()
    total_encrypted = 0
    total_skipped_enc = 0
    total_skipped_null = 0

    for table, cabinet_col, column in TARGETS:
        # Skip si la table n'existe pas (ex. legacy DB sans email_messages)
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            print(f"  ⊘ {table}.{column} → table absente, skip")
            continue
        result = migrate_column_in_place(
            conn, table=table, cabinet_id_column=cabinet_col,
            target_column=column, cabinet_id=args.client_id,
            dry_run=args.dry_run,
        )
        glyph = "✓" if not args.dry_run else "·"
        print(f"  {glyph} {table}.{column}: encrypted={result.rows_encrypted}, "
              f"already={result.rows_skipped_already_encrypted}, "
              f"null/empty={result.rows_skipped_null_or_empty}")
        total_encrypted += result.rows_encrypted
        total_skipped_enc += result.rows_skipped_already_encrypted
        total_skipped_null += result.rows_skipped_null_or_empty

    wall = time.perf_counter() - t0
    print()
    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  total encrypted   : {total_encrypted}")
    print(f"  already encrypted : {total_skipped_enc}")
    print(f"  null/empty        : {total_skipped_null}")
    print(f"  duration          : {wall:.2f}s")
    print(f"─────────────────────────────────────────────────────")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
