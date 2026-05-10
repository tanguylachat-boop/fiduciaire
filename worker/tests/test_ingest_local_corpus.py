"""Tests pour `fiduciaire_worker.ingest_local` (logique du script ingest_local_corpus.py).

Le script CLI (`worker/scripts/ingest_local_corpus.py`) est un thin wrapper
sur `fiduciaire_worker.ingest_local.ingest_corpus()`. Cette suite couvre
la logique : iteration fichiers supportés, agrégation des outcomes,
gestion d'erreurs par doc, callback de progression.

Le pipeline lui-même est mocké : il a déjà sa propre suite de tests
d'intégration (`test_pipeline_integration.py`).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import db  # noqa: E402
from fiduciaire_worker.ingest_local import (  # noqa: E402
    ACCEPTED_SUFFIXES,
    IngestSummary,
    ingest_corpus,
    iter_supported_files,
)
from fiduciaire_worker.pipeline import PipelineOutcome  # noqa: E402


# --- iter_supported_files -----------------------------------------------------


def test_iter_supported_files_filters_by_suffix(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "b.txt").write_text("note")
    (tmp_path / "c.PNG").write_bytes(b"\x89PNG")
    (tmp_path / "d.docx").write_bytes(b"x")
    out = iter_supported_files(tmp_path)
    names = [p.name for p in out]
    assert "a.pdf" in names
    assert "c.PNG" in names
    assert "b.txt" not in names
    assert "d.docx" not in names


def test_iter_supported_files_sorted_alphabetically(tmp_path: Path) -> None:
    for n in ("c.pdf", "a.pdf", "b.pdf"):
        (tmp_path / n).write_bytes(b"x")
    out = iter_supported_files(tmp_path)
    assert [p.name for p in out] == ["a.pdf", "b.pdf", "c.pdf"]


def test_iter_supported_files_ignores_hidden(tmp_path: Path) -> None:
    (tmp_path / ".DS_Store").write_bytes(b"x")
    (tmp_path / ".hidden.pdf").write_bytes(b"x")
    (tmp_path / "real.pdf").write_bytes(b"x")
    out = iter_supported_files(tmp_path)
    assert [p.name for p in out] == ["real.pdf"]


def test_iter_supported_files_ignores_subdirs(tmp_path: Path) -> None:
    (tmp_path / "real.pdf").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "ignored.pdf").write_bytes(b"x")
    out = iter_supported_files(tmp_path)
    assert [p.name for p in out] == ["real.pdf"]


def test_iter_supported_files_empty_dir(tmp_path: Path) -> None:
    assert iter_supported_files(tmp_path) == []


def test_iter_supported_files_dir_not_exists_raises(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, NotADirectoryError)):
        iter_supported_files(tmp_path / "nope")


def test_accepted_suffixes_match_watcher() -> None:
    """Doit rester aligné avec watcher.ACCEPTED_SUFFIXES."""
    from fiduciaire_worker.watcher import ACCEPTED_SUFFIXES as WATCHER_SUFFIXES
    assert ACCEPTED_SUFFIXES == WATCHER_SUFFIXES


# --- ingest_corpus ------------------------------------------------------------


def _make_outcome(doc_id: int, status: str, duration_s: float = 1.0,
                  reasons: list[str] | None = None) -> PipelineOutcome:
    return PipelineOutcome(
        doc_id=doc_id,
        sha256=f"sha{doc_id}",
        status=status,
        final_path=None,
        classification=None,
        qr_used=False,
        duration_s=duration_s,
        review_reasons=reasons or [],
    )


def test_ingest_corpus_calls_process_document_per_file(tmp_path: Path) -> None:
    for n in ("a.pdf", "b.pdf", "c.pdf"):
        (tmp_path / n).write_bytes(b"x")

    fake_config = MagicMock()
    fake_conn = MagicMock(spec=sqlite3.Connection)

    with patch("fiduciaire_worker.ingest_local.process_document") as pd:
        pd.side_effect = [
            _make_outcome(1, db.STATUS_ROUTED),
            _make_outcome(2, db.STATUS_ROUTED),
            _make_outcome(3, db.STATUS_ROUTED),
        ]
        summary = ingest_corpus(tmp_path, fake_config, fake_conn)

    assert pd.call_count == 3
    for call in pd.call_args_list:
        # delete_inbox=False obligatoire pour ne pas effacer data/samples
        assert call.kwargs.get("delete_inbox") is False
    assert summary.total == 3
    assert summary.routed == 3


def test_ingest_corpus_summary_mixed_statuses(tmp_path: Path) -> None:
    for n in ("a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf"):
        (tmp_path / n).write_bytes(b"x")

    fake_config = MagicMock()
    fake_conn = MagicMock(spec=sqlite3.Connection)

    with patch("fiduciaire_worker.ingest_local.process_document") as pd:
        pd.side_effect = [
            _make_outcome(1, db.STATUS_ROUTED, duration_s=1.0),
            _make_outcome(2, db.STATUS_NEEDS_REVIEW, duration_s=2.0,
                          reasons=["client_null"]),
            _make_outcome(3, db.STATUS_FAILED, duration_s=0.5,
                          reasons=["ocr_error:foo"]),
            _make_outcome(4, db.STATUS_DUPLICATE, duration_s=0.1),
            _make_outcome(5, db.STATUS_ROUTED, duration_s=1.5),
        ]
        summary = ingest_corpus(tmp_path, fake_config, fake_conn)

    assert summary.total == 5
    assert summary.routed == 2
    assert summary.needs_review == 1
    assert summary.failed == 1
    assert summary.duplicates == 1


def test_ingest_corpus_continues_on_doc_exception(tmp_path: Path) -> None:
    """Si process_document raise sur 1 doc, les autres continuent et l'erreur
    est comptée comme failed."""
    for n in ("a.pdf", "b.pdf", "c.pdf"):
        (tmp_path / n).write_bytes(b"x")

    fake_config = MagicMock()
    fake_conn = MagicMock(spec=sqlite3.Connection)

    with patch("fiduciaire_worker.ingest_local.process_document") as pd:
        pd.side_effect = [
            _make_outcome(1, db.STATUS_ROUTED),
            RuntimeError("Ollama timeout"),
            _make_outcome(3, db.STATUS_ROUTED),
        ]
        summary = ingest_corpus(tmp_path, fake_config, fake_conn)

    assert summary.total == 3
    assert summary.routed == 2
    assert summary.failed == 1
    failed_entry = next(e for e in summary.by_file if e["status"] == "failed")
    assert "Ollama" in failed_entry["error"]


def test_ingest_corpus_durations_collected(tmp_path: Path) -> None:
    for n in ("a.pdf", "b.pdf", "c.pdf"):
        (tmp_path / n).write_bytes(b"x")

    fake_config = MagicMock()
    fake_conn = MagicMock(spec=sqlite3.Connection)

    with patch("fiduciaire_worker.ingest_local.process_document") as pd:
        pd.side_effect = [
            _make_outcome(1, db.STATUS_ROUTED, duration_s=1.0),
            _make_outcome(2, db.STATUS_ROUTED, duration_s=2.0),
            _make_outcome(3, db.STATUS_ROUTED, duration_s=3.0),
        ]
        summary = ingest_corpus(tmp_path, fake_config, fake_conn)

    assert summary.median_duration_s == pytest.approx(2.0)
    assert summary.total_duration_s == pytest.approx(6.0)


def test_ingest_corpus_progress_callback(tmp_path: Path) -> None:
    for n in ("a.pdf", "b.pdf"):
        (tmp_path / n).write_bytes(b"x")

    fake_config = MagicMock()
    fake_conn = MagicMock(spec=sqlite3.Connection)

    progress_calls: list[tuple[int, int, str, str]] = []

    def on_progress(k, n, path, outcome):
        progress_calls.append((k, n, path.name, outcome.status))

    with patch("fiduciaire_worker.ingest_local.process_document") as pd:
        pd.side_effect = [
            _make_outcome(1, db.STATUS_ROUTED),
            _make_outcome(2, db.STATUS_NEEDS_REVIEW),
        ]
        ingest_corpus(tmp_path, fake_config, fake_conn, on_progress=on_progress)

    assert progress_calls == [
        (1, 2, "a.pdf", db.STATUS_ROUTED),
        (2, 2, "b.pdf", db.STATUS_NEEDS_REVIEW),
    ]


def test_ingest_corpus_empty_dir_returns_empty_summary(tmp_path: Path) -> None:
    fake_config = MagicMock()
    fake_conn = MagicMock(spec=sqlite3.Connection)
    summary = ingest_corpus(tmp_path, fake_config, fake_conn)
    assert summary.total == 0
    assert summary.routed == 0
    assert summary.median_duration_s is None
    assert summary.total_duration_s == 0.0


def test_ingest_corpus_dir_not_exists_raises(tmp_path: Path) -> None:
    fake_config = MagicMock()
    fake_conn = MagicMock(spec=sqlite3.Connection)
    with pytest.raises((FileNotFoundError, NotADirectoryError)):
        ingest_corpus(tmp_path / "nope", fake_config, fake_conn)


def test_ingest_summary_by_file_records_metadata(tmp_path: Path) -> None:
    for n in ("a.pdf", "b.pdf"):
        (tmp_path / n).write_bytes(b"x")

    fake_config = MagicMock()
    fake_conn = MagicMock(spec=sqlite3.Connection)

    with patch("fiduciaire_worker.ingest_local.process_document") as pd:
        pd.side_effect = [
            _make_outcome(11, db.STATUS_ROUTED, duration_s=1.2),
            _make_outcome(12, db.STATUS_NEEDS_REVIEW, duration_s=2.4,
                          reasons=["montant_null"]),
        ]
        summary = ingest_corpus(tmp_path, fake_config, fake_conn)

    assert len(summary.by_file) == 2
    a = summary.by_file[0]
    b = summary.by_file[1]
    assert a["filename"] == "a.pdf"
    assert a["status"] == db.STATUS_ROUTED
    assert a["doc_id"] == 11
    assert a["duration_s"] == pytest.approx(1.2)
    assert a["reasons"] == []
    assert b["status"] == db.STATUS_NEEDS_REVIEW
    assert b["reasons"] == ["montant_null"]


# --- IngestSummary properties -------------------------------------------------


def test_ingest_summary_median_with_one_value() -> None:
    s = IngestSummary(
        total=1, routed=1, needs_review=0, failed=0, duplicates=0,
        durations_s=[1.5], by_file=[],
    )
    assert s.median_duration_s == pytest.approx(1.5)
    assert s.total_duration_s == pytest.approx(1.5)


def test_ingest_summary_median_empty() -> None:
    s = IngestSummary(
        total=0, routed=0, needs_review=0, failed=0, duplicates=0,
        durations_s=[], by_file=[],
    )
    assert s.median_duration_s is None
    assert s.total_duration_s == 0.0
