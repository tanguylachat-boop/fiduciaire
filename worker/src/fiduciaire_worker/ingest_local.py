"""Ingestion d'un corpus local via le pipeline complet.

Itère sur les fichiers supportés d'un dossier (ex. `data/samples/`),
appelle `pipeline.process_document` pour chacun avec `delete_inbox=False`
(important : on ne veut pas supprimer le corpus source). Agrège les
outcomes dans une `IngestSummary` exploitable par le CLI ou les tests.

Use case principal : populer `data/fiduciaire.sqlite` avec les vraies
métadonnées OCR + classification avant de lancer `entry_bench.py`. Cf
`docs/specs/ingest-local-corpus.md` pour le contexte (bench RunPod
2026-05-10 inconclusif faute de pipeline d'ingestion).
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .pipeline import PipelineOutcome, process_document
from .watcher import ACCEPTED_SUFFIXES as _WATCHER_SUFFIXES

# Aligné avec watcher.ACCEPTED_SUFFIXES (test_accepted_suffixes_match_watcher).
ACCEPTED_SUFFIXES: set[str] = set(_WATCHER_SUFFIXES)

_log = logging.getLogger("fiduciaire.ingest_local")


@dataclass
class IngestSummary:
    total: int
    routed: int
    needs_review: int
    failed: int
    duplicates: int
    durations_s: list[float]
    by_file: list[dict[str, Any]] = field(default_factory=list)

    @property
    def median_duration_s(self) -> float | None:
        if not self.durations_s:
            return None
        return statistics.median(self.durations_s)

    @property
    def total_duration_s(self) -> float:
        return float(sum(self.durations_s))


def iter_supported_files(directory: Path) -> list[Path]:
    """Retourne les fichiers du dossier dont le suffixe est dans
    `ACCEPTED_SUFFIXES`, triés par nom. Non récursif. Ignore les
    fichiers cachés (commençant par '.') et les sous-dossiers.

    Raises:
        NotADirectoryError: si `directory` existe mais n'est pas un dossier.
        FileNotFoundError: si `directory` n'existe pas.
    """
    if not directory.exists():
        raise FileNotFoundError(f"dossier introuvable: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"pas un dossier: {directory}")

    out: list[Path] = []
    for p in directory.iterdir():
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        if p.suffix.lower() not in ACCEPTED_SUFFIXES:
            continue
        out.append(p)
    return sorted(out, key=lambda x: x.name)


ProgressCallback = Callable[[int, int, Path, PipelineOutcome], None]


def ingest_corpus(
    directory: Path,
    config: Config,
    conn: sqlite3.Connection,
    on_progress: ProgressCallback | None = None,
) -> IngestSummary:
    """Ingère tous les fichiers supportés du dossier via le pipeline complet.

    Args:
        directory: dossier source (ex. `data/samples/`).
        config: configuration cabinet déjà chargée.
        conn: connexion SQLite avec schéma déjà initialisé.
        on_progress: callback optionnel `(k, n, path, outcome) -> None`,
            appelé après chaque doc traité (k=index 1-based, n=total).

    Returns:
        IngestSummary avec compteurs par statut + durations + détail par
        fichier.

    Notes:
        - Utilise `delete_inbox=False` pour ne pas effacer le corpus.
        - Si `process_document` lève une exception sur un doc, le doc est
          compté comme `failed` et l'iteration continue (utile pour bench).
    """
    files = iter_supported_files(directory)
    n = len(files)

    summary = IngestSummary(
        total=0, routed=0, needs_review=0, failed=0, duplicates=0,
        durations_s=[],
    )

    for idx, path in enumerate(files, start=1):
        try:
            outcome = process_document(path, config, conn, delete_inbox=False)
            error_msg: str | None = None
        except Exception as exc:  # noqa: BLE001 — bench mode tolère les erreurs par doc
            _log.warning("process_document raised on %s: %s", path.name, exc)
            outcome = PipelineOutcome(
                doc_id=-1,
                sha256="",
                status="failed",
                final_path=None,
                classification=None,
                qr_used=False,
                duration_s=0.0,
                review_reasons=[],
                skipped_reason=None,
            )
            error_msg = f"{type(exc).__name__}: {exc}"

        summary.total += 1
        summary.durations_s.append(outcome.duration_s)

        if outcome.status == "routed":
            summary.routed += 1
        elif outcome.status == "needs_review":
            summary.needs_review += 1
        elif outcome.status == "failed":
            summary.failed += 1
        elif outcome.status == "duplicate":
            summary.duplicates += 1
        # tout autre status reste juste compté dans total (ex. "ingested" si
        # le pipeline est interrompu en cours — devrait pas arriver).

        record: dict[str, Any] = {
            "filename": path.name,
            "status": outcome.status,
            "doc_id": outcome.doc_id,
            "duration_s": outcome.duration_s,
            "reasons": list(outcome.review_reasons),
        }
        if error_msg is not None:
            record["error"] = error_msg
        summary.by_file.append(record)

        if on_progress is not None:
            on_progress(idx, n, path, outcome)

    return summary
