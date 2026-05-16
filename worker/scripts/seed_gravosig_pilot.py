"""Seed pilote Gravosig — Sprint 2 Session 12.

Pré-remplit le cabinet `gravosig-fiduciaire-01` (Winbiz, Delémont JU)
+ 3 mandants placeholder Bexio. À lancer avant l'install physique chez
la femme Gravosig (semaine du 19 mai 2026).

Sur place, Tanguy renommera les mandants avec les vrais noms :
  python worker/scripts/provision_cabinet.py --force \\
    --cabinet-id gravosig-fiduciaire-01 \\
    --mandants "<noms-réels>" ...
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, audit_log, db  # noqa: E402
from fiduciaire_worker.cabinet_provisioning import (  # noqa: E402
    CabinetAlreadyExistsError,
    provision_cabinet,
)
from fiduciaire_worker.config import load_config  # noqa: E402

GRAVOSIG_CABINET_ID = "gravosig-fiduciaire-01"
GRAVOSIG_CABINET_NAME = "Gravosig Fiduciaire"
GRAVOSIG_VILLE = "Delémont"
GRAVOSIG_CANTON = "JU"
GRAVOSIG_LANG = "fr"
GRAVOSIG_LOGICIEL = "winbiz"
GRAVOSIG_MANDANTS = [
    "mandant-pme-01",
    "mandant-pme-02",
    "mandant-pme-03",
]


INSTALL_CHECKLIST = """
─── CHECKLIST INSTALL GRAVOSIG (à dérouler sur place) ───
[ ] 1. Mac Mini M4 Pro branché, MAJ macOS faite
[ ] 2. Ollama installé + modèles llama3.3:70b + qwen2.5vl:7b pullés
[ ] 3. .env créé à la racine avec :
        BEXIO_PAT=<token PAT du cabinet>
        IMAP_HOST=<serveur>  /  IMAP_USER=<user>  /  IMAP_PASS=<password>
[ ] 4. PAT Bexio stockés dans Keychain (1 par mandant Bexio) :
        keyring set fiduciaire-ai bexio-pat-<mandant-réel>
[ ] 5. Renommer les mandants placeholder :
        python worker/scripts/provision_cabinet.py --force \\
          --cabinet-id gravosig-fiduciaire-01 \\
          --cabinet-name "Gravosig Fiduciaire" \\
          --ville Delémont --canton JU --lang fr --logiciel winbiz \\
          --mandants "<m1>,<m2>,<m3>"
[ ] 6. Import historique Bexio par mandant (12 mois) :
        python worker/scripts/import_bexio_history.py \\
          --cabinet-id gravosig-fiduciaire-01 \\
          --mandant-id <m1> --months 12
[ ] 7. Smoke test : déposer 1 PDF dans data/clients/<id>/inbox,
       vérifier qu'il arrive dans /entries
[ ] 8. Smoke test export Crésus + rapport mensuel PDF
[ ] 9. Imprimer docs/user-guide.pdf et le laisser sur le bureau
[ ] 10. Backup initial : python worker/scripts/backup_now.py
─────────────────────────────────────────────────────
"""


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config()
    db_path = config.paths.db
    clients_root = config.paths.clients_root

    db_path.parent.mkdir(parents=True, exist_ok=True)
    clients_root.mkdir(parents=True, exist_ok=True)

    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    audit_log.init_audit_schema(conn)

    print("SEED GRAVOSIG PILOT")
    print(f"  cabinet-id  : {GRAVOSIG_CABINET_ID}")
    print(f"  cabinet     : {GRAVOSIG_CABINET_NAME}")
    print(f"  lieu        : {GRAVOSIG_VILLE} ({GRAVOSIG_CANTON})")
    print(f"  logiciel    : {GRAVOSIG_LOGICIEL}")
    print(f"  mandants    : {GRAVOSIG_MANDANTS}")
    print(f"  db          : {db_path}")
    print(f"  clients-root: {clients_root}")
    print()

    user_id = os.environ.get("USER") or "system"
    try:
        result = provision_cabinet(
            cabinet_id=GRAVOSIG_CABINET_ID,
            cabinet_name=GRAVOSIG_CABINET_NAME,
            ville=GRAVOSIG_VILLE,
            canton=GRAVOSIG_CANTON,
            lang=GRAVOSIG_LANG,
            mandants=GRAVOSIG_MANDANTS,
            logiciel=GRAVOSIG_LOGICIEL,
            clients_root=clients_root,
            conn=conn,
            user_id=user_id,
            db_path=db_path,
        )
    except CabinetAlreadyExistsError as exc:
        print(f"✗ {exc}")
        print()
        print("Le cabinet est déjà provisionné. Si tu veux reset :")
        print(f"  python worker/scripts/provision_cabinet.py --force \\")
        print(f"    --cabinet-id {GRAVOSIG_CABINET_ID} \\")
        print(f"    --cabinet-name \"{GRAVOSIG_CABINET_NAME}\" \\")
        print(f"    --ville {GRAVOSIG_VILLE} --canton {GRAVOSIG_CANTON} "
              f"--lang fr --logiciel winbiz \\")
        print(f"    --mandants \"{','.join(GRAVOSIG_MANDANTS)}\"")
        conn.close()
        return 4

    print(f"─── RÉSULTAT ────────────────────────────────────────")
    print(f"  base dir        : {result.base_dir}")
    print(f"  config.yaml     : {result.config_path}")
    print(f"  mandants count  : {result.mandants_count}")
    print(f"  accounts seeded : {result.accounts_seeded}")
    print(f"─────────────────────────────────────────────────────")
    print(INSTALL_CHECKLIST)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
