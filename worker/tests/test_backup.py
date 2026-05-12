"""Tests `fiduciaire_worker.backup` — Sprint 1 §3.5.

Backup chiffré (Fernet) + restore + rétention 30/12/10 ans.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker.backup import (  # noqa: E402
    ARCHIVE_MAGIC,
    apply_retention,
    create_backup,
    restore_backup,
    verify_backup_restorable,
)
from fiduciaire_worker.encryption import (  # noqa: E402
    EncryptionError,
    MasterKey,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.delenv("FIDUCIAIRE_ENCRYPTION_DISABLED", raising=False)
    yield


def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fiduciaire.sqlite"
    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    # Ajoute quelques rows pour avoir un dump non vide
    conn.execute(
        "INSERT INTO documents (sha256, original_filename, archive_path, status) "
        "VALUES ('sha1', 'doc1.pdf', 'arch/sha1.pdf', 'routed')"
    )
    conn.execute(
        "INSERT INTO documents (sha256, original_filename, archive_path, status) "
        "VALUES ('sha2', 'doc2.pdf', 'arch/sha2.pdf', 'routed')"
    )
    conn.close()
    return db_path


def _seed_archive(tmp_path: Path) -> Path:
    archive_root = tmp_path / "archive"
    (archive_root / "cab-a").mkdir(parents=True)
    (archive_root / "cab-b").mkdir(parents=True)
    (archive_root / "cab-a" / "sha1.pdf").write_bytes(b"%PDF-1.4 cabinet-a")
    (archive_root / "cab-b" / "sha2.pdf").write_bytes(b"%PDF-1.4 cabinet-b")
    return archive_root


def _backup_key() -> MasterKey:
    return MasterKey.generate("backup-master")


# --- Create + restore --------------------------------------------------------


def test_create_backup_writes_encrypted_file(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    archive = _seed_archive(tmp_path)
    backups = tmp_path / "backups"

    key = _backup_key()
    result = create_backup(
        db_path=db_path, archive_root=archive,
        backup_dir=backups, key=key,
    )
    assert result.path.exists()
    blob = result.path.read_bytes()
    assert blob[:4] == ARCHIVE_MAGIC
    assert result.db_rows_total > 0
    assert result.archive_files == 2


def test_restore_backup_recreates_db_and_archive(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    archive = _seed_archive(tmp_path)
    backups = tmp_path / "backups"

    key = _backup_key()
    backup_res = create_backup(
        db_path=db_path, archive_root=archive,
        backup_dir=backups, key=key,
    )

    restore_dir = tmp_path / "restored"
    restore_res = restore_backup(backup_res.path, restore_dir, key=key)

    # DB restaurée a les mêmes docs
    conn = sqlite3.connect(str(restore_res.db_path))
    rows = conn.execute("SELECT sha256 FROM documents ORDER BY id").fetchall()
    conn.close()
    assert {r[0] for r in rows} == {"sha1", "sha2"}

    # Fichiers archive restaurés intacts
    assert (restore_dir / "archive" / "cab-a" / "sha1.pdf").read_bytes() == b"%PDF-1.4 cabinet-a"
    assert (restore_dir / "archive" / "cab-b" / "sha2.pdf").read_bytes() == b"%PDF-1.4 cabinet-b"


def test_restore_with_wrong_key_fails(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    archive = _seed_archive(tmp_path)
    backups = tmp_path / "backups"

    key = _backup_key()
    backup_res = create_backup(
        db_path=db_path, archive_root=archive,
        backup_dir=backups, key=key,
    )

    bad_key = MasterKey.generate("backup-master")
    with pytest.raises(EncryptionError):
        restore_backup(backup_res.path, tmp_path / "bad", key=bad_key)


def test_verify_backup_restorable_ok(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    archive = _seed_archive(tmp_path)
    key = _backup_key()
    backup_res = create_backup(
        db_path=db_path, archive_root=archive,
        backup_dir=tmp_path / "b", key=key,
    )

    ok, reason = verify_backup_restorable(
        backup_res.path, tmp_path / "verify_tmp", key=key,
    )
    assert ok is True
    assert reason is None


def test_verify_backup_restorable_detects_corruption(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    archive = _seed_archive(tmp_path)
    key = _backup_key()
    backup_res = create_backup(
        db_path=db_path, archive_root=archive,
        backup_dir=tmp_path / "b", key=key,
    )

    # Corrompt le fichier (modifie un byte au milieu)
    blob = backup_res.path.read_bytes()
    corrupted = blob[:100] + b"X" + blob[101:]
    backup_res.path.write_bytes(corrupted)

    ok, reason = verify_backup_restorable(
        backup_res.path, tmp_path / "v", key=key,
    )
    assert ok is False
    assert reason is not None


# --- Retention 30/12/10 -----------------------------------------------------


def _touch_backup(backup_dir: Path, dt: datetime) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    name = dt.strftime("backup-%Y-%m-%d-%H%M%S.tar.gz.fid")
    p = backup_dir / name
    p.write_bytes(b"FID1\x00\x00\x00\x01stub")
    return p


def test_retention_keeps_30_daily(tmp_path: Path) -> None:
    backups = tmp_path / "b"
    # Crée 35 backups daily (1 par jour, du 2026-01-01 au 2026-02-04)
    from datetime import timedelta
    base = datetime(2026, 1, 1, 3, 0, 0)
    paths = [_touch_backup(backups, base + timedelta(days=i)) for i in range(35)]
    assert all(p.exists() for p in paths)

    result = apply_retention(backups, daily_keep=30, monthly_keep=0,
                             yearly_keep=0)
    # Les 30 plus récents conservés
    assert len(result.kept_daily) == 30
    # 5 supprimés (les plus anciens — sauf si certains sont conservés par monthly)
    # Avec monthly_keep=0, yearly_keep=0 → vraiment 5 supprimés
    assert len(result.deleted) == 5


def test_retention_monthly_keeps_one_per_month(tmp_path: Path) -> None:
    backups = tmp_path / "b"
    # 1 backup par mois sur 18 mois
    from datetime import timedelta
    paths: list[Path] = []
    for month_offset in range(18):
        year = 2024 + (month_offset // 12)
        month = (month_offset % 12) + 1
        dt = datetime(year, month, 1, 3, 0, 0)
        paths.append(_touch_backup(backups, dt))

    result = apply_retention(backups, daily_keep=0,
                             monthly_keep=12, yearly_keep=0)
    # 12 mensuels conservés, 6 supprimés
    assert len(result.kept_monthly) == 12
    assert len(result.deleted) == 6


def test_retention_yearly_keeps_one_per_year(tmp_path: Path) -> None:
    backups = tmp_path / "b"
    # 1 backup par an sur 12 ans
    paths: list[Path] = []
    for year_offset in range(12):
        dt = datetime(2014 + year_offset, 6, 15, 3, 0, 0)
        paths.append(_touch_backup(backups, dt))

    result = apply_retention(backups, daily_keep=0,
                             monthly_keep=0, yearly_keep=10)
    assert len(result.kept_yearly) == 10
    assert len(result.deleted) == 2


def test_retention_combined_30_12_10(tmp_path: Path) -> None:
    """Test full 30/12/10 sur 100 backups répartis sur plusieurs années."""
    backups = tmp_path / "b"
    from datetime import timedelta
    base = datetime(2024, 1, 1, 3, 0, 0)
    # 100 backups daily du 2024-01-01 → ~2024-04-10
    for i in range(100):
        _touch_backup(backups, base + timedelta(days=i))

    result = apply_retention(backups)
    # Toutes les politiques actives
    keep_all = (set(result.kept_daily) | set(result.kept_monthly) |
                set(result.kept_yearly))
    # On garde forcément au moins 30 (daily) + monthly + yearly distincts
    assert len(keep_all) >= 30
    # Et au moins 1 supprimé (sinon retention sert à rien)
    assert len(result.deleted) > 0


def test_retention_dry_run_does_not_delete(tmp_path: Path) -> None:
    backups = tmp_path / "b"
    from datetime import timedelta
    base = datetime(2026, 1, 1, 3, 0, 0)
    paths = [_touch_backup(backups, base + timedelta(days=i)) for i in range(35)]

    result = apply_retention(backups, daily_keep=30, monthly_keep=0,
                             yearly_keep=0, dry_run=True)
    assert len(result.deleted) == 5
    # Mais les fichiers existent toujours
    assert all(p.exists() for p in paths)


def test_retention_ignores_non_backup_files(tmp_path: Path) -> None:
    backups = tmp_path / "b"
    backups.mkdir()
    (backups / "random.txt").write_text("not a backup")
    (backups / "backup-2026-01-01-030000.tar.gz.fid").write_bytes(b"FID1")

    result = apply_retention(backups)
    # random.txt n'apparaît dans aucune catégorie
    assert all(p.name != "random.txt" for p in result.deleted)
    assert (backups / "random.txt").exists()


# --- Multi-mandant content ---------------------------------------------------


def test_backup_contains_all_mandants_archive(tmp_path: Path) -> None:
    """Le backup global doit inclure les archives de tous les cabinets."""
    db_path = _seed_db(tmp_path)
    archive = tmp_path / "archive"
    for cab in ("cab-a", "cab-b", "cab-c"):
        (archive / cab).mkdir(parents=True)
        (archive / cab / f"{cab}.pdf").write_bytes(f"PDF-{cab}".encode())

    key = _backup_key()
    backup_res = create_backup(
        db_path=db_path, archive_root=archive,
        backup_dir=tmp_path / "b", key=key,
    )
    assert backup_res.archive_files == 3

    restore_res = restore_backup(
        backup_res.path, tmp_path / "restored", key=key,
    )
    # Vérifie que tous les cabinets sont restaurés
    for cab in ("cab-a", "cab-b", "cab-c"):
        path = restore_res.archive_path / cab / f"{cab}.pdf"
        assert path.exists()
        assert path.read_bytes() == f"PDF-{cab}".encode()
