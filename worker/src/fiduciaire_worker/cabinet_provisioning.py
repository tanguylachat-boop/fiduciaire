"""Provisioning idempotent d'un cabinet — Sprint 2 Session 12.

Crée en 1 appel :
- L'arborescence `data/clients/<cabinet-id>/{inbox,archive,needs-review,validated,exports}`
- `config.yaml` cabinet-specific depuis un template
- Tables `cabinets`, `mandants`, `chart_of_accounts` (CREATE IF NOT EXISTS)
- Row cabinet + mandants
- Plan comptable suisse standard seed (28 comptes KMU)
- Audit event `cabinet_provisioned` (ou `_re_provisioned` si --force)

Cf decision doc `docs/decisions/2026-05-16-cabinet-provisioning.md`.

Multi-mandant first-class : `chart_of_accounts` indexé par `client_id`,
tests cross-mandant explicites.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import audit_log as _audit
from .plan_comptable_seed import SEED_PLAN_COMPTABLE_SUISSE

_log = logging.getLogger("fiduciaire.cabinet_provisioning")

ALLOWED_LANGS = {"fr", "de", "it"}
ALLOWED_LOGICIELS = {"bexio", "winbiz", "cresus", "abacus"}
CABINET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

SUB_DIRS = ("inbox", "archive", "needs-review", "validated", "exports")

PROVISIONING_SCHEMA = """
CREATE TABLE IF NOT EXISTS cabinets (
    cabinet_id TEXT PRIMARY KEY,
    cabinet_name TEXT NOT NULL,
    ville TEXT,
    canton TEXT,
    lang TEXT NOT NULL DEFAULT 'fr',
    logiciel TEXT NOT NULL,
    config_path TEXT NOT NULL,
    provisioned_at TEXT NOT NULL DEFAULT (datetime('now')),
    provisioned_by TEXT
);

CREATE TABLE IF NOT EXISTS mandants (
    cabinet_id TEXT NOT NULL REFERENCES cabinets(cabinet_id),
    mandant_id TEXT NOT NULL,
    mandant_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (cabinet_id, mandant_id)
);

CREATE TABLE IF NOT EXISTS chart_of_accounts (
    client_id TEXT NOT NULL,
    account_no TEXT NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (client_id, account_no)
);

CREATE INDEX IF NOT EXISTS idx_coa_client_type
  ON chart_of_accounts(client_id, account_type);
"""


class CabinetAlreadyExistsError(Exception):
    """Cabinet déjà en DB ; utiliser force=True pour réécrire."""


@dataclass
class ProvisioningResult:
    cabinet_id: str
    created: bool
    base_dir: Path
    config_path: Path
    accounts_seeded: int
    mandants_count: int
    re_provisioned: bool = False


# --- Schema -----------------------------------------------------------------


def init_provisioning_schema(conn: sqlite3.Connection) -> None:
    """Idempotent. Crée cabinets/mandants/chart_of_accounts si absents."""
    conn.executescript(PROVISIONING_SCHEMA)


# --- Validation -------------------------------------------------------------


def _validate_inputs(
    cabinet_id: str, lang: str, logiciel: str,
) -> None:
    if not CABINET_ID_RE.match(cabinet_id):
        raise ValueError(
            f"cabinet_id invalide : '{cabinet_id}'. "
            "Slug attendu : [a-z0-9][a-z0-9-]{1,63}",
        )
    if lang not in ALLOWED_LANGS:
        raise ValueError(
            f"lang invalide : '{lang}'. "
            f"Choix : {sorted(ALLOWED_LANGS)}",
        )
    if logiciel not in ALLOWED_LOGICIELS:
        raise ValueError(
            f"logiciel invalide : '{logiciel}'. "
            f"Choix : {sorted(ALLOWED_LOGICIELS)}",
        )


# --- Config YAML template --------------------------------------------------


def _render_config_yaml(
    *,
    cabinet_id: str,
    cabinet_name: str,
    ville: str | None,
    canton: str | None,
    lang: str,
    logiciel: str,
    mandants: list[str],
    base_dir: Path,
    db_path: Path,
) -> str:
    """Sérialise un config.yaml propre. F-string vs yaml.dump : on garde
    les commentaires + ordre prévisible. Pas de secret embarqué."""
    mandants_block = "\n".join(f"  - {m}" for m in mandants)
    ocr_langs = {
        "fr": '["fra", "deu"]',
        "de": '["deu", "fra"]',
        "it": '["ita", "deu", "fra"]',
    }[lang]
    return f"""# Cabinet {cabinet_name} — config provisionnée
# Généré par worker/scripts/provision_cabinet.py (Sprint 2 Session 12)
# Cf docs/decisions/2026-05-16-cabinet-provisioning.md

cabinet:
  name: "{cabinet_name}"
  slug: "{cabinet_id}"
  ville: "{ville or ''}"
  canton: "{canton or ''}"
  lang: "{lang}"
  logiciel: "{logiciel}"
  langues_ocr: {ocr_langs}

mandants:
{mandants_block}

paths:
  inbox: "{base_dir / 'inbox'}"
  needs_review: "{base_dir / 'needs-review'}"
  archive: "{base_dir / 'archive'}"
  clients_root: "{base_dir.parent}"
  db: "{db_path}"

llm:
  endpoint: "http://localhost:11434"
  env: "prod"
  models:
    prod:
      primary: "llama3.3:70b-instruct-q4_K_M"
      fallback: "qwen2.5:32b-instruct-q4_K_M"
      vision: "qwen2.5vl:7b-q4_K_M"
  prompt_file: "worker/prompts/classify_v2_fewshot.txt"
  timeout_s: 60
  temperature: 0.0
  num_predict: 512
  num_ctx: 4096

ocr:
  engine: "tesseract"
  dpi: 300

confidence_thresholds:
  type: 0.85
  client: 0.80
  date: 0.75
  montant: 0.75

logging:
  level: "INFO"
  file: "{base_dir / 'worker.log'}"
"""


# --- Seed plan comptable ---------------------------------------------------


def _seed_chart_of_accounts(
    conn: sqlite3.Connection, cabinet_id: str,
) -> int:
    """INSERT OR IGNORE des comptes seed. Retourne le nombre inséré.

    Idempotent : compte déjà présent (même account_no) ⇒ ignoré.
    """
    count_before = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE client_id=?",
        (cabinet_id,),
    ).fetchone()[0]
    for account in SEED_PLAN_COMPTABLE_SUISSE:
        conn.execute(
            "INSERT OR IGNORE INTO chart_of_accounts "
            "(client_id, account_no, name, account_type, source) "
            "VALUES (?, ?, ?, ?, 'seed')",
            (cabinet_id, account.account_no, account.name,
             account.account_type),
        )
    count_after = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE client_id=?",
        (cabinet_id,),
    ).fetchone()[0]
    # Pour un cabinet neuf, seeded == len(SEED). Pour un re-run, 0 ajout.
    return count_after - count_before


# --- Public API ------------------------------------------------------------


def provision_cabinet(
    *,
    cabinet_id: str,
    cabinet_name: str,
    ville: str | None,
    canton: str | None,
    lang: str,
    mandants: list[str],
    logiciel: str,
    clients_root: Path,
    conn: sqlite3.Connection,
    force: bool = False,
    user_id: str | None = None,
    db_path: Path | None = None,
) -> ProvisioningResult:
    """Provisionne un cabinet complet (DB + folders + config + seed + audit).

    Args:
        cabinet_id: slug `[a-z0-9-]{2,64}`. Servira de client_id partout.
        cabinet_name: nom long affiché dans header/reports.
        ville, canton: optionnels (None = vides en YAML).
        lang: 'fr' | 'de' | 'it'.
        mandants: liste de mandant_id (slugs). Peut être vide.
        logiciel: 'bexio' | 'winbiz' | 'cresus' | 'abacus'.
        clients_root: dossier racine `data/clients/`.
        conn: connexion SQLite (schémas existants déjà initialisés).
        force: si True, réécrit cabinet + mandants + config.yaml.
        user_id: propagé à l'audit event.
        db_path: chemin DB pour le YAML (défaut : déduit du fichier conn).

    Raises:
        ValueError: cabinet_id slug / lang / logiciel invalide.
        CabinetAlreadyExistsError: cabinet existe, force=False.
    """
    _validate_inputs(cabinet_id, lang, logiciel)
    init_provisioning_schema(conn)
    _audit.init_audit_schema(conn)

    existing = conn.execute(
        "SELECT cabinet_id FROM cabinets WHERE cabinet_id=?",
        (cabinet_id,),
    ).fetchone()
    re_provisioned = False
    if existing is not None:
        if not force:
            raise CabinetAlreadyExistsError(
                f"Cabinet '{cabinet_id}' existe déjà. "
                "Utiliser force=True pour réécrire.",
            )
        re_provisioned = True

    # --- Folders ---
    base_dir = (clients_root / cabinet_id).resolve()
    for sub in SUB_DIRS:
        (base_dir / sub).mkdir(parents=True, exist_ok=True)

    # --- Config YAML ---
    if db_path is None:
        # On utilise la propriété sqlite3.Connection.execute("PRAGMA database_list")
        # pour récupérer le path du fichier DB.
        row = conn.execute("PRAGMA database_list").fetchone()
        db_path = Path(row["file"]) if row and row["file"] else base_dir / "fiduciaire.sqlite"
    config_path = base_dir / "config.yaml"
    yaml_text = _render_config_yaml(
        cabinet_id=cabinet_id,
        cabinet_name=cabinet_name,
        ville=ville,
        canton=canton,
        lang=lang,
        logiciel=logiciel,
        mandants=mandants,
        base_dir=base_dir,
        db_path=Path(db_path),
    )
    config_path.write_text(yaml_text, encoding="utf-8")

    # --- Cabinet row ---
    conn.execute(
        "INSERT OR REPLACE INTO cabinets "
        "(cabinet_id, cabinet_name, ville, canton, lang, logiciel, "
        " config_path, provisioned_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (cabinet_id, cabinet_name, ville, canton, lang, logiciel,
         str(config_path), user_id),
    )

    # --- Mandants ---
    if force:
        conn.execute(
            "DELETE FROM mandants WHERE cabinet_id=?", (cabinet_id,),
        )
    for m in mandants:
        conn.execute(
            "INSERT OR IGNORE INTO mandants (cabinet_id, mandant_id) "
            "VALUES (?, ?)",
            (cabinet_id, m),
        )

    # --- Plan comptable seed ---
    accounts_seeded = _seed_chart_of_accounts(conn, cabinet_id)

    # --- Audit log ---
    action = "cabinet_re_provisioned" if re_provisioned else "cabinet_provisioned"
    _audit.log_audit_event(
        conn,
        cabinet_id=cabinet_id,
        entity_type="cabinet",
        entity_id=cabinet_id,
        action=action,
        user_id=user_id,
        after={
            "cabinet_name": cabinet_name,
            "ville": ville or "",
            "canton": canton or "",
            "lang": lang,
            "logiciel": logiciel,
            "mandants_count": len(mandants),
            "accounts_seeded": accounts_seeded,
        },
    )

    _log.info(
        "cabinet provisioned id=%s name=%s logiciel=%s mandants=%d "
        "accounts_seeded=%d force=%s",
        cabinet_id, cabinet_name, logiciel, len(mandants),
        accounts_seeded, force,
    )

    return ProvisioningResult(
        cabinet_id=cabinet_id,
        created=True,
        base_dir=base_dir,
        config_path=config_path,
        accounts_seeded=accounts_seeded,
        mandants_count=len(mandants),
        re_provisioned=re_provisioned,
    )
