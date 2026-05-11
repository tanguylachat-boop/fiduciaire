"""Tests pour `secrets.get_imap_credentials` (Sprint 1 §3.1).

Pattern aligné avec test_secrets.py / get_bexio_pat :
1. Keychain → .env → raise pour le password (obligatoire)
2. Host / port / user : Keychain / .env fallback, ou défauts si fournis
   par l'orchestrateur depuis le config cabinet.
"""

from __future__ import annotations

import sys
import types

import pytest

from fiduciaire_worker import secrets as sec


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Évite la fuite des vraies vars d'env dev dans les tests."""
    for varname in (
        "IMAP_PASSWORD_PILOTE_JURA_01",
        "IMAP_PASSWORD_TEST_CABINET",
        "IMAP_HOST_PILOTE_JURA_01",
        "IMAP_PORT_PILOTE_JURA_01",
        "IMAP_USER_PILOTE_JURA_01",
    ):
        monkeypatch.delenv(varname, raising=False)
    monkeypatch.setattr(sec, "_load_dotenv_if_available", lambda: None)
    yield


def _install_fake_keyring(monkeypatch, values: dict[str, str] | None = None):
    """Installe un keyring factice. `values` : map user_key → password."""
    values = values or {}
    fake = types.SimpleNamespace()

    def _get_password(service: str, username: str):
        return values.get(username)

    fake.get_password = _get_password
    monkeypatch.setitem(sys.modules, "keyring", fake)


# --- Tests password obligatoire -----------------------------------------------


def test_imap_password_from_keychain_wins(monkeypatch):
    _install_fake_keyring(
        monkeypatch,
        {"imap-pilote-jura-01-password": "FROM_KC"},
    )
    monkeypatch.setenv("IMAP_PASSWORD_PILOTE_JURA_01", "FROM_ENV")
    creds = sec.get_imap_credentials(
        "pilote-jura-01",
        host="imap.example.ch", user="alice@example.ch",
    )
    assert creds.password == "FROM_KC"


def test_imap_password_fallback_to_env(monkeypatch):
    _install_fake_keyring(monkeypatch, {})  # keychain vide
    monkeypatch.setenv("IMAP_PASSWORD_PILOTE_JURA_01", "ENV_PWD")
    creds = sec.get_imap_credentials(
        "pilote-jura-01",
        host="imap.example.ch", user="alice@example.ch",
    )
    assert creds.password == "ENV_PWD"


def test_imap_password_missing_raises_explicit(monkeypatch):
    _install_fake_keyring(monkeypatch, {})
    with pytest.raises(RuntimeError, match=r"IMAP password introuvable"):
        sec.get_imap_credentials(
            "pilote-jura-01",
            host="imap.example.ch", user="alice@example.ch",
        )


def test_imap_password_never_in_error_message(monkeypatch):
    """Si raise, le message ne doit jamais contenir une valeur secrète."""
    _install_fake_keyring(monkeypatch, {})
    try:
        sec.get_imap_credentials(
            "pilote-jura-01", host="imap.ex.ch", user="a@b.ch",
        )
    except RuntimeError as exc:
        msg = str(exc)
        # Le message doit mentionner les sources, pas une valeur
        assert "Keychain" in msg
        assert "IMAP_PASSWORD" in msg
        # Sanity : ne contient pas de valeur factice évidente
        assert "secret" not in msg.lower() or "<" in msg  # ok if "<password>" template


# --- Tests host/port/user fallback --------------------------------------------


def test_host_port_user_from_args_when_no_override(monkeypatch):
    _install_fake_keyring(
        monkeypatch,
        {"imap-pilote-jura-01-password": "p"},
    )
    creds = sec.get_imap_credentials(
        "pilote-jura-01",
        host="imap.infomaniak.ch",
        port=993,
        user="factures@cabinet.ch",
    )
    assert creds.host == "imap.infomaniak.ch"
    assert creds.port == 993
    assert creds.user == "factures@cabinet.ch"


def test_host_can_be_overridden_via_env(monkeypatch):
    _install_fake_keyring(
        monkeypatch,
        {"imap-pilote-jura-01-password": "p"},
    )
    monkeypatch.setenv("IMAP_HOST_PILOTE_JURA_01", "override.example.ch")
    creds = sec.get_imap_credentials(
        "pilote-jura-01",
        host="imap.default.ch",  # défaut config
        user="a@b.ch",
    )
    assert creds.host == "override.example.ch"


def test_port_from_env_parsed_to_int(monkeypatch):
    _install_fake_keyring(
        monkeypatch,
        {"imap-pilote-jura-01-password": "p"},
    )
    monkeypatch.setenv("IMAP_PORT_PILOTE_JURA_01", "993")
    creds = sec.get_imap_credentials(
        "pilote-jura-01", host="h", user="u",
    )
    assert creds.port == 993
    assert isinstance(creds.port, int)


def test_cabinet_id_namespacing(monkeypatch):
    """2 cabinets → clés Keychain différentes, isolation."""
    _install_fake_keyring(monkeypatch, {
        "imap-pilote-jura-01-password": "PWD_JURA",
        "imap-test-cabinet-password": "PWD_TEST",
    })
    c1 = sec.get_imap_credentials("pilote-jura-01", host="h", user="u")
    c2 = sec.get_imap_credentials("test-cabinet", host="h", user="u")
    assert c1.password == "PWD_JURA"
    assert c2.password == "PWD_TEST"


def test_cabinet_id_normalization_in_env_var(monkeypatch):
    """cabinet-id avec dash → ENV_VAR avec underscore et uppercase."""
    _install_fake_keyring(monkeypatch, {})
    monkeypatch.setenv("IMAP_PASSWORD_PILOTE_JURA_01", "via-env")
    creds = sec.get_imap_credentials(
        "pilote-jura-01", host="h", user="u",
    )
    assert creds.password == "via-env"


def test_password_value_never_in_logs(monkeypatch, caplog):
    """Le PAT-style logging ne doit jamais contenir la valeur."""
    _install_fake_keyring(
        monkeypatch,
        {"imap-pilote-jura-01-password": "TOPSECRET"},
    )
    caplog.set_level("DEBUG")
    sec.get_imap_credentials(
        "pilote-jura-01", host="imap.x.ch", user="alice@x.ch",
    )
    full_log = " ".join(r.message for r in caplog.records)
    assert "TOPSECRET" not in full_log


def test_use_tls_default_true(monkeypatch):
    _install_fake_keyring(
        monkeypatch,
        {"imap-pilote-jura-01-password": "p"},
    )
    creds = sec.get_imap_credentials(
        "pilote-jura-01", host="h", user="u",
    )
    assert creds.use_tls is True
