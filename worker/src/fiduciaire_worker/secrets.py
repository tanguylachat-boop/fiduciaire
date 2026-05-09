"""Chargement des secrets (PAT Bexio, clés futures) avec fallback chain.

Ordre de résolution (premier hit gagne) :
  1. Keychain macOS (recommandé en prod) — service `fiduciaire`, user paramétrable
  2. Variable d'environnement (chargée depuis `.env` si python-dotenv dispo)
  3. RuntimeError explicite

Aucune valeur secrète n'est jamais loggée — uniquement la SOURCE résolue (debug).
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger("fiduciaire.secrets")

KEYRING_SERVICE = "fiduciaire"
BEXIO_PAT_KEYRING_USER_DEFAULT = "bexio-pat-pilote-dev"
BEXIO_PAT_ENV_VAR = "BEXIO_PAT"


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
