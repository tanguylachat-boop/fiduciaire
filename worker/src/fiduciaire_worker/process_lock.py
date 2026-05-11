"""Lock file POSIX simple pour daemons / CLI cron-poll.

Use case : empêcher 2 instances simultanées de `imap_fetch` sur le même
cabinet quand launchd / cron se chevauche (poll 5 min sur un fetch qui dure
6 min).

Approche minimaliste sans `flock` :
- Écrit PID + timestamp ISO dans `data/locks/<name>.lock`.
- Au 2e acquire, lit le fichier, vérifie si PID encore vivant via
  `os.kill(pid, 0)`. Si vivant → raise LockAcquireError. Si mort → lock
  orphelin (auto-reclaim ou force).
- Cleanup automatique via context manager.

Pourquoi pas `fcntl.flock` ? Moins portable (Windows si jamais), moins
debuggable (état non lisible), et inutile pour notre cas (poll 5 min, pas
de concurrence haute fréquence). PID + os.kill suffit.

Sécurité : le lock file ne contient JAMAIS de credentials. Juste PID + ISO
timestamp.
"""

from __future__ import annotations

import errno
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("fiduciaire.process_lock")

_PID_RE = re.compile(r"pid=(\d+)")
_TS_RE = re.compile(r"timestamp=(\S+)")


class LockAcquireError(RuntimeError):
    """Lock détenu par un autre process vivant."""


@dataclass
class LockInfo:
    pid: int
    timestamp: str | None


def is_pid_alive(pid: int) -> bool:
    """True si un process avec ce PID existe encore (POSIX).

    `os.kill(pid, 0)` envoie le signal "null" — vérifie l'existence sans
    interrompre. ProcessLookupError = mort. PermissionError = vivant mais
    appartient à un autre user (donc considéré vivant).
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        return True
    return True


def parse_lock_file(path: Path) -> LockInfo | None:
    """Parse un fichier lock. Retourne None si absent ou corrompu."""
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m_pid = _PID_RE.search(content)
    if not m_pid:
        return None
    try:
        pid = int(m_pid.group(1))
    except ValueError:
        return None
    m_ts = _TS_RE.search(content)
    timestamp = m_ts.group(1) if m_ts else None
    return LockInfo(pid=pid, timestamp=timestamp)


class ProcessLock:
    """Lock file PID-based.

    Args:
        path: chemin du lock file (parent créé si absent).
        auto_reclaim_stale: si True, recycle silencieusement un lock dont
            le PID est mort. Si False (défaut), un lock orphelin force à
            passer `force=True` à `acquire()`.
    """

    def __init__(self, path: Path, auto_reclaim_stale: bool = False) -> None:
        self.path = Path(path)
        self.auto_reclaim_stale = auto_reclaim_stale
        self._owned = False

    # --- Context manager ---

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, tb) -> None:
        self.release()

    # --- Core ---

    def acquire(self, force: bool = False) -> None:
        """Prend le lock. Raise LockAcquireError si déjà détenu et vivant.

        Args:
            force: si True, recycle un lock orphelin même si
                `auto_reclaim_stale=False`.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = parse_lock_file(self.path)
        if existing is not None:
            if is_pid_alive(existing.pid):
                raise LockAcquireError(
                    f"Lock déjà actif: file={self.path} pid={existing.pid} "
                    f"started_at={existing.timestamp or 'unknown'}. "
                    "Si le process est vraiment mort, relancer avec --force."
                )
            # PID mort → stale lock
            if not (force or self.auto_reclaim_stale):
                raise LockAcquireError(
                    f"Lock orphelin (PID mort): file={self.path} "
                    f"pid={existing.pid} ts={existing.timestamp}. "
                    "Relancer avec --force pour reprendre."
                )
            _log.info(
                "reclaiming stale lock %s (dead pid=%d, ts=%s)",
                self.path, existing.pid, existing.timestamp,
            )

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content = f"pid={os.getpid()}\ntimestamp={ts}\n"
        self.path.write_text(content, encoding="utf-8")
        self._owned = True

    def release(self) -> None:
        """Supprime le lock file. Idempotent."""
        if not self._owned:
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("lock release failed for %s: %s", self.path, exc)
        finally:
            self._owned = False
