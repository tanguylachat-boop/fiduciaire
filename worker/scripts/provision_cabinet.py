"""CLI : provisionne un cabinet (DB + folders + config + seed + audit).

Usage :
  python worker/scripts/provision_cabinet.py \\
    --cabinet-id gravosig-fiduciaire-01 \\
    --cabinet-name "Gravosig Fiduciaire SA" \\
    --ville Delémont --canton JU --lang fr \\
    --mandants "mandant-pme-01,mandant-pme-02,mandant-pme-03" \\
    --logiciel winbiz

  # Re-run sur cabinet existant :
  ... --force

⚠️  Idempotent : sans --force, échoue proprement si le cabinet existe déjà.
⚠️  Audit : émet un event 'cabinet_provisioned' (ou _re_provisioned si force).
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
from fiduciaire_worker.cabinet_provisioning import (  # noqa: E402
    CabinetAlreadyExistsError,
    provision_cabinet,
)
from fiduciaire_worker.config import load_config  # noqa: E402


def _parse_mandants(arg: str) -> list[str]:
    return [m.strip() for m in arg.split(",") if m.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Provisionne un cabinet complet en 1 commande.",
    )
    parser.add_argument("--cabinet-id", required=True,
                        help="Slug [a-z0-9][a-z0-9-]{1,63}")
    parser.add_argument("--cabinet-name", required=True)
    parser.add_argument("--ville", default=None)
    parser.add_argument("--canton", default=None)
    parser.add_argument("--lang", choices=["fr", "de", "it"], default="fr")
    parser.add_argument("--mandants", default="",
                        help="Mandant IDs séparés par virgule (vide accepté).")
    parser.add_argument("--logiciel",
                        choices=["bexio", "winbiz", "cresus", "abacus"],
                        required=True)
    parser.add_argument("--force", action="store_true",
                        help="Réécrit cabinet/mandants/config si déjà présent.")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--clients-root", type=Path, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config(args.config)
    db_path = args.db if args.db is not None else config.paths.db
    clients_root = (
        args.clients_root if args.clients_root is not None
        else config.paths.clients_root
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    clients_root.mkdir(parents=True, exist_ok=True)

    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    audit_log.init_audit_schema(conn)

    mandants = _parse_mandants(args.mandants)
    user_id = os.environ.get("USER") or "system"

    print("PROVISION CABINET")
    print(f"  cabinet-id   : {args.cabinet_id}")
    print(f"  cabinet-name : {args.cabinet_name}")
    print(f"  ville/canton : {args.ville or '-'} / {args.canton or '-'}")
    print(f"  lang         : {args.lang}")
    print(f"  logiciel     : {args.logiciel}")
    print(f"  mandants     : {mandants or '(aucun)'}")
    print(f"  clients-root : {clients_root}")
    print(f"  db           : {db_path}")
    print(f"  force        : {args.force}")
    print(f"  user_id      : {user_id}")
    print()

    t0 = time.perf_counter()
    try:
        result = provision_cabinet(
            cabinet_id=args.cabinet_id,
            cabinet_name=args.cabinet_name,
            ville=args.ville,
            canton=args.canton,
            lang=args.lang,
            mandants=mandants,
            logiciel=args.logiciel,
            clients_root=clients_root,
            conn=conn,
            force=args.force,
            user_id=user_id,
            db_path=db_path,
        )
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        conn.close()
        return 2
    except CabinetAlreadyExistsError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        conn.close()
        return 4
    finally:
        pass

    wall = time.perf_counter() - t0
    print(f"─── SUMMARY ─────────────────────────────────────────")
    print(f"  base dir         : {result.base_dir}")
    print(f"  config.yaml      : {result.config_path}")
    print(f"  mandants count   : {result.mandants_count}")
    print(f"  accounts seeded  : {result.accounts_seeded}")
    print(f"  re-provisioned   : {result.re_provisioned}")
    print(f"  duration         : {wall:.2f}s")
    print(f"─────────────────────────────────────────────────────")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
