"""Tests pour `fiduciaire_worker.imap_client`.

Facade autour de `imaplib.IMAP4_SSL`. Tests via FakeImap injecté
au constructeur (pas de réseau, pas de TLS, full offline).

Le FakeImap implémente l'interface minimale d'`imaplib.IMAP4_SSL`
utilisée par notre code (login, select, uid, fetch, close, logout).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker.imap_client import (  # noqa: E402
    FetchedMessage,
    ImapAuthError,
    ImapClient,
    ImapCredentials,
    ImapNetworkError,
)


class FakeImap:
    """Faux client imaplib qui implémente l'interface utilisée par ImapClient.

    Permet de simuler login OK/KO, select retournant UIDVALIDITY+EXISTS,
    SEARCH retournant des UIDs, FETCH retournant des bytes RFC822.
    """

    def __init__(
        self,
        host: str,
        port: int = 993,
        login_ok: bool = True,
        uidvalidity: int = 42,
        exists: int = 0,
        uids: list[int] | None = None,
        messages: dict[int, bytes] | None = None,
        timeout: int | None = None,  # ignoré, signature compatible IMAP4_SSL
    ):
        self.host = host
        self.port = port
        self._login_ok = login_ok
        self._uidvalidity = uidvalidity
        self._exists = exists
        self._uids = uids or []
        self._messages = messages or {}
        self.selected_folder: str | None = None
        self.login_called = False
        self.logout_called = False
        self.store_calls: list[tuple[str, str, str]] = []

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        self.login_called = True
        if not self._login_ok:
            import imaplib
            raise imaplib.IMAP4.error(
                b"[AUTHENTICATIONFAILED] Invalid credentials"
            )
        return ("OK", [b"LOGIN completed"])

    def select(self, folder: str = "INBOX", readonly: bool = False) -> tuple[str, list[bytes]]:
        self.selected_folder = folder
        return ("OK", [str(self._exists).encode()])

    def response(self, key: str) -> tuple[str, list[bytes]]:
        """imaplib expose UIDVALIDITY/UIDNEXT via response()."""
        if key.upper() == "UIDVALIDITY":
            return ("OK", [str(self._uidvalidity).encode()])
        return ("OK", [b""])

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        cmd = command.upper()
        if cmd == "SEARCH":
            # arg typique : "UID <last+1>:*" — on simule un retour all-uids
            return ("OK", [b" ".join(str(u).encode() for u in self._uids)])
        if cmd == "FETCH":
            uid_str = args[0]
            try:
                uid = int(uid_str)
            except (ValueError, TypeError):
                return ("NO", [b"invalid uid"])
            if uid not in self._messages:
                return ("OK", [None])
            return (
                "OK",
                [(b"%d (BODY[] {%d}" % (uid, len(self._messages[uid])),
                  self._messages[uid]), b")"],
            )
        if cmd == "STORE":
            uid_str, flags_op, flags = args
            self.store_calls.append((uid_str, flags_op, flags))
            return ("OK", [b""])
        return ("NO", [b"unknown command"])

    def logout(self) -> tuple[str, list[bytes]]:
        self.logout_called = True
        return ("BYE", [b"LOGOUT completed"])


def _fake_factory(login_ok=True, uidvalidity=42, exists=10,
                  uids=None, messages=None):
    def factory(host, port, timeout=None):
        return FakeImap(
            host=host, port=port, login_ok=login_ok,
            uidvalidity=uidvalidity, exists=exists,
            uids=uids if uids is not None else [],
            messages=messages or {},
        )
    return factory


# --- Tests connexion ----------------------------------------------------------


def test_connect_login_success() -> None:
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(login_ok=True),
    )
    client.connect(user="alice", password="s3cret")
    assert client.is_connected()
    client.close()


def test_connect_login_failure_raises_auth_error() -> None:
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(login_ok=False),
    )
    with pytest.raises(ImapAuthError):
        client.connect(user="alice", password="bad-pwd")


def test_connect_rejects_plain_port_143() -> None:
    """TLS obligatoire — port 143 (IMAP plain) doit lever ValueError."""
    with pytest.raises(ValueError, match=r"TLS"):
        ImapClient(
            host="imap.example.com", port=143,
            imap_factory=_fake_factory(),
        )


def test_factory_default_is_imap4_ssl() -> None:
    """Si aucun factory n'est passé, utilise imaplib.IMAP4_SSL."""
    import imaplib
    client = ImapClient(host="imap.example.com", port=993)
    assert client._imap_factory is imaplib.IMAP4_SSL


# --- Tests select_folder / uidvalidity ---------------------------------------


def test_select_folder_returns_uidvalidity_and_exists() -> None:
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(uidvalidity=99, exists=42),
    )
    client.connect("u", "p")
    uidv, exists = client.select_folder("INBOX")
    assert uidv == 99
    assert exists == 42


def test_select_folder_before_connect_raises() -> None:
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(),
    )
    with pytest.raises(RuntimeError, match=r"not connected"):
        client.select_folder("INBOX")


# --- Tests fetch_uids_above ---------------------------------------------------


def test_fetch_uids_above_filters_correctly() -> None:
    """fetch_uids_above(5) → retourne uniquement les uids > 5."""
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(uids=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
    )
    client.connect("u", "p")
    client.select_folder("INBOX")
    result = client.fetch_uids_above(5)
    assert result == [6, 7, 8, 9, 10]


def test_fetch_uids_above_zero_returns_all() -> None:
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(uids=[1, 2, 3]),
    )
    client.connect("u", "p")
    client.select_folder("INBOX")
    assert client.fetch_uids_above(0) == [1, 2, 3]


def test_fetch_uids_above_empty_when_no_new() -> None:
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(uids=[1, 2, 3]),
    )
    client.connect("u", "p")
    client.select_folder("INBOX")
    assert client.fetch_uids_above(10) == []


# --- Tests fetch_message ------------------------------------------------------


def test_fetch_message_returns_bytes() -> None:
    raw = b"From: x@y.com\r\nSubject: test\r\n\r\nBody\r\n"
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(uids=[7], messages={7: raw}),
    )
    client.connect("u", "p")
    client.select_folder("INBOX")
    msg = client.fetch_message(7)
    assert isinstance(msg, FetchedMessage)
    assert msg.uid == 7
    assert msg.raw_bytes == raw


def test_fetch_message_missing_uid_raises() -> None:
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(uids=[1], messages={1: b"x"}),
    )
    client.connect("u", "p")
    client.select_folder("INBOX")
    with pytest.raises(ValueError, match=r"uid"):
        client.fetch_message(999)


# --- Tests mark_seen ----------------------------------------------------------


def test_mark_seen_calls_store() -> None:
    fakeimap_ref: dict[str, Any] = {}

    def factory(host, port, timeout=None):
        fk = FakeImap(host=host, port=port, uids=[1], messages={1: b"x"})
        fakeimap_ref["fk"] = fk
        return fk

    client = ImapClient(
        host="imap.example.com", port=993, imap_factory=factory,
    )
    client.connect("u", "p")
    client.select_folder("INBOX")
    client.mark_seen(1)
    fk = fakeimap_ref["fk"]
    assert len(fk.store_calls) == 1
    assert fk.store_calls[0][0] == "1"
    assert "Seen" in fk.store_calls[0][2]


# --- Tests close --------------------------------------------------------------


def test_close_calls_logout() -> None:
    fakeimap_ref: dict[str, Any] = {}

    def factory(host, port, timeout=None):
        fk = FakeImap(host=host, port=port)
        fakeimap_ref["fk"] = fk
        return fk

    client = ImapClient(
        host="imap.example.com", port=993, imap_factory=factory,
    )
    client.connect("u", "p")
    client.close()
    assert fakeimap_ref["fk"].logout_called is True
    assert client.is_connected() is False


def test_close_when_not_connected_is_safe() -> None:
    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=_fake_factory(),
    )
    # Ne lève pas
    client.close()


# --- Tests retry exp backoff sur erreurs réseau ------------------------------


def test_connect_retries_on_network_error_then_succeeds() -> None:
    """Factory lève 2× puis succède au 3e essai → connect réussit."""
    attempts: list[int] = []

    def flaky_factory(host, port, timeout=None):
        attempts.append(1)
        if len(attempts) < 3:
            import socket
            raise socket.gaierror("temp DNS fail")
        return FakeImap(host=host, port=port)

    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=flaky_factory,
        max_retries=3,
        retry_initial_backoff_s=0.01,  # accélère le test
    )
    # Patch sleep pour zéro attente
    with patch("fiduciaire_worker.imap_client.time.sleep", lambda *_: None):
        client.connect("u", "p")
    assert len(attempts) == 3
    assert client.is_connected()


def test_connect_gives_up_after_max_retries() -> None:
    def always_fail(host, port, timeout=None):
        import socket
        raise socket.gaierror("permanent DNS fail")

    client = ImapClient(
        host="imap.example.com", port=993,
        imap_factory=always_fail,
        max_retries=2,
        retry_initial_backoff_s=0.01,
    )
    with patch("fiduciaire_worker.imap_client.time.sleep", lambda *_: None):
        with pytest.raises(ImapNetworkError):
            client.connect("u", "p")
