"""Tests `fiduciaire_worker.encryption` — Sprint 1 §3.4.

Fernet chiffrement applicatif des fichiers archive. Pas de SQLCipher
(décision : FileVault couvre la DB au repos, cf
docs/decisions/2026-05-12-encryption-strategy.md).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import encryption  # noqa: E402
from fiduciaire_worker.encryption import (  # noqa: E402
    ARCHIVE_MAGIC,
    EncryptionError,
    KeyNotFoundError,
    MasterKey,
    decrypt_bytes,
    decrypt_file_to_bytes,
    decrypt_file_to_path,
    encrypt_bytes,
    encrypt_file,
    is_encrypted_file,
    is_encryption_disabled,
    rotate_key_and_re_encrypt,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Force le mode disabled = OFF + env vars test isolées."""
    monkeypatch.delenv("FIDUCIAIRE_ENCRYPTION_DISABLED", raising=False)
    yield


def _key(cabinet_id: str = "test-cabinet") -> MasterKey:
    return MasterKey.generate(cabinet_id)


# --- Master key --------------------------------------------------------------


def test_master_key_generate_unique() -> None:
    k1 = MasterKey.generate("cab-a")
    k2 = MasterKey.generate("cab-a")
    # Très peu de chances de collision pour 256 bits aléatoires
    assert k1.value != k2.value
    assert len(k1.value) == 44  # base64url(32 bytes)


def test_master_key_uses_fernet() -> None:
    k = MasterKey.generate("x")
    f = k.fernet
    assert f is not None
    raw = b"hello"
    token = f.encrypt(raw)
    assert f.decrypt(token) == raw


# --- Encrypt/decrypt bytes ---------------------------------------------------


def test_encrypt_decrypt_roundtrip() -> None:
    k = _key()
    raw = b"Confidential PDF binary content blob"
    token = encrypt_bytes(raw, k)
    assert token != raw
    decrypted = decrypt_bytes(token, k)
    assert decrypted == raw


def test_decrypt_with_wrong_key_fails() -> None:
    k1 = _key("cab-a")
    k2 = _key("cab-b")
    token = encrypt_bytes(b"secret", k1)
    with pytest.raises(EncryptionError):
        decrypt_bytes(token, k2)


def test_decrypt_corrupted_token_fails() -> None:
    k = _key()
    token = encrypt_bytes(b"x", k)
    # Modifier 1 byte au milieu casse le HMAC
    corrupted = token[:10] + b"!" + token[11:]
    with pytest.raises(EncryptionError):
        decrypt_bytes(corrupted, k)


# --- Encrypt/decrypt files ---------------------------------------------------


def test_encrypt_file_writes_magic_header(tmp_path: Path, monkeypatch) -> None:
    """Le fichier chiffré doit commencer par FID1 + version."""
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_TEST_CABINET",
                       MasterKey.generate("test-cabinet").value.decode())
    src = tmp_path / "plain.pdf"
    dst = tmp_path / "enc.pdf"
    src.write_bytes(b"%PDF-1.4\nblob")

    encrypt_file(src, dst, cabinet_id="test-cabinet")

    blob = dst.read_bytes()
    assert blob[:4] == ARCHIVE_MAGIC
    assert blob[4:8] == b"\x00\x00\x00\x01"
    assert is_encrypted_file(dst) is True
    assert is_encrypted_file(src) is False


def test_encrypt_decrypt_file_roundtrip(tmp_path: Path, monkeypatch) -> None:
    key = MasterKey.generate("test-cab")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_TEST_CAB",
                       key.value.decode())
    src = tmp_path / "plain.pdf"
    dst = tmp_path / "enc.pdf"
    src.write_bytes(b"%PDF-1.4\nsensitive cabinet data")

    encrypt_file(src, dst, cabinet_id="test-cab")

    decrypted = decrypt_file_to_bytes(dst, cabinet_id="test-cab")
    assert decrypted == src.read_bytes()


def test_decrypt_file_to_path(tmp_path: Path, monkeypatch) -> None:
    key = MasterKey.generate("c")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_C", key.value.decode())
    src = tmp_path / "p.bin"
    enc = tmp_path / "e.bin"
    out = tmp_path / "out.bin"
    src.write_bytes(b"data-123")

    encrypt_file(src, enc, cabinet_id="c")
    decrypt_file_to_path(enc, out, cabinet_id="c")

    assert out.read_bytes() == b"data-123"


def test_decrypt_file_with_plain_input_returns_as_is(
    tmp_path: Path, monkeypatch,
) -> None:
    """Back-compat : un fichier sans header FID1 est considéré clair."""
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_C",
                       MasterKey.generate("c").value.decode())
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(b"%PDF-1.4 plain")

    out = decrypt_file_to_bytes(plain, cabinet_id="c")
    assert out == b"%PDF-1.4 plain"


def test_decrypt_invalid_magic_raises(tmp_path: Path, monkeypatch) -> None:
    """Fichier qui commence par FID1 mais avec un payload corrompu → raise."""
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_C",
                       MasterKey.generate("c").value.decode())
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"FID1\x00\x00\x00\x01" + b"not-a-fernet-token")

    with pytest.raises(EncryptionError):
        decrypt_file_to_bytes(bad, cabinet_id="c")


# --- Dev mode disabled -------------------------------------------------------


def test_dev_mode_disables_encryption(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_DISABLED", "true")
    assert is_encryption_disabled() is True

    src = tmp_path / "plain.pdf"
    dst = tmp_path / "enc.pdf"
    src.write_bytes(b"%PDF-1.4")

    # Pas de clé requise en mode disabled
    encrypt_file(src, dst, cabinet_id="any")
    # Le fichier dst n'est PAS chiffré (copie simple)
    assert dst.read_bytes() == b"%PDF-1.4"
    assert not is_encrypted_file(dst)

    # Decrypt en mode disabled retourne tel quel
    assert decrypt_file_to_bytes(dst, cabinet_id="any") == b"%PDF-1.4"


# --- Key resolution ----------------------------------------------------------


def test_get_master_key_from_env_var(monkeypatch) -> None:
    key = MasterKey.generate("env-cab")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_ENV_CAB", key.value.decode())
    loaded = encryption.get_master_key("env-cab")
    assert loaded.value == key.value


def test_get_master_key_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("FIDUCIAIRE_ENCRYPTION_KEY_NONE", raising=False)
    # Mock keyring pour s'assurer qu'il retourne None
    monkeypatch.setattr(encryption, "_try_keyring_get", lambda c: None)
    with pytest.raises(KeyNotFoundError):
        encryption.get_master_key("none-cab")


def test_ensure_master_key_generates_if_absent(monkeypatch) -> None:
    """Si pas de clé existante, ensure_master_key en crée une."""
    monkeypatch.setattr(encryption, "_try_keyring_get", lambda c: None)
    monkeypatch.setattr(encryption, "_try_keyring_set", lambda c, k: True)
    monkeypatch.delenv("FIDUCIAIRE_ENCRYPTION_KEY_NEW_CAB", raising=False)

    key = encryption.ensure_master_key("new-cab")
    assert key.cabinet_id == "new-cab"
    assert len(key.value) == 44


# --- Multi-mandant isolation -------------------------------------------------


def test_multi_mandant_keys_isolated(tmp_path: Path, monkeypatch) -> None:
    """Cabinet A ne peut PAS déchiffrer un fichier de cabinet B."""
    key_a = MasterKey.generate("cab-a")
    key_b = MasterKey.generate("cab-b")
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_CAB_A", key_a.value.decode())
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_CAB_B", key_b.value.decode())

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"cabinet B confidential")

    enc_b = tmp_path / "enc_b.pdf"
    encrypt_file(src, enc_b, cabinet_id="cab-b")

    # Cabinet A tente de déchiffrer → fail
    with pytest.raises(EncryptionError):
        decrypt_file_to_bytes(enc_b, cabinet_id="cab-a")

    # Cabinet B OK
    assert decrypt_file_to_bytes(enc_b, cabinet_id="cab-b") == src.read_bytes()


# --- Rotation key -----------------------------------------------------------


def test_rotate_key_re_encrypts_archive(tmp_path: Path, monkeypatch) -> None:
    cab = "rot-cab"
    old_key = MasterKey.generate(cab)
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_ROT_CAB",
                       old_key.value.decode())
    # Pas de keychain pour ce test → on s'assure que set ne raise pas
    monkeypatch.setattr(encryption, "_try_keyring_set", lambda c, k: True)

    archive = tmp_path / "archive"
    archive.mkdir()
    src1 = archive / "doc1.pdf"
    src2 = archive / "doc2.pdf"
    src1.write_bytes(b"%PDF-1.4 doc1 content")
    src2.write_bytes(b"%PDF-1.4 doc2 content")

    # Chiffre avec l'ancienne clé
    encrypt_file(src1, src1, cabinet_id=cab)
    encrypt_file(src2, src2, cabinet_id=cab)
    assert is_encrypted_file(src1)
    assert is_encrypted_file(src2)

    new_key = MasterKey.generate(cab)
    result = rotate_key_and_re_encrypt(cab, archive, new_key=new_key)
    assert result.files_re_encrypted == 2
    assert result.errors == []

    # Avec la nouvelle clé en env, déchiffrement OK
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_ROT_CAB",
                       new_key.value.decode())
    raw1 = decrypt_file_to_bytes(src1, cabinet_id=cab)
    assert raw1 == b"%PDF-1.4 doc1 content"


def test_rotate_skips_plain_files(tmp_path: Path, monkeypatch) -> None:
    """Les fichiers sans header FID1 ne sont pas touchés par la rotation."""
    cab = "rot2"
    key = MasterKey.generate(cab)
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_ROT2", key.value.decode())
    monkeypatch.setattr(encryption, "_try_keyring_set", lambda c, k: True)

    archive = tmp_path / "a"
    archive.mkdir()
    plain = archive / "plain.pdf"
    plain.write_bytes(b"%PDF-plain")

    new_key = MasterKey.generate(cab)
    result = rotate_key_and_re_encrypt(cab, archive, new_key=new_key)
    assert result.files_re_encrypted == 0
    assert result.files_skipped_already_plain == 1
    # plain.pdf inchangé
    assert plain.read_bytes() == b"%PDF-plain"


# --- Header format -----------------------------------------------------------


def test_is_encrypted_file_detects_magic(tmp_path: Path) -> None:
    enc = tmp_path / "e.bin"
    enc.write_bytes(b"FID1\x00\x00\x00\x01gAAAAAB...")
    assert is_encrypted_file(enc) is True

    plain = tmp_path / "p.bin"
    plain.write_bytes(b"%PDF-1.4")
    assert is_encrypted_file(plain) is False


def test_decrypt_too_short_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_KEY_C",
                       MasterKey.generate("c").value.decode())
    f = tmp_path / "short.bin"
    f.write_bytes(b"FID1")  # < HEADER_LENGTH
    # is_encrypted_file True (commence par FID1) mais decrypt rejette
    with pytest.raises(EncryptionError):
        decrypt_file_to_bytes(f, cabinet_id="c")
