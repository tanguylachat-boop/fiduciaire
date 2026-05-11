"""Chargement des secrets (PAT Bexio, IMAP credentials, clés futures) avec
fallback chain.

Ordre de résolution (premier hit gagne) :
  1. Keychain macOS (recommandé en prod) — service `fiduciaire`, user paramétrable
  2. Variable d'environnement (chargée depuis `.env` si python-dotenv dispo)
  3. RuntimeError explicite

Aucune valeur secrète n'est jamais loggée — uniquement la SOURCE résolue (debug).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

_log = logging.getLogger("fiduciaire.secrets")

KEYRING_SERVICE = "fiduciaire"
BEXIO_PAT_KEYRING_USER_DEFAULT = "bexio-pat-pilote-dev"
BEXIO_PAT_ENV_VAR = "BEXIO_PAT"


@dataclass
class ImapCredentials:
    """Credentials IMAP pour un cabinet. Cf imap_client.ImapCredentials.

    NB: une dataclass identique existe aussi dans `imap_client` pour éviter
    une dépendance circulaire (`secrets` est utilisé par scripts CLI très
    tôt dans l'init). Les deux types ont les mêmes champs.
    """
    host: str
    port: int
    user: str
    password: str
    use_tls: bool = True


def _load_dotenv_if_available() -> None:
    """Charge le `.env` racine si python-dotenv est installé. No-op sinon."""
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
    except ImportError:
        return
    # find_dotenv() remonte l'arborescence depuis cwd ; suffisant pour worker + scripts.
    load_dotenv()


def _try_keyring(service: str, username: str) -> str | None:
    """Essaie de lire le secret depuis Keychain. Renvoie None si indispo ou vide."""
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        value = keyring.get_password(service, username)
    except Exception as e:  # backend pas configuré, accès refusé, etc.
        _log.debug("keyring lookup failed for %s/%s: %s", service, username, type(e).__name__)
        return None
    return value or None


def get_bexio_pat(
    keyring_user: str = BEXIO_PAT_KEYRING_USER_DEFAULT,
    env_var: str = BEXIO_PAT_ENV_VAR,
) -> str:
    """Renvoie le PAT Bexio depuis (1) Keychain → (2) .env / env var → (3) raise.

    Args:
        keyring_user: nom d'utilisateur Keychain (défaut: bexio-pat-pilote-dev)
        env_var: nom de la variable d'env fallback (défaut: BEXIO_PAT)

    Returns:
        PAT Bexio en clair. Ne pas logger, ne pas commiter.

    Raises:
        RuntimeError: aucune source ne fournit de valeur non-vide.
    """
    pat = _try_keyring(KEYRING_SERVICE, keyring_user)
    if pat:
        _log.debug("PAT Bexio: source=keychain user=%s", keyring_user)
        return pat

    _load_dotenv_if_available()
    pat = os.getenv(env_var)
    if pat:
        _log.debug("PAT Bexio: source=env_var name=%s", env_var)
        return pat

    raise RuntimeError(
        "PAT Bexio introuvable. Sources tentées (dans l'ordre) :\n"
        f"  1. Keychain macOS service='{KEYRING_SERVICE}' user='{keyring_user}'\n"
        f"  2. Variable d'environnement {env_var} (chargée depuis .env si python-dotenv installé)\n"
        "Pour stocker dans Keychain :\n"
        f"  python -c \"import keyring; keyring.set_password('{KEYRING_SERVICE}', "
        f"'{keyring_user}', '<PAT>')\"\n"
        "Ou créer un .env à la racine du repo avec :\n"
        f"  {env_var}=<PAT>"
    )


# --- IMAP credentials (Sprint 1 §3.1) ----------------------------------------


def _normalize_cabinet_for_env(cabinet_id: str) -> str:
    """`pilote-jura-01` → `PILOTE_JURA_01` (compatible env var names)."""
    return cabinet_id.replace("-", "_").replace(".", "_").upper()


def _resolve_imap_field(
    cabinet_id: str,
    field: str,
    default: str | int | None = None,
) -> str | int | None:
    """Cherche un champ IMAP dans Keychain puis env var. Pour champs
    non-sensibles (host, port, user), le `default` (depuis config.yaml)
    est utilisé en dernier recours."""
    keyring_user = f"imap-{cabinet_id}-{field}"
    env_var = f"IMAP_{field.upper()}_{_normalize_cabinet_for_env(cabinet_id)}"

    val = _try_keyring(KEYRING_SERVICE, keyring_user)
    if val:
        return val
    val = os.getenv(env_var)
    if val:
        return val
    return default


def get_imap_credentials(
    cabinet_id: str,
    host: str | None = None,
    port: int = 993,
    user: str | None = None,
) -> ImapCredentials:
    """Renvoie les credentials IMAP d'un cabinet.

    Le `password` est OBLIGATOIRE (Keychain → env var → raise). Les
    autres champs (host, port, user) peuvent venir du Keychain/env
    mais retombent sur les arguments passés (typiquement remplis
    depuis `config/clients/<cabinet>.yaml` par l'orchestrateur).

    Args:
        cabinet_id: ID unique du cabinet (ex. "pilote-jura-01").
        host: serveur IMAP par défaut (depuis config).
        port: port TLS par défaut (993).
        user: user IMAP par défaut.

    Returns:
        ImapCredentials avec tous les champs résolus.

    Raises:
        RuntimeError: si password introuvable dans Keychain ni env var.
    """
    _load_dotenv_if_available()

    resolved_host = _resolve_imap_field(cabinet_id, "host", host)
    resolved_port_raw = _resolve_imap_field(cabinet_id, "port", port)
    resolved_user = _resolve_imap_field(cabinet_id, "user", user)
    resolved_password = _resolve_imap_field(cabinet_id, "password", None)

    if not resolved_password:
        env_var = f"IMAP_PASSWORD_{_normalize_cabinet_for_env(cabinet_id)}"
        keyring_user = f"imap-{cabinet_id}-password"
        raise RuntimeError(
            f"IMAP password introuvable pour cabinet={cabinet_id}. "
            "Sources tentées (dans l'ordre) :\n"
            f"  1. Keychain macOS service='{KEYRING_SERVICE}' user='{keyring_user}'\n"
            f"  2. Variable d'environnement {env_var} "
            "(chargée depuis .env si python-dotenv installé)\n"
            "Pour stocker dans Keychain :\n"
            f"  python -c \"import keyring; keyring.set_password("
            f"'{KEYRING_SERVICE}', '{keyring_user}', '<password>')\""
        )

    if not resolved_host:
        raise RuntimeError(
            f"IMAP host introuvable pour cabinet={cabinet_id}. "
            "Passer --host ou définir IMAP_HOST_<CABINET> dans .env."
        )
    if not resolved_user:
        raise RuntimeError(
            f"IMAP user introuvable pour cabinet={cabinet_id}. "
            "Passer --user ou définir IMAP_USER_<CABINET> dans .env."
        )

    try:
        resolved_port = int(resolved_port_raw) if resolved_port_raw else port
    except (ValueError, TypeError):
        resolved_port = port

    _log.debug(
        "IMAP creds: cabinet=%s host=%s port=%d user=%s "
        "password_source=resolved",
        cabinet_id, resolved_host, resolved_port, resolved_user,
    )

    return ImapCredentials(
        host=str(resolved_host),
        port=int(resolved_port),
        user=str(resolved_user),
        password=str(resolved_password),
        use_tls=True,
    )
