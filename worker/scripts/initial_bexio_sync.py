"""Initial Bexio sync — pull plan comptable + 100 entries + contacts d'un mandant.

Lecture seule. Aucune écriture vers Bexio. PAT chargé depuis Keychain macOS.

Usage :
  python worker/scripts/initial_bexio_sync.py [--client-id cabinet-pilote-01]

Pré-requis :
  python -c "import keyring; keyring.set_password('fiduciaire', 'bexio-pat-pilote-dev', '<PAT>')"
  Le PAT s'obtient dans Bexio : Profil → Personal Access Tokens → Generate.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

import keyring  # noqa: E402
from fiduciaire_worker import accounting_schema, bexio_client, db, vendor_account_history  # noqa: E402

KEYRING_SERVICE = "fiduciaire"
KEYRING_USERNAME_DEFAULT = "bexio-pat-pilote-dev"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--client-id", default="cabinet-pilote-01")
    p.add_argument(
        "--db",
        default=str(REPO_ROOT / "data" / "fiduciaire.sqlite"),
        help="Chemin de la base SQLite locale",
    )
    p.add_argument(
        "--keyring-username",
        default=KEYRING_USERNAME_DEFAULT,
        help="Nom d'usager Keychain (défaut: bexio-pat-pilote-dev)",
    )
    p.add_argument(
        "--rebuild-vendor-history",
        action="store_true",
        default=True,
        help="Rebuild vendor_account_history depuis le cache Bexio (défaut: true)",
    )
    args = p.parse_args()

    pat = keyring.get_password(KEYRING_SERVICE, args.keyring_username)
    if not pat:
        print(
            f"ERREUR: PAT introuvable dans le Keychain ({KEYRING_SERVICE}/{args.keyring_username}).\n"
            f"Pour l'ajouter : python -c \"import keyring; "
            f"keyring.set_password('{KEYRING_SERVICE}', '{args.keyring_username}', '<PAT>')\"",
            file=sys.stderr,
        )
        return 2

    db_path = Path(args.db)
    print(f"DB: {db_path}")
    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    print(f"Connexion Bexio (read-only) pour mandant {args.client_id}...")
    client = bexio_client.BexioReadOnlyClient(
        client_id=args.client_id,
        pat=pat,
    )

    try:
        print("→ Sync plan comptable + contacts + 100 dernières écritures...")
        report = client.sync_to_local_cache(conn)
        print(
            f"   ✓ {report.accounts_count} comptes | "
            f"{report.contacts_count} contacts | "
            f"{report.entries_count} écritures"
        )

        if args.rebuild_vendor_history:
            print("→ Rebuild vendor_account_history depuis le cache...")
            history = vendor_account_history.build_history_from_bexio_cache(
                conn, args.client_id
            )
            print(f"   ✓ {len(history)} fournisseurs analysés")
            top = sorted(
                history.values(), key=lambda v: v.occurrences, reverse=True
            )[:5]
            for v in top:
                print(
                    f"     · {v.vendor_name[:40]:<40} → {v.recommended_account} "
                    f"({v.occurrences} occurrences, conf {v.confidence:.2f})"
                )

        print("\nSync terminée. Cache local prêt pour `entry_proposer`.")
        return 0
    except Exception as e:
        # PAT jamais affiché en clair — bexio_client.py garantit pas de leak.
        print(f"ERREUR sync: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
