"""CLI push des écritures validées vers Bexio v3.

⚠️  Double opt-in obligatoire pour la prod :
   1. `--live` en argument CLI
   2. Variable d'env `BEXIO_PUSH_LIVE=true`

Sans les deux, le script force `dry_run=True`.

Exemples :
  # Dry-run (par défaut, safe) :
  python worker/scripts/bexio_push.py --client-id pilote-jura-01

  # Prod (les 2 conditions doivent être satisfaites) :
  BEXIO_PUSH_LIVE=true python worker/scripts/bexio_push.py \\
    --client-id pilote-jura-01 --live

  # Avec maps account/tax custom :
  python worker/scripts/bexio_push.py --client-id pilote-jura-01 \\
    --account-map config/account-map-jura.json \\
    --tax-map config/tax-map-jura.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.bexio_push import (  # noqa: E402
    BexioPushSummary,
    push_validated_entries,
)
from fiduciaire_worker.config import load_config  # noqa: E402
from fiduciaire_worker.secrets import get_bexio_pat  # noqa: E402

LIVE_ENV_VAR = "BEXIO_PUSH_LIVE"


def _load_map(path: Path | None) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"map file introuvable: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"map file must be a JSON object: {path}")
    return raw


def _print_summary(summary: BexioPushSummary, wall_clock_s: float) -> None:
    print("\n─── BEXIO PUSH SUMMARY ──────────────────────────────")
    print(f"Cabinet          : {summary.cabinet_id}")
    print(f"Mode             : {'DRY-RUN (no HTTP write)' if summary.dry_run else 'LIVE'}")
    print(f"Total scanned    : {summary.total}")
    if summary.pushed:
        print(f"  pushed         : {summary.pushed}")
    if summary.skipped_dry_run:
        print(f"  dry-run preview: {summary.skipped_dry_run}")
    if summary.already_pushed:
        print(f"  already pushed : {summary.already_pushed}")
    if summary.failed:
        print(f"  failed         : {summary.failed}")
    if summary.account_not_mapped:
        print(f"  account map KO : {summary.account_not_mapped}")
    print(f"Duration         : {summary.duration_s:.1f}s "
          f"(wall clock {wall_clock_s:.1f}s)")
    if summary.failed:
        print(f"\n⚠️  Failed entries — détail :")
        for r in summary.results:
            if r.status == "failed":
                print(f"   ✗ entry_id={r.entry_id} http={r.http_status} "
                      f"err={r.error}")
                if r.response_excerpt:
                    excerpt = r.response_excerpt[:200].replace("\n", " ")
                    print(f"     body: {excerpt}...")
    print("─────────────────────────────────────────────────────")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Push validated accounting_entries → Bexio v3 manual_entries.",
    )
    parser.add_argument("--client-id", required=True,
                        help="Cabinet ID multi-mandant (ex. pilote-jura-01).")
    parser.add_argument("--config", type=Path, default=None,
                        help="Path config.yaml (défaut: auto).")
    parser.add_argument("--db", type=Path, default=None,
                        help="Path SQLite. Override config.paths.db.")
    parser.add_argument("--state", default="validated",
                        choices=["validated", "proposed", "rejected"],
                        help="État SQL à pousser (défaut: validated).")
    parser.add_argument("--live", action="store_true",
                        help=(f"Active le mode prod. Requiert AUSSI {LIVE_ENV_VAR}=true."
                              " Sans cela, dry-run forcé."))
    parser.add_argument("--limit", type=int, default=None,
                        help="Max entries à scanner par run.")
    parser.add_argument("--account-map", type=Path, default=None,
                        help="JSON {account_no: bexio_id_int}. Sans cela, "
                             "toutes les entries seront 'account_not_mapped'.")
    parser.add_argument("--tax-map", type=Path, default=None,
                        help="JSON {vat_code: tax_id_int}. Optionnel — sans, "
                             "les entries seront envoyées sans tax_id.")
    parser.add_argument("--base-url", default="https://api.bexio.com",
                        help="Base URL API Bexio (défaut: prod).")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Tentatives max sur 5xx (défaut 3).")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Double opt-in
    env_live = os.getenv(LIVE_ENV_VAR, "").lower() == "true"
    cli_live = bool(args.live)
    dry_run = not (env_live and cli_live)

    config = load_config(args.config)
    config.paths.ensure()

    db_path = args.db if args.db is not None else config.paths.db
    if not db_path.exists():
        print(f"✗ DB introuvable: {db_path}", file=sys.stderr)
        return 2

    conn: sqlite3.Connection = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    try:
        account_map = _load_map(args.account_map)
        tax_map = _load_map(args.tax_map)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"✗ map load error: {exc}", file=sys.stderr)
        conn.close()
        return 2

    # Convert int values from JSON (already int in JSON usually)
    if account_map:
        account_map = {str(k): int(v) for k, v in account_map.items()}
    if tax_map:
        tax_map = {str(k): int(v) for k, v in tax_map.items()}

    try:
        pat = get_bexio_pat()
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        conn.close()
        return 2

    print(f"BEXIO PUSH")
    print(f"  cabinet     : {args.client_id}")
    print(f"  state       : {args.state}")
    print(f"  base_url    : {args.base_url}")
    print(f"  db          : {db_path}")
    print(f"  dry_run     : {dry_run}")
    if not dry_run:
        print(f"  ⚠️  LIVE MODE — écriture réelle vers Bexio activée.")
    else:
        if cli_live and not env_live:
            print(f"  ↳  --live passé mais {LIVE_ENV_VAR}!=true → dry-run forcé.")
        elif env_live and not cli_live:
            print(f"  ↳  {LIVE_ENV_VAR}=true mais --live absent → dry-run forcé.")
    print(f"  account_map : {'yes' if account_map else 'no'}")
    print(f"  tax_map     : {'yes' if tax_map else 'no'}")
    if args.limit:
        print(f"  limit       : {args.limit}")
    print()

    t0 = time.perf_counter()
    try:
        summary = push_validated_entries(
            cabinet_id=args.client_id,
            pat=pat,
            conn=conn,
            base_url=args.base_url,
            state_filter=args.state,
            dry_run=dry_run,
            limit=args.limit,
            max_retries=args.max_retries,
            account_no_to_bexio_id=account_map,
            tax_code_to_bexio_id=tax_map,
        )
    except KeyboardInterrupt:
        wall = time.perf_counter() - t0
        print(f"\n⚠️  interrompu après {wall:.1f}s", file=sys.stderr)
        return 130
    finally:
        conn.close()

    wall = time.perf_counter() - t0
    _print_summary(summary, wall)

    if summary.failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
