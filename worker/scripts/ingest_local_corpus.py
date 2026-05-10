"""Ingest un dossier local (PDFs/PNGs) via le pipeline complet → DB SQLite.

Use case principal : populer `data/fiduciaire.sqlite` avec les vraies
métadonnées OCR + classification avant de lancer `entry_bench.py`.

Le bench RunPod 2026-05-10 (Llama 70B vs Mistral Small 3) a été
inconclusif parce que `seed_db_from_bench.py` insère les docs sans
texte OCR ni champ `fournisseur` dans `classification_json`. Ce script
remplace `seed_db_from_bench.py` pour le bench réel : il appelle
`pipeline.process_document` sur chaque fichier, ce qui aboutit à des
documents valides utilisables par `entry_proposer`.

Usage :
  python worker/scripts/ingest_local_corpus.py \
    --dir data/samples \
    --client-id pilote-jura-01 \
    --reset-db

Voir docs/specs/ingest-local-corpus.md pour le contexte complet.
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
from fiduciaire_worker.ingest_local import (  # noqa: E402
    IngestSummary,
    ingest_corpus,
    iter_supported_files,
)
from fiduciaire_worker.pipeline import PipelineOutcome  # noqa: E402

_STATUS_GLYPH = {
    "routed": "✓",
    "needs_review": "?",
    "failed": "✗",
    "duplicate": "=",
}


def _print_progress(idx: int, total: int, path: Path, outcome: PipelineOutcome) -> None:
    glyph = _STATUS_GLYPH.get(outcome.status, "·")
    reasons = (" | " + ",".join(outcome.review_reasons)) if outcome.review_reasons else ""
    print(
        f"  [{idx:>3}/{total}] {glyph} {path.name:<45} "
        f"status={outcome.status:<13} dur={outcome.duration_s:5.1f}s{reasons}",
        flush=True,
    )


def _print_summary(summary: IngestSummary, db_path: Path, client_id: str | None,
                   wall_clock_s: float) -> None:
    print("\n─── SUMMARY ──────────────────────────────────────────")
    print(f"Total            : {summary.total}")
    print(f"  routed         : {summary.routed}")
    print(f"  needs_review   : {summary.needs_review}")
    print(f"  failed         : {summary.failed}")
    print(f"  duplicates     : {summary.duplicates}")
    if summary.median_duration_s is not None:
        print(f"Median duration  : {summary.median_duration_s:.1f}s")
    print(f"Total pipeline   : {summary.total_duration_s:.1f}s "
          f"(wall clock {wall_clock_s:.1f}s)")
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"DB               : {db_path} ({size_mb:.1f} MB)")
    if client_id:
        print(f"Client cible     : {client_id} (non persisté sur documents en Sprint 0a)")
    if summary.failed > 0:
        print("\n⚠️  des erreurs sont survenues — détail :")
        for rec in summary.by_file:
            if rec["status"] == "failed":
                err = rec.get("error") or ",".join(rec.get("reasons") or [])
                print(f"   ✗ {rec['filename']:<45} {err}")
    print("─────────────────────────────────────────────────────")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingère un dossier local via le pipeline complet "
                    "(prepare → ocr → classify → route|review).",
    )
    parser.add_argument(
        "--dir", type=Path, default=REPO_ROOT / "data" / "samples",
        help="Dossier source (défaut: data/samples)",
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="Path config.yaml (défaut: ./config.yaml ou config.example.yaml)",
    )
    parser.add_argument(
        "--db", type=Path, default=None,
        help="Path SQLite. Override config.paths.db si fourni.",
    )
    parser.add_argument(
        "--client-id", type=str, default=None,
        help="Client cible (loggé dans summary, pas persisté en Sprint 0a).",
    )
    parser.add_argument(
        "--reset-db", action="store_true",
        help="Supprime la DB cible avant l'ingest (idempotent dev).",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not args.dir.exists() or not args.dir.is_dir():
        print(f"✗ --dir introuvable ou n'est pas un dossier: {args.dir}",
              file=sys.stderr)
        return 2

    files = iter_supported_files(args.dir)
    if not files:
        print(f"✗ aucun fichier supporté dans {args.dir} "
              f"(extensions: {', '.join(sorted(_accepted()))}).",
              file=sys.stderr)
        return 2

    config = load_config(args.config)
    config.paths.ensure()

    db_path = args.db if args.db is not None else config.paths.db

    if args.reset_db and db_path.exists():
        db_path.unlink()
        print(f"✗ {db_path} supprimée (--reset-db)")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    print(f"INGEST corpus")
    print(f"  dir        : {args.dir}")
    print(f"  config     : {args.config or '(auto)'}")
    print(f"  db         : {db_path}")
    print(f"  client_id  : {args.client_id or '(none)'}")
    print(f"  files      : {len(files)}")
    print()

    t0 = time.perf_counter()
    try:
        summary = ingest_corpus(args.dir, config, conn, on_progress=_print_progress)
    except KeyboardInterrupt:
        wall = time.perf_counter() - t0
        print(f"\n⚠️  interrompu après {wall:.1f}s", file=sys.stderr)
        return 130
    finally:
        conn.close()

    wall = time.perf_counter() - t0
    _print_summary(summary, db_path, args.client_id, wall)

    if summary.failed > 0 and summary.total == summary.failed:
        # Tous les docs ont échoué → exit non-zéro pour signaler le problème
        return 1
    return 0


def _accepted() -> set[str]:
    from fiduciaire_worker.ingest_local import ACCEPTED_SUFFIXES
    return ACCEPTED_SUFFIXES


if __name__ == "__main__":
    sys.exit(main())
