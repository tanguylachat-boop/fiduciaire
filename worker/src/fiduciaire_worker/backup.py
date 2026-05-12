"""Backup automatisé chiffré — Sprint 1 §3.5.

Stratégie :
1. Snapshot SQLite (`.dump` SQL via sqlite3.iterdump) + tar du dossier
   `data/archive/` (les PDFs sont déjà chiffrés individuellement par
   `encryption.py`).
2. Tout est compressé tar.gz puis chiffré en bloc via Fernet avec une
   clé maître backup distincte (Keychain `fiduciaire`, `backup-master-key`).
3. Rétention : 30 quotidiens + 12 mensuels + 10 ans annuels.

Pourquoi 2 niveaux de chiffrement (archive files + backup global) :
- Archive files chiffrés par cabinet → segmentation : compromis 1 clé
  cabinet ≠ compromis des autres.
- Backup global chiffré → protège le snapshot SQL (qui contient toutes
  les données métadata multi-mandant en clair).

Cf docs/decisions/2026-05-12-encryption-strategy.md.
"""

from __future__ import annotations

import io
import logging
import re
import sqlite3
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .encryption import (
    ARCHIVE_MAGIC,
    EncryptionError,
    MasterKey,
    decrypt_bytes,
    encrypt_bytes,
    ensure_master_key,
    get_master_key,
    is_encryption_disabled,
)

_log = logging.getLogger("fiduciaire.backup")

BACKUP_NAME_RE = re.compile(
    r"backup-(?P<date>\d{4}-\d{2}-\d{2})-(?P<time>\d{6})\.tar\.gz\.fid"
)
BACKUP_CABINET_ID = "backup-master"  # cabinet_id réservé pour la clé backup

DEFAULT_DAILY_KEEP = 30
DEFAULT_MONTHLY_KEEP = 12
DEFAULT_YEARLY_KEEP = 10


@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    db_rows_total: int
    archive_files: int
    duration_s: float


@dataclass
class RetentionResult:
    kept_daily: list[Path] = field(default_factory=list)
    kept_monthly: list[Path] = field(default_factory=list)
    kept_yearly: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)


@dataclass
class RestoreResult:
    db_path: Path
    archive_path: Path
    db_rows_total: int
    archive_files: int


# --- Helpers DB --------------------------------------------------------------


def _dump_db_to_sql(db_path: Path) -> bytes:
    """Snapshot SQL d'une DB SQLite via iterdump."""
    conn = sqlite3.connect(str(db_path))
    try:
        return "\n".join(conn.iterdump()).encode("utf-8")
    finally:
        conn.close()


def _restore_db_from_sql(sql_blob: bytes, dst_db: Path) -> None:
    """Crée une DB SQLite depuis un dump SQL bytes."""
    if dst_db.exists():
        dst_db.unlink()
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(dst_db))
    try:
        conn.executescript(sql_blob.decode("utf-8"))
    finally:
        conn.close()


def _count_db_rows(db_path: Path) -> int:
    """Compte total des rows sur les tables utilisateur (debug/audit)."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        total = 0
        for (name,) in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            total += count
        return total
    finally:
        conn.close()


# --- Backup creation ---------------------------------------------------------


def create_backup(
    *,
    db_path: Path,
    archive_root: Path,
    backup_dir: Path,
    key: MasterKey | None = None,
    timestamp: datetime | None = None,
) -> BackupResult:
    """Crée un backup chiffré dans `backup_dir/backup-YYYY-MM-DD-HHMMSS.tar.gz.fid`.

    Args:
        db_path: DB SQLite à snapshoter.
        archive_root: dossier `data/archive/` à inclure (récursif).
        backup_dir: destination des backups.
        key: clé backup. Défaut: ensure_master_key(BACKUP_CABINET_ID).
        timestamp: horodatage forcé (utile tests). Défaut: now UTC.
    """
    t0 = time.perf_counter()
    ts = timestamp or datetime.now(timezone.utc)
    name = ts.strftime("backup-%Y-%m-%d-%H%M%S.tar.gz.fid")
    backup_dir.mkdir(parents=True, exist_ok=True)
    out_path = backup_dir / name

    if key is None and is_encryption_disabled():
        # En mode dev, on autorise key=None → pas de chiffrement
        # mais le fichier garde le suffixe .fid pour cohérence
        key = None
    elif key is None:
        key = ensure_master_key(BACKUP_CABINET_ID)

    # Build tar.gz en mémoire
    tar_buf = io.BytesIO()
    db_rows = 0
    archive_count = 0
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        if db_path.exists():
            sql_blob = _dump_db_to_sql(db_path)
            ti = tarfile.TarInfo(name="db.sql")
            ti.size = len(sql_blob)
            ti.mtime = int(ts.timestamp())
            tar.addfile(ti, io.BytesIO(sql_blob))
            db_rows = _count_db_rows(db_path)

        if archive_root.exists():
            for file in sorted(archive_root.rglob("*")):
                if not file.is_file():
                    continue
                rel = file.relative_to(archive_root.parent)
                tar.add(str(file), arcname=str(rel))
                archive_count += 1

    tar_bytes = tar_buf.getvalue()

    if key is None:
        # Mode disabled : on écrit le tar.gz brut sans Fernet
        out_path.write_bytes(tar_bytes)
    else:
        token = encrypt_bytes(tar_bytes, key)
        # Préfixe FID1 + version pour cohérence avec encryption.py
        blob = ARCHIVE_MAGIC + b"\x00\x00\x00\x01" + token
        out_path.write_bytes(blob)

    duration = time.perf_counter() - t0
    size = out_path.stat().st_size
    _log.info(
        "backup created path=%s size=%d db_rows=%d archive=%d dur=%.1fs",
        out_path, size, db_rows, archive_count, duration,
    )
    return BackupResult(
        path=out_path, size_bytes=size,
        db_rows_total=db_rows, archive_files=archive_count,
        duration_s=duration,
    )


# --- Backup restore ----------------------------------------------------------


def restore_backup(
    backup_path: Path,
    restore_root: Path,
    key: MasterKey | None = None,
) -> RestoreResult:
    """Restaure un backup chiffré dans restore_root/.

    Crée `restore_root/db.sqlite` + `restore_root/archive/...`.

    Raises:
        EncryptionError: si la clé est invalide ou le fichier corrompu.
    """
    blob = backup_path.read_bytes()

    # Détection chiffré vs disabled
    if blob.startswith(ARCHIVE_MAGIC):
        if key is None:
            key = get_master_key(BACKUP_CABINET_ID)
        # Skip header (4 + 4)
        token = blob[8:]
        try:
            tar_bytes = decrypt_bytes(token, key)
        except EncryptionError:
            raise
    else:
        # Mode disabled : tar.gz en clair
        tar_bytes = blob

    restore_root.mkdir(parents=True, exist_ok=True)
    db_path = restore_root / "db.sqlite"
    archive_path = restore_root / "archive"
    archive_path.mkdir(parents=True, exist_ok=True)

    archive_count = 0
    db_rows = 0
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if member.name == "db.sql":
                f = tar.extractfile(member)
                assert f is not None
                _restore_db_from_sql(f.read(), db_path)
                db_rows = _count_db_rows(db_path)
            else:
                f = tar.extractfile(member)
                if f is None:
                    continue
                # Le member name est typiquement "archive/<cabinet>/<sha>.pdf"
                # On strippe le préfixe "archive/" pour le coller dans archive_path
                rel = member.name
                if rel.startswith("archive/"):
                    rel = rel[len("archive/"):]
                dest = archive_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(f.read())
                archive_count += 1

    return RestoreResult(
        db_path=db_path, archive_path=archive_path,
        db_rows_total=db_rows, archive_files=archive_count,
    )


# --- Retention --------------------------------------------------------------


def _parse_backup_dt(path: Path) -> datetime | None:
    m = BACKUP_NAME_RE.match(path.name)
    if not m:
        return None
    try:
        return datetime.strptime(
            f"{m.group('date')}-{m.group('time')}",
            "%Y-%m-%d-%H%M%S",
        )
    except ValueError:
        return None


def apply_retention(
    backup_dir: Path,
    daily_keep: int = DEFAULT_DAILY_KEEP,
    monthly_keep: int = DEFAULT_MONTHLY_KEEP,
    yearly_keep: int = DEFAULT_YEARLY_KEEP,
    dry_run: bool = False,
) -> RetentionResult:
    """Applique la politique de rétention 30/12/10 sur backup_dir.

    Stratégie :
    - Trie les backups par timestamp (du plus récent au plus ancien).
    - daily_keep premiers backups → kept_daily.
    - Premier backup de chaque mois (parmi les `monthly_keep` derniers mois)
      → kept_monthly.
    - Premier backup de chaque année (parmi les `yearly_keep` dernières)
      → kept_yearly.
    - Le reste → deleted.

    Args:
        dry_run: si True, n'efface pas, retourne juste le plan.
    """
    candidates: list[tuple[datetime, Path]] = []
    for p in backup_dir.iterdir():
        if not p.is_file():
            continue
        dt = _parse_backup_dt(p)
        if dt is not None:
            candidates.append((dt, p))
    candidates.sort(key=lambda x: x[0], reverse=True)  # plus récent en premier

    result = RetentionResult()

    # Daily : les N plus récents
    daily_set = {p for _, p in candidates[:daily_keep]}
    result.kept_daily = list(daily_set)

    # Monthly : 1 par mois (le plus ancien du mois, qui est aussi le 1er du mois généralement)
    months_seen: dict[str, Path] = {}
    for dt, p in reversed(candidates):  # plus ancien en premier
        key = f"{dt.year}-{dt.month:02d}"
        if key not in months_seen:
            months_seen[key] = p
    # Garde les `monthly_keep` mois les plus récents
    monthly_sorted = sorted(months_seen.items(), reverse=True)[:monthly_keep]
    monthly_set = {p for _, p in monthly_sorted}
    result.kept_monthly = list(monthly_set)

    # Yearly : 1 par année (le plus ancien)
    years_seen: dict[int, Path] = {}
    for dt, p in reversed(candidates):
        if dt.year not in years_seen:
            years_seen[dt.year] = p
    yearly_sorted = sorted(years_seen.items(), reverse=True)[:yearly_keep]
    yearly_set = {p for _, p in yearly_sorted}
    result.kept_yearly = list(yearly_set)

    keep_all = daily_set | monthly_set | yearly_set
    for _, p in candidates:
        if p not in keep_all:
            result.deleted.append(p)
            if not dry_run:
                p.unlink(missing_ok=True)

    return result


# --- Restore test (idempotence check) ----------------------------------------


def verify_backup_restorable(
    backup_path: Path,
    tmp_dir: Path,
    key: MasterKey | None = None,
) -> tuple[bool, str | None]:
    """Test rapide : restaure dans tmp_dir, vérifie quelques queries DB.

    Retourne (True, None) si tout OK, (False, "raison") si KO.
    À lancer mensuellement via launchd pour valider l'intégrité.
    """
    try:
        result = restore_backup(backup_path, tmp_dir, key=key)
    except Exception as exc:
        return False, f"restore failed: {type(exc).__name__}: {exc}"

    # Smoke queries
    try:
        conn = sqlite3.connect(str(result.db_path))
        try:
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return False, f"DB corrupted: {exc}"

    return True, None
