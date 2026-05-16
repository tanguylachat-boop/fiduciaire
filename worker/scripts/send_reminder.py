"""CLI : envoie une relance approuvée via SMTP.

Lit la relance en DB (vérifie status='approved' et cabinet_id), appelle
smtp_client.send_reminder(), output JSON pur sur stdout. Logs sur stderr.

Usage :
  python worker/scripts/send_reminder.py \\
    --reminder-id 42 \\
    --cabinet-id gravosig-fiduciaire-01

Output JSON stdout :
  {"ok": true, "reminder_id": 42, "status": "sent", "dry_run": true, "sent_at": "..."}
  {"ok": false, "reminder_id": 42, "status": "failed", "error": "SMTP connection refused"}

Exit code : 0 si OK, 1 si erreur.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import db as _db  # noqa: E402
from fiduciaire_worker.audit_log import init_audit_schema  # noqa: E402
from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker.missing_docs_detector import init_anomalies_schema  # noqa: E402
from fiduciaire_worker.reminder_engine import init_reminders_schema  # noqa: E402
from fiduciaire_worker.smtp_client import ConfigError, _is_dry_run, send_reminder  # noqa: E402

_log = logging.getLogger("fiduciaire.send_reminder_cli")

_OUT_JSON = True  # stdout = JSON pur, jamais de texte libre


def _emit(data: dict) -> None:
    """Écrit le JSON résultat sur stdout. Seule sortie stdout autorisée."""
    print(json.dumps(data, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Envoie une relance approuvée via SMTP.",
    )
    parser.add_argument("--reminder-id", type=int, required=True,
                        help="ID de la relance (table reminders).")
    parser.add_argument("--cabinet-id", required=True,
                        help="Cabinet ID (vérification cross-mandant).")
    parser.add_argument("--db", type=Path, default=None,
                        help="Chemin DB SQLite (sinon lu depuis config.yaml).")
    parser.add_argument("--config", type=Path, default=None,
                        help="Chemin config.yaml cabinet (optionnel).")
    parser.add_argument("--log-level", default="WARNING",
                        help="Niveau de log stderr (défaut WARNING).")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    rid = args.reminder_id
    cabinet_id = args.cabinet_id

    # ── Résolution chemin DB ──────────────────────────────────────────────────
    try:
        config = load_config(args.config)
        db_path = args.db if args.db is not None else config.paths.db
    except Exception as exc:
        _log.warning("load_config failed (%s), using --db or default path", exc)
        db_path = args.db or (REPO_ROOT / "data" / "fiduciaire.sqlite")

    # ── Connexion + init schémas ──────────────────────────────────────────────
    try:
        conn = _db.connect(db_path)
        _db.init_schema(conn)
        init_anomalies_schema(conn)
        init_audit_schema(conn)
        init_reminders_schema(conn)
    except Exception as exc:
        _emit({
            "ok": False,
            "reminder_id": rid,
            "status": "failed",
            "error": f"Impossible d'ouvrir la DB : {exc}",
        })
        return 1

    # ── Vérification pré-envoi : cabinet_id + status ─────────────────────────
    row = conn.execute(
        "SELECT * FROM reminders WHERE id = ? AND cabinet_id = ?",
        (rid, cabinet_id),
    ).fetchone()

    if row is None:
        _emit({
            "ok": False,
            "reminder_id": rid,
            "status": "failed",
            "error": f"Relance {rid} introuvable ou cabinet_id incorrect (cabinet={cabinet_id!r})",
        })
        conn.close()
        return 1

    if row["status"] != "approved":
        _emit({
            "ok": False,
            "reminder_id": rid,
            "status": row["status"],
            "error": f"Status '{row['status']}' — la relance doit être 'approved' avant envoi",
        })
        conn.close()
        return 1

    # ── Envoi via smtp_client ─────────────────────────────────────────────────
    try:
        ok = send_reminder(rid, conn)
    except ConfigError as exc:
        _emit({
            "ok": False,
            "reminder_id": rid,
            "status": "failed",
            "error": str(exc),
        })
        conn.close()
        return 1
    except Exception as exc:
        # Erreur réseau ou autre non gérée par smtp_client (ex: ConnectionRefusedError)
        error_msg = f"{type(exc).__name__}: {exc}"
        _log.error("Unexpected error sending reminder %d: %s", rid, error_msg)
        try:
            conn.execute(
                "UPDATE reminders SET status='failed', error_message=? WHERE id=?",
                (error_msg, rid),
            )
            conn.commit()
        except Exception:
            pass
        _emit({
            "ok": False,
            "reminder_id": rid,
            "status": "failed",
            "error": error_msg,
        })
        conn.close()
        return 1

    # ── Lecture statut final en DB ────────────────────────────────────────────
    updated = conn.execute(
        "SELECT status, sent_at FROM reminders WHERE id = ?", (rid,)
    ).fetchone()
    final_status = updated["status"] if updated else ("sent" if ok else "failed")
    sent_at = updated["sent_at"] if updated else None

    conn.close()

    if ok:
        _emit({
            "ok": True,
            "reminder_id": rid,
            "status": final_status,
            "dry_run": _is_dry_run(),
            "sent_at": sent_at,
        })
        return 0
    else:
        _emit({
            "ok": False,
            "reminder_id": rid,
            "status": final_status,
            "error": "Échec SMTP (voir logs stderr pour détails)",
        })
        return 1


if __name__ == "__main__":
    sys.exit(main())
