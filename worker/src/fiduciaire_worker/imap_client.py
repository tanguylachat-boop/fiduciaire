"""Facade autour de `imaplib.IMAP4_SSL` pour fetcher des mails de manière
testable et résiliente.

Approche : la stdlib `imaplib` reste la dépendance (zéro lib externe),
mais on encapsule l'API verbeuse dans une classe `ImapClient` avec un
factory injectable. Les tests utilisent un FakeImap au lieu d'une vraie
connexion TLS.

Garanties :
- TLS obligatoire (port 993 par défaut, refuse port 143).
- Retry exponentiel backoff sur erreurs réseau (`socket.gaierror`,
  `ConnectionRefusedError`, `TimeoutError`).
- Pas de retry sur erreur d'auth (raise immédiatement).
- Pas de password dans les logs.
- Méthodes idempotentes : `close()` peut être appelée plusieurs fois.

Cf docs/specs/imap-fetch.md §3.4 + §3.5.
"""

from __future__ import annotations

import imaplib
import logging
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable

_log = logging.getLogger("fiduciaire.imap_client")


# --- Exceptions ---------------------------------------------------------------


class ImapError(Exception):
    """Base class IMAP errors."""


class ImapAuthError(ImapError):
    """Login refusé par le serveur."""


class ImapNetworkError(ImapError):
    """Erreur réseau persistante après retries."""


# --- Dataclasses --------------------------------------------------------------


@dataclass
class ImapCredentials:
    host: str
    port: int
    user: str
    password: str
    use_tls: bool = True


@dataclass
class FetchedMessage:
    uid: int
    raw_bytes: bytes
    internal_date: str | None = None


# --- Client ------------------------------------------------------------------


ImapFactory = Callable[..., Any]
"""Signature : factory(host, port, timeout=None) -> imaplib.IMAP4_SSL-like."""


class ImapClient:
    """Facade testable autour d'imaplib.IMAP4_SSL.

    Args:
        host: serveur IMAP (ex. imap.infomaniak.ch)
        port: port TLS (défaut 993). 143 refusé (TLS obligatoire).
        imap_factory: callable qui retourne un IMAP4_SSL-like client.
            Défaut: imaplib.IMAP4_SSL. Override pour les tests.
        max_retries: tentatives max sur erreur réseau (défaut 3).
        retry_initial_backoff_s: backoff initial en secondes (exp ×2).
        timeout_s: timeout socket (défaut 30s).
    """

    def __init__(
        self,
        host: str,
        port: int = 993,
        imap_factory: ImapFactory | None = None,
        max_retries: int = 3,
        retry_initial_backoff_s: float = 1.0,
        timeout_s: int = 30,
    ):
        if port == 143:
            raise ValueError(
                "Port 143 (IMAP plain) refusé. TLS obligatoire — utiliser le port 993."
            )
        self.host = host
        self.port = port
        self._imap_factory = imap_factory or imaplib.IMAP4_SSL
        self._max_retries = max_retries
        self._retry_initial_backoff_s = retry_initial_backoff_s
        self._timeout_s = timeout_s
        self._imap: Any | None = None
        self._selected_folder: str | None = None

    # --- État ---

    def is_connected(self) -> bool:
        return self._imap is not None

    # --- Connect / close ---

    def connect(self, user: str, password: str) -> None:
        """Établit la connexion TLS et fait le login.

        Retry exponentiel sur erreurs réseau (DNS, refused, timeout).
        Pas de retry sur erreur d'auth.

        Raises:
            ImapNetworkError: si épuisement des retries.
            ImapAuthError: si login refusé.
        """
        backoff = self._retry_initial_backoff_s
        attempt = 0
        last_exc: Exception | None = None

        while attempt < self._max_retries:
            attempt += 1
            try:
                imap = self._imap_factory(
                    self.host, self.port, timeout=self._timeout_s
                )
            except (socket.gaierror, ConnectionRefusedError,
                    TimeoutError, OSError) as exc:
                last_exc = exc
                _log.warning(
                    "IMAP connect failed (attempt %d/%d): %s",
                    attempt, self._max_retries, type(exc).__name__,
                )
                if attempt < self._max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                continue

            # Login : pas de retry sur AUTHENTICATIONFAILED
            try:
                imap.login(user, password)
            except imaplib.IMAP4.error as exc:
                msg = str(exc).lower()
                if "auth" in msg or "login" in msg or "credential" in msg:
                    _log.error("IMAP auth failed: %s", type(exc).__name__)
                    raise ImapAuthError(
                        "Authentification IMAP refusée — "
                        "vérifier user/password Keychain ou .env"
                    ) from exc
                # Autre erreur IMAP4.error → retry réseau
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                continue
            except (socket.gaierror, ConnectionRefusedError,
                    TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                continue

            # Succès
            self._imap = imap
            _log.info("IMAP connected to %s:%d as %s", self.host, self.port, user)
            return

        raise ImapNetworkError(
            f"IMAP connect épuisé après {self._max_retries} tentatives: "
            f"{type(last_exc).__name__ if last_exc else 'unknown'}"
        )

    def close(self) -> None:
        """LOGOUT + cleanup. Idempotent."""
        if self._imap is None:
            return
        try:
            self._imap.logout()
        except Exception as exc:  # pragma: no cover — best effort
            _log.warning("IMAP logout failed: %s", exc)
        finally:
            self._imap = None
            self._selected_folder = None

    # --- Operations ---

    def select_folder(self, folder: str = "INBOX") -> tuple[int, int]:
        """SELECT <folder> → (uidvalidity, exists).

        Returns:
            (uidvalidity, exists_count)

        Raises:
            RuntimeError: si non connecté.
        """
        if self._imap is None:
            raise RuntimeError("not connected — appeler connect() d'abord")

        status, exists_data = self._imap.select(folder, readonly=False)
        if status != "OK":
            raise ImapError(f"SELECT {folder} failed: {status}")
        try:
            exists = int(exists_data[0])
        except (ValueError, TypeError, IndexError):
            exists = 0

        uidv_status, uidv_data = self._imap.response("UIDVALIDITY")
        try:
            uidvalidity = int(uidv_data[0]) if uidv_data and uidv_data[0] else 0
        except (ValueError, TypeError):
            uidvalidity = 0

        self._selected_folder = folder
        return uidvalidity, exists

    def fetch_uids_above(self, last_uid: int) -> list[int]:
        """Retourne les UIDs > last_uid dans le folder sélectionné.

        Args:
            last_uid: UID seuil (exclu). Passer 0 pour récupérer tout.

        Returns:
            Liste triée d'UIDs.
        """
        if self._imap is None:
            raise RuntimeError("not connected")
        if self._selected_folder is None:
            raise RuntimeError("aucun folder sélectionné — appeler select_folder()")

        search_arg = f"{last_uid + 1}:*"
        status, data = self._imap.uid("SEARCH", "UID", search_arg)
        if status != "OK":
            raise ImapError(f"UID SEARCH failed: {status}")
        if not data or not data[0]:
            return []
        raw = data[0]
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", errors="ignore")
        try:
            uids = sorted(int(x) for x in raw.split() if x)
        except ValueError:
            return []
        # `<last+1>:*` peut retourner le dernier UID même s'il == last_uid quand
        # la boîte n'a plus de message. Filtre defensive.
        return [u for u in uids if u > last_uid]

    def fetch_message(self, uid: int) -> FetchedMessage:
        """UID FETCH <uid> BODY.PEEK[] → FetchedMessage(raw_bytes).

        Raises:
            ValueError: si UID inconnu.
            ImapError: si la commande échoue.
        """
        if self._imap is None:
            raise RuntimeError("not connected")
        status, data = self._imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if status != "OK":
            raise ImapError(f"UID FETCH {uid} failed: {status}")
        # data peut être [None] si UID inexistant, ou une liste avec
        # le tuple (header_response, payload_bytes)
        if not data or data[0] is None:
            raise ValueError(f"uid {uid} introuvable dans la boîte")
        # Cherche le payload : c'est le 2e élément d'un tuple parmi les items
        payload: bytes | None = None
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                if isinstance(item[1], (bytes, bytearray)):
                    payload = bytes(item[1])
                    break
        if payload is None:
            raise ImapError(f"UID FETCH {uid}: payload introuvable")
        return FetchedMessage(uid=uid, raw_bytes=payload)

    def mark_seen(self, uid: int) -> None:
        """UID STORE <uid> +FLAGS (\\Seen)."""
        if self._imap is None:
            raise RuntimeError("not connected")
        status, _ = self._imap.uid("STORE", str(uid), "+FLAGS", r"(\Seen)")
        if status != "OK":
            raise ImapError(f"UID STORE {uid} failed: {status}")

    # --- Context manager ---

    def __enter__(self) -> "ImapClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
