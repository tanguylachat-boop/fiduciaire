"""CLI polling IMAP cabinet → pipeline ingestion.

Use case :
  - cron / launchd toutes les 5 min sur Mac Mini cabinet
  - debug manuel avant prod (--dry-run)
  - reset/replay si recovery (--reset-state)

Exemples :
  python worker/scripts/imap_fetch.py --client-id pilote-jura-01
  python worker/scripts/imap_fetch.py --client-id pilote-jura-01 --dry-run
  python worker/scripts/imap_fetch.py --client-id pilote-jura-01 --limit 5

Voir docs/specs/imap-fetch.md §USER ACTION MAP pour le contexte.
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

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker.imap_fetch import (  # noqa: E402
    ImapFetchFilters,
    ImapFetchSummary,
    fetch_emails,
)
from fiduciaire_worker.imap_client import ImapAuthError, ImapNetworkError  # noqa: E402
from fiduciaire_worker.process_lock import (  # noqa: E402
    LockAcquireError,
    ProcessLock,
)
from fiduciaire_worker.secrets import get_imap_credentials  # noqa: E402

_DEFAULT_LOCK_DIR = REPO_ROOT / "data" / "locks"


def _print_summary(summary: ImapFetchSummary, wall_clock_s: float) -> None:
    print("\n─── IMAP FETCH SUMMARY ──────────────────────────────")
    print(f"Cabinet          : {summary.cabinet_id}")
    print(f"Folder           : {summary.folder}")
    print(f"UIDVALIDITY      : {summary.uidvalidity}")
    print(f"Dry-run          : {'YES (no DB writes)' if summary.dry_run else 'no'}")
    print(f"New messages     : {summary.new_messages}")
    if summary.duplicates:
        print(f"  duplicates     : {summary.duplicates} (Message-ID match)")
    if summary.filtered_sender:
        print(f"  filtered sender: {summary.filtered_sender}")
    if summary.pgp_skipped:
        print(f"  PGP-flagged    : {summary.pgp_skipped}")
    if summary.smime_skipped:
        print(f"  SMIME-flagged  : {summary.smime_skipped}")
    if summary.no_attachment:
        print(f"  no-attachment  : {summary.no_attachment}")
    print(f"Attachments      : {summary.attachments_total}")
    if summary.attachments_processed:
        print(f"  → processed    : {summary.attachments_processed}")
    if summary.attachments_unsupported:
        print(f"  → unsupported  : {summary.attachments_unsupported}")
    if summary.attachments_failed:
        print(f"  → failed       : {summary.attachments_failed}")
    if summary.attachments_oversized:
        print(f"  → oversized    : {summary.attachments_oversized}")
    if summary.attachments_empty:
        print(f"  → empty        : {summary.attachments_empty}")
    print(f"Last UID seen    : {summary.last_uid_seen}")
    print(f"Pipeline duration: {summary.duration_s:.1f}s "
          f"(wall clock {wall_clock_s:.1f}s)")
    if summary.errors:
        print(f"\n⚠️  Errors:")
        for err in summary.errors:
            print(f"   - {err}")
    if summary.attachments_failed:
        print(f"\n⚠️  Failed attachments — détail :")
        for outcome in summary.by_message:
            if outcome.attachments_failed > 0:
                print(f"   ✗ uid={outcome.uid} msg-id={outcome.message_id} "
                      f"from={outcome.from_addr} err={outcome.error or 'see DB'}")
    print("─────────────────────────────────────────────────────")


def _reset_state(conn: sqlite3.Connection, cabinet_id: str, folder: str) -> None:
    cur = conn.execute(
        "DELETE FROM email_fetch_state WHERE cabinet_id=? AND folder=?",
        (cabinet_id, folder),
    )
    print(f"✗ email_fetch_state cleared for cabinet={cabinet_id} "
          f"folder={folder} (rows deleted: {cur.rowcount})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Poll IMAP cabinet + route attachments via pipeline.",
    )
    parser.add_argument("--client-id", required=True,
                        help="Cabinet ID (ex. pilote-jura-01).")
    parser.add_argument("--folder", default="INBOX",
                        help="Dossier IMAP (défaut: INBOX).")
    parser.add_argument("--config", type=Path, default=None,
                        help="Path config.yaml (défaut: auto-detect).")
    parser.add_argument("--db", type=Path, default=None,
                        help="Path SQLite. Override config.paths.db.")
    parser.add_argument("--host", type=str, default=None,
                        help="IMAP host (override Keychain/.env).")
    parser.add_argument("--port", type=int, default=993,
                        help="IMAP port TLS (défaut 993, 143 refusé).")
    parser.add_argument("--user", type=str, default=None,
                        help="IMAP user (override Keychain/.env).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Lecture seule : pas de DB write, pas de pipeline, "
                             "pas de mark_seen.")
    parser.add_argument("--mark-seen", action="store_true",
                        help="Marque les messages traités comme \\Seen.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max emails à traiter en 1 run (défaut: tous).")
    parser.add_argument("--reset-state", action="store_true",
                        help="Efface email_fetch_state pour ce cabinet/folder "
                             "avant fetch (full rescan + dedup Message-ID).")
    parser.add_argument("--max-attachment-mb", type=int, default=50,
                        help="Taille max attachment en MB (défaut 50).")
    parser.add_argument("--sender-allow", action="append", default=None,
                        help="Liste blanche d'expéditeurs (répétable). "
                             "Format: email exact ou '@domain.com' wildcard.")
    parser.add_argument("--force", action="store_true",
                        help="Force la reprise même si un lock orphelin existe.")
    parser.add_argument("--lock-dir", type=Path, default=_DEFAULT_LOCK_DIR,
                        help=f"Dossier des locks (défaut: {_DEFAULT_LOCK_DIR}).")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config(args.config)
    config.paths.ensure()

    db_path = args.db if args.db is not None else config.paths.db
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn: sqlite3.Connection = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    if args.reset_state:
        _reset_state(conn, args.client_id, args.folder)

    try:
        creds = get_imap_credentials(
            cabinet_id=args.client_id,
            host=args.host,
            port=args.port,
            user=args.user,
        )
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    print(f"IMAP fetch")
    print(f"  cabinet     : {args.client_id}")
    print(f"  host        : {creds.host}:{creds.port}")
    print(f"  user        : {creds.user}")
    print(f"  folder      : {args.folder}")
    print(f"  db          : {db_path}")
    print(f"  dry_run     : {args.dry_run}")
    print(f"  mark_seen   : {args.mark_seen}")
    if args.limit:
        print(f"  limit       : {args.limit}")
    if args.sender_allow:
        print(f"  sender_allow: {args.sender_allow}")
    print()

    filters = (
        ImapFetchFilters(sender_allowlist=args.sender_allow)
        if args.sender_allow else ImapFetchFilters()
    )

    lock_path = args.lock_dir / f"imap-fetch-{args.client_id}.lock"
    lock = ProcessLock(lock_path)
    try:
        lock.acquire(force=args.force)
    except LockAcquireError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        conn.close()
        return 3

    t0 = time.perf_counter()
    try:
        summary = fetch_emails(
            cabinet_id=args.client_id,
            creds=creds,
            conn=conn,
            config=config,
            folder=args.folder,
            limit=args.limit,
            dry_run=args.dry_run,
            mark_seen=args.mark_seen,
            filters=filters,
            max_attachment_size_bytes=args.max_attachment_mb * 1024 * 1024,
        )
    except ImapAuthError as exc:
        print(f"\n✗ Authentification IMAP refusée : {exc}", file=sys.stderr)
        print("  → vérifier Keychain ou IMAP_PASSWORD_<CABINET> dans .env",
              file=sys.stderr)
        return 2
    except ImapNetworkError as exc:
        print(f"\n✗ Connexion IMAP épuisée : {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        wall = time.perf_counter() - t0
        print(f"\n⚠️  interrompu après {wall:.1f}s", file=sys.stderr)
        return 130
    finally:
        lock.release()
        conn.close()

    wall = time.perf_counter() - t0
    _print_summary(summary, wall)

    return 0


if __name__ == "__main__":
    sys.exit(main())
