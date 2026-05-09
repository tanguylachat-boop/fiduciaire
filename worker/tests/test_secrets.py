"""Tests du fallback chain Keychain → .env → raise pour secrets.get_bexio_pat()."""
from __future__ import annotations

import logging
import sys
import types

import pytest

from fiduciaire_worker import secrets as sec


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Évite que le BEXIO_PAT du dev fuite dans les tests :
    1. Supprime la var d'env en cours
    2. Désactive load_dotenv() pour empêcher un re-load depuis le `.env` du repo
       (qui contient le vrai PAT en dev local).
    """
    monkeypatch.delenv(sec.BEXIO_PAT_ENV_VAR, raising=False)
    monkeypatch.setattr(sec, "_load_dotenv_if_available", lambda: None)
    yield


def _install_fake_keyring(monkeypatch, value: str | None, *, raising: bool = False):
    """Installe un module `keyring` factice dans sys.modules pour le test."""
    fake = types.SimpleNamespace()

    def _get_password(service: str, username: str):
        if raising:
            raise RuntimeError("backend not configured")
        return value

    fake.get_password = _get_password
    monkeypatch.setitem(sys.modules, "keyring", fake)


def test_keychain_hit_wins(monkeypatch):
    _install_fake_keyring(monkeypatch, "FROM_KEYCHAIN")
    monkeypatch.setenv(sec.BEXIO_PAT_ENV_VAR, "FROM_ENV")
    assert sec.get_bexio_pat() == "FROM_KEYCHAIN"


def test_falls_back_to_env_when_keychain_empty(monkeypatch):
    _install_fake_keyring(monkeypatch, None)
    monkeypatch.setenv(sec.BEXIO_PAT_ENV_VAR, "FROM_ENV")
    assert sec.get_bexio_pat() == "FROM_ENV"


def test_falls_back_to_env_when_keychain_module_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setenv(sec.BEXIO_PAT_ENV_VAR, "FROM_ENV")
    # Sans `keyring` importable, la fonction doit lire le .env
    pat = sec.get_bexio_pat()
    assert pat == "FROM_ENV"


def test_falls_back_to_env_when_keychain_raises(monkeypatch):
    _install_fake_keyring(monkeypatch, None, raising=True)
    monkeypatch.setenv(sec.BEXIO_PAT_ENV_VAR, "FROM_ENV")
    assert sec.get_bexio_pat() == "FROM_ENV"


def test_raises_when_nothing_set(monkeypatch):
    _install_fake_keyring(monkeypatch, None)
    with pytest.raises(RuntimeError, match="PAT Bexio introuvable"):
        sec.get_bexio_pat()


def test_pat_value_never_in_logs(monkeypatch, caplog):
    """Le PAT en clair ne doit JAMAIS apparaître dans les logs même en debug."""
    caplog.set_level(logging.DEBUG, logger="fiduciaire.secrets")
    _install_fake_keyring(monkeypatch, "VERYSECRETKEYCHAIN")
    pat = sec.get_bexio_pat()
    assert pat == "VERYSECRETKEYCHAIN"
    full_log = "\n".join(r.getMessage() for r in caplog.records)
    assert "VERYSECRETKEYCHAIN" not in full_log


def test_env_value_never_in_logs(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="fiduciaire.secrets")
    _install_fake_keyring(monkeypatch, None)
    monkeypatch.setenv(sec.BEXIO_PAT_ENV_VAR, "VERYSECRETENV")
    pat = sec.get_bexio_pat()
    assert pat == "VERYSECRETENV"
    full_log = "\n".join(r.getMessage() for r in caplog.records)
    assert "VERYSECRETENV" not in full_log


def test_custom_keyring_user_override(monkeypatch):
    """Permet de paramétrer le username Keychain (multi-cabinets futur)."""
    received = {}

    def _get(service, user):
        received["service"] = service
        received["user"] = user
        return "OK"

    fake = types.SimpleNamespace(get_password=_get)
    monkeypatch.setitem(sys.modules, "keyring", fake)
    sec.get_bexio_pat(keyring_user="bexio-pat-cabinet-jura-prod")
    assert received["service"] == "fiduciaire"
    assert received["user"] == "bexio-pat-cabinet-jura-prod"


def test_custom_env_var_override(monkeypatch):
    _install_fake_keyring(monkeypatch, None)
    monkeypatch.setenv("CUSTOM_PAT_VAR", "FROM_CUSTOM")
    assert sec.get_bexio_pat(env_var="CUSTOM_PAT_VAR") == "FROM_CUSTOM"
