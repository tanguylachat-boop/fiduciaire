"""Tests pour `fiduciaire_worker.process_lock`.

Lock file POSIX simple (sans flock) : écrit PID + timestamp dans un fichier,
détecte les locks orphelins (PID mort) via `os.kill(pid, 0)`.

Compatible launchd / cron : 2e instance abort proprement avec exit code clair.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker.process_lock import (  # noqa: E402
    LockAcquireError,
    LockInfo,
    ProcessLock,
    is_pid_alive,
    parse_lock_file,
)


def test_acquire_creates_lock_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    lock = ProcessLock(lock_path)

    with lock:
        assert lock_path.exists()
        info = parse_lock_file(lock_path)
        assert info is not None
        assert info.pid == os.getpid()
        assert info.timestamp is not None


def test_release_removes_lock_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    lock = ProcessLock(lock_path)
    lock.acquire()
    assert lock_path.exists()
    lock.release()
    assert not lock_path.exists()


def test_context_manager_releases_on_exit(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    with ProcessLock(lock_path):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_context_manager_releases_on_exception(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    with pytest.raises(RuntimeError, match="boom"):
        with ProcessLock(lock_path):
            assert lock_path.exists()
            raise RuntimeError("boom")
    assert not lock_path.exists()


def test_second_acquire_fails_if_pid_alive(tmp_path: Path) -> None:
    """Process actuel est vivant → 2e acquire raise LockAcquireError."""
    lock_path = tmp_path / "test.lock"
    lock1 = ProcessLock(lock_path)
    lock1.acquire()
    try:
        lock2 = ProcessLock(lock_path)
        with pytest.raises(LockAcquireError) as exc_info:
            lock2.acquire()
        assert "déjà actif" in str(exc_info.value).lower() or \
               "pid" in str(exc_info.value).lower()
    finally:
        lock1.release()


def test_stale_lock_dead_pid_acquires_when_force(tmp_path: Path) -> None:
    """Si lock pointe vers PID mort → acquire avec force=True passe."""
    lock_path = tmp_path / "test.lock"
    # Écrit un lock orphelin manuel avec PID très improbable
    dead_pid = 999999
    assert not is_pid_alive(dead_pid)
    lock_path.write_text(f"pid={dead_pid}\ntimestamp=2020-01-01T00:00:00Z\n")

    lock = ProcessLock(lock_path)
    with pytest.raises(LockAcquireError):
        lock.acquire(force=False)

    lock.acquire(force=True)
    assert lock_path.exists()
    info = parse_lock_file(lock_path)
    assert info.pid == os.getpid()
    lock.release()


def test_stale_lock_dead_pid_auto_reclaim_without_force(tmp_path: Path) -> None:
    """Politique de défaut : PID mort + auto_reclaim_stale=True → on prend le lock."""
    lock_path = tmp_path / "test.lock"
    lock_path.write_text("pid=999999\ntimestamp=2020-01-01T00:00:00Z\n")

    lock = ProcessLock(lock_path, auto_reclaim_stale=True)
    lock.acquire(force=False)
    info = parse_lock_file(lock_path)
    assert info.pid == os.getpid()
    lock.release()


def test_parse_lock_file_returns_none_if_missing(tmp_path: Path) -> None:
    assert parse_lock_file(tmp_path / "absent.lock") is None


def test_parse_lock_file_returns_none_if_corrupt(tmp_path: Path) -> None:
    lock_path = tmp_path / "corrupt.lock"
    lock_path.write_text("not-a-lock-file")
    assert parse_lock_file(lock_path) is None


def test_is_pid_alive_self() -> None:
    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_dead() -> None:
    assert is_pid_alive(999999) is False


def test_lockinfo_dataclass() -> None:
    info = LockInfo(pid=42, timestamp="2026-05-11T10:00:00Z")
    assert info.pid == 42
    assert info.timestamp == "2026-05-11T10:00:00Z"


def test_lock_path_parents_created(tmp_path: Path) -> None:
    """Le parent du lock_path est créé si absent."""
    deep = tmp_path / "a" / "b" / "c" / "x.lock"
    assert not deep.parent.exists()
    with ProcessLock(deep):
        assert deep.exists()
    assert not deep.exists()


def test_release_idempotent(tmp_path: Path) -> None:
    """release() 2× ne raise pas."""
    lock_path = tmp_path / "test.lock"
    lock = ProcessLock(lock_path)
    lock.acquire()
    lock.release()
    lock.release()  # ne doit pas raise


def test_acquire_after_release_works(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    lock = ProcessLock(lock_path)
    lock.acquire()
    lock.release()
    lock.acquire()
    lock.release()
