"""Chiffrement at-rest pour les fichiers archive — Sprint 1 §3.4.

Stratégie Sprint 1 (documentée dans
`docs/decisions/2026-05-12-encryption-strategy.md`) :

1. **Fichiers PDF dans `data/archive/<cabinet>/`** : chiffrés via Fernet
   (AES-128-CBC + HMAC-SHA256, lib `cryptography`). 1 clé par cabinet,
   stockée dans Keychain macOS (fallback `.env` pour dev).

2. **DB SQLite `fiduciaire.sqlite`** : NON chiffrée par cette couche.
   Repose sur FileVault macOS (disk-level encryption) actif sur le Mac
   Mini cabinet. SQLCipher reporté Sprint 2 (install pénible, gain
   marginal vs FileVault déjà actif).

3. **Mode dev** : `FIDUCIAIRE_ENCRYPTION_DISABLED=true` désactive le
   chiffrement (utile pour tests rapides, jamais en prod).

Format on-disk d'un fichier chiffré :
  bytes 0-3   : magic `FID1` (validation)
  bytes 4-7   : version `\x00\x00\x00\x01`
  bytes 8+    : Fernet token (base64url, AES-CBC + HMAC)

Cf RFC 7518 (Fernet specification informelle :
https://github.com/fernet/spec).
"""

from __future__ import annotations

import base64
import logging
import os
import secrets as py_secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from . import secrets as secrets_mod

_log = logging.getLogger("fiduciaire.encryption")

ENCRYPTION_DISABLED_ENV = "FIDUCIAIRE_ENCRYPTION_DISABLED"
KEYRING_PREFIX = "encryption-key"
ARCHIVE_MAGIC = b"FID1"
ARCHIVE_VERSION = b"\x00\x00\x00\x01"
HEADER_LENGTH = len(ARCHIVE_MAGIC) + len(ARCHIVE_VERSION)


class EncryptionError(RuntimeError):
    """Erreur générique de chiffrement / déchiffrement."""


class KeyNotFoundError(EncryptionError):
    """Clé absente du Keychain ET de l'env."""


@dataclass
class MasterKey:
    """Clé symétrique 256-bit pour Fernet.

    `value`: les 32 bytes encodés en base64url (format attendu par Fernet).
    """
    cabinet_id: str
    value: bytes  # 44 chars base64url (32 bytes raw)

    @classmethod
    def generate(cls, cabinet_id: str) -> "MasterKey":
        return cls(cabinet_id=cabinet_id, value=Fernet.generate_key())

    @property
    def fernet(self) -> Fernet:
        return Fernet(self.value)


# --- Disabled-mode helper ----------------------------------------------------


def is_encryption_disabled() -> bool:
    return os.getenv(ENCRYPTION_DISABLED_ENV, "").lower() == "true"


# --- Key resolution ----------------------------------------------------------


def _keyring_user_for(cabinet_id: str) -> str:
    return f"{KEYRING_PREFIX}-{cabinet_id}"


def _env_var_for(cabinet_id: str) -> str:
    norm = cabinet_id.replace("-", "_").replace(".", "_").upper()
    return f"FIDUCIAIRE_ENCRYPTION_KEY_{norm}"


def _try_keyring_get(cabinet_id: str) -> bytes | None:
    val = secrets_mod._try_keyring(  # type: ignore[attr-defined]
        secrets_mod.KEYRING_SERVICE, _keyring_user_for(cabinet_id),
    )
    return val.encode("ascii") if val else None


def _try_keyring_set(cabinet_id: str, key: bytes) -> bool:
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        keyring.set_password(
            secrets_mod.KEYRING_SERVICE,
            _keyring_user_for(cabinet_id),
            key.decode("ascii"),
        )
        return True
    except Exception as exc:  # pragma: no cover — backend pas configuré
        _log.debug("keyring set failed for %s: %s", cabinet_id, type(exc).__name__)
        return False


def get_master_key(cabinet_id: str) -> MasterKey:
    """Résout la clé depuis Keychain → env var. Raise si absente.

    Pour créer une nouvelle clé, voir `ensure_master_key()`.
    """
    val = _try_keyring_get(cabinet_id)
    if val:
        return MasterKey(cabinet_id=cabinet_id, value=val)

    secrets_mod._load_dotenv_if_available()  # type: ignore[attr-defined]
    env = os.getenv(_env_var_for(cabinet_id))
    if env:
        return MasterKey(cabinet_id=cabinet_id, value=env.encode("ascii"))

    raise KeyNotFoundError(
        f"Clé encryption introuvable pour cabinet={cabinet_id}. "
        f"Sources tentées : Keychain user='{_keyring_user_for(cabinet_id)}' "
        f"+ env var '{_env_var_for(cabinet_id)}'. "
        f"Pour en créer une : ensure_master_key('{cabinet_id}')."
    )


def ensure_master_key(cabinet_id: str) -> MasterKey:
    """Retourne la clé existante OU en génère une nouvelle (persistée Keychain).

    Si le Keychain n'est pas accessible, retourne quand même la clé mais
    n'avertit pas (caller responsable de la persister via env var manuellement).
    """
    try:
        return get_master_key(cabinet_id)
    except KeyNotFoundError:
        pass

    key = MasterKey.generate(cabinet_id)
    persisted = _try_keyring_set(cabinet_id, key.value)
    if not persisted:
        _log.warning(
            "encryption key generated for cabinet=%s mais Keychain inaccessible. "
            "À persister manuellement via env var %s.",
            cabinet_id, _env_var_for(cabinet_id),
        )
    return key


# --- Bytes encryption --------------------------------------------------------


def encrypt_bytes(data: bytes, key: MasterKey) -> bytes:
    """Chiffre data → token Fernet bytes."""
    return key.fernet.encrypt(data)


def decrypt_bytes(token: bytes, key: MasterKey) -> bytes:
    """Déchiffre un token Fernet. Raise EncryptionError si KO."""
    try:
        return key.fernet.decrypt(token)
    except InvalidToken as exc:
        raise EncryptionError(
            "decrypt failed (token invalide ou mauvaise clé)"
        ) from exc


# --- File encryption ---------------------------------------------------------


def _wrap_file_format(token: bytes) -> bytes:
    """Préfixe magic + version au token Fernet."""
    return ARCHIVE_MAGIC + ARCHIVE_VERSION + token


def _unwrap_file_format(blob: bytes) -> bytes:
    """Strip magic + version. Raise si format invalide."""
    if len(blob) < HEADER_LENGTH:
        raise EncryptionError("fichier trop court pour être chiffré (header manquant)")
    if blob[:4] != ARCHIVE_MAGIC:
        raise EncryptionError(
            f"magic invalide: attendu {ARCHIVE_MAGIC!r}, reçu {blob[:4]!r}"
        )
    if blob[4:8] != ARCHIVE_VERSION:
        raise EncryptionError(
            f"version inconnue: {blob[4:8]!r} (attendu {ARCHIVE_VERSION!r})"
        )
    return blob[HEADER_LENGTH:]


def is_encrypted_file(path: Path) -> bool:
    """True si le fichier commence par le magic FID1."""
    try:
        with open(path, "rb") as f:
            header = f.read(len(ARCHIVE_MAGIC))
        return header == ARCHIVE_MAGIC
    except OSError:
        return False


def encrypt_file(src: Path, dst: Path, cabinet_id: str) -> None:
    """Chiffre src → dst (overwrite). En mode disabled, copie simple.

    Idempotent : si dst existe et est déjà chiffré, on l'écrase quand même
    avec une nouvelle version (par sécurité, pas de skip).
    """
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if is_encryption_disabled():
        dst.write_bytes(src.read_bytes())
        return

    key = ensure_master_key(cabinet_id)
    raw = src.read_bytes()
    token = encrypt_bytes(raw, key)
    blob = _wrap_file_format(token)
    dst.write_bytes(blob)


def decrypt_file_to_bytes(src: Path, cabinet_id: str) -> bytes:
    """Déchiffre src et retourne les bytes en mémoire (streaming pipeline)."""
    src = Path(src)
    blob = src.read_bytes()

    if is_encryption_disabled():
        return blob

    # Si le fichier n'a pas le magic, on suppose qu'il est clair (back-compat)
    if not blob.startswith(ARCHIVE_MAGIC):
        return blob

    token = _unwrap_file_format(blob)
    key = get_master_key(cabinet_id)
    return decrypt_bytes(token, key)


def decrypt_file_to_path(src: Path, dst: Path, cabinet_id: str) -> None:
    """Déchiffre src → dst."""
    raw = decrypt_file_to_bytes(src, cabinet_id)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(raw)


# --- Key rotation ------------------------------------------------------------


@dataclass
class RotationResult:
    cabinet_id: str
    files_re_encrypted: int
    files_skipped_already_plain: int
    errors: list[str]


def rotate_key_and_re_encrypt(
    cabinet_id: str,
    archive_root: Path,
    new_key: MasterKey | None = None,
) -> RotationResult:
    """Génère une nouvelle clé, re-chiffre tous les .enc du dossier archive.

    Args:
        cabinet_id: cabinet ciblé.
        archive_root: dossier `data/archive/<cabinet>/` (récursif).
        new_key: clé nouvelle imposée (utile pour tests). Sinon générée.

    Returns:
        RotationResult avec compteurs + erreurs.
    """
    old_key = get_master_key(cabinet_id)
    if new_key is None:
        new_key = MasterKey.generate(cabinet_id)

    result = RotationResult(
        cabinet_id=cabinet_id, files_re_encrypted=0,
        files_skipped_already_plain=0, errors=[],
    )

    for path in archive_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            blob = path.read_bytes()
        except OSError as exc:
            result.errors.append(f"{path}: {exc}")
            continue

        if not blob.startswith(ARCHIVE_MAGIC):
            result.files_skipped_already_plain += 1
            continue

        try:
            token = _unwrap_file_format(blob)
            raw = decrypt_bytes(token, old_key)
            new_token = encrypt_bytes(raw, new_key)
            path.write_bytes(_wrap_file_format(new_token))
            result.files_re_encrypted += 1
        except EncryptionError as exc:
            result.errors.append(f"{path}: {exc}")

    if not result.errors:
        # Persiste la nouvelle clé en Keychain (remplace l'ancienne)
        _try_keyring_set(cabinet_id, new_key.value)

    return result
