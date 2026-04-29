"""Watcher filesystem sur paths.inbox.

Sur file_created (PDF/PNG/JPG/TIF), debounce ~1.5 s puis appelle pipeline.process_document.
Le debounce évite de traiter un fichier en cours d'écriture (scanners qui copient en plusieurs blocs).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from watchdog.observers import Observer

from . import db
from .config import Config
from .pipeline import process_document

log = logging.getLogger("fiduciaire.watcher")

ACCEPTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def _is_stable(path: Path, settle_s: float = 1.5, checks: int = 3) -> bool:
    """Vérifie que la taille ne change plus pendant settle_s × checks secondes."""
    last = -1
    for _ in range(checks):
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size == last and size > 0:
            return True
        last = size
        time.sleep(settle_s)
    return last > 0


class InboxHandler(FileSystemEventHandler):
    def __init__(self, config: Config):
        self.config = config
        self._lock = threading.Lock()

    def _maybe_process(self, path_str: str) -> None:
        path = Path(path_str)
        if path.suffix.lower() not in ACCEPTED_SUFFIXES:
            return
        if not _is_stable(path):
            log.warning("fichier instable, skip: %s", path)
            return
        with self._lock:
            try:
                conn = db.connect(self.config.paths.db)
                db.init_schema(conn)
                outcome = process_document(path, self.config, conn)
                log.info(
                    "✓ %s → status=%s final=%s qr=%s dur=%.1fs reasons=%s",
                    path.name,
                    outcome.status,
                    outcome.final_path.name if outcome.final_path else None,
                    outcome.qr_used,
                    outcome.duration_s,
                    outcome.review_reasons or "-",
                )
                conn.close()
            except Exception as e:
                log.exception("pipeline error on %s: %s", path, e)

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            threading.Thread(target=self._maybe_process, args=(event.src_path,), daemon=True).start()

    def on_moved(self, event):
        if isinstance(event, FileMovedEvent) and not event.is_directory:
            threading.Thread(target=self._maybe_process, args=(event.dest_path,), daemon=True).start()


def run(config: Config) -> None:
    config.paths.ensure()
    handler = InboxHandler(config)
    observer = Observer()
    observer.schedule(handler, str(config.paths.inbox), recursive=False)
    observer.start()
    log.info("watching: %s", config.paths.inbox)

    # Traite les fichiers déjà présents au démarrage
    for f in sorted(config.paths.inbox.iterdir()):
        if f.is_file() and f.suffix.lower() in ACCEPTED_SUFFIXES:
            handler._maybe_process(str(f))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
