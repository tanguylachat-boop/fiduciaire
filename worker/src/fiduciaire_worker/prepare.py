"""Étape 1 — Préparation : sha256, copie archive, INSERT documents."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import db


@dataclass
class PrepareResult:
    doc_id: int
    sha256: str
    archive_path: Path
    is_new: bool


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def prepare(source: Path, archive_dir: Path, conn: sqlite3.Connection) -> PrepareResult:
    """Hash + archive + INSERT idempotent.

    Si le fichier existe déjà (même sha256), on logue et on retourne is_new=False
    sans recopier. Le caller décide quoi faire (ignorer ou retraiter).
    """
    digest = sha256_file(source)
    ext = source.suffix.lower() or ".bin"
    archive_path = archive_dir / f"{digest}{ext}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    if not archive_path.exists():
        shutil.copy2(source, archive_path)

    doc_id, is_new = db.insert_document(
        conn, sha256=digest, original_filename=source.name, archive_path=str(archive_path)
    )
    db.log_action(
        conn,
        doc_id,
        action="prepare",
        payload={"sha256": digest, "archive_path": str(archive_path), "is_new": is_new},
    )
    if not is_new:
        # marqueur soft : doublon ignoré, le watcher décidera de supprimer l'inbox
        db.log_action(conn, doc_id, action="duplicate_ignored", payload={"sha256": digest})

    return PrepareResult(doc_id=doc_id, sha256=digest, archive_path=archive_path, is_new=is_new)
