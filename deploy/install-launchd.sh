#!/bin/bash
# Installe le LaunchAgent IMAP fetch pour un cabinet.
#
# Usage :
#   ./deploy/install-launchd.sh pilote-jura-01
#
# Pré-requis :
#   - Repo cloné dans $REPO_ROOT (défaut: $HOME/fiduciaire)
#   - venv worker installé (worker/.venv/bin/python)
#   - Credentials IMAP stockées dans Keychain ou .env
#
# Le plist install dans ~/Library/LaunchAgents/ et démarre immédiatement.

set -euo pipefail

CLIENT_ID="${1:-}"
if [[ -z "$CLIENT_ID" ]]; then
    echo "Usage: $0 <client-id>" >&2
    echo "Example: $0 pilote-jura-01" >&2
    exit 1
fi

REPO_ROOT="${REPO_ROOT:-$HOME/fiduciaire}"
VENV_PYTHON="${VENV_PYTHON:-$REPO_ROOT/worker/.venv/bin/python}"
USER_NAME="${USER}"
PLIST_DEST="$HOME/Library/LaunchAgents/com.lxstudio.fiduciaire.imap-${CLIENT_ID}.plist"
LOG_DIR="$HOME/Library/Logs/fiduciaire"
LOCK_DIR="$REPO_ROOT/data/locks"

# Sanity checks
[[ -d "$REPO_ROOT" ]] || { echo "✗ REPO_ROOT introuvable : $REPO_ROOT" >&2; exit 2; }
[[ -x "$VENV_PYTHON" ]] || { echo "✗ venv Python introuvable : $VENV_PYTHON" >&2; exit 2; }
[[ -f "$REPO_ROOT/deploy/imap-fetch.plist.template" ]] || \
    { echo "✗ template introuvable" >&2; exit 2; }

mkdir -p "$LOG_DIR" "$LOCK_DIR" "$(dirname "$PLIST_DEST")"

# Substitution variables
sed \
    -e "s|@@CLIENT_ID@@|${CLIENT_ID}|g" \
    -e "s|@@REPO_ROOT@@|${REPO_ROOT}|g" \
    -e "s|@@VENV_PYTHON@@|${VENV_PYTHON}|g" \
    -e "s|@@USER@@|${USER_NAME}|g" \
    "$REPO_ROOT/deploy/imap-fetch.plist.template" > "$PLIST_DEST"

echo "✓ plist installé : $PLIST_DEST"

# (Re)load
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "✓ launchd loaded : com.lxstudio.fiduciaire.imap-${CLIENT_ID}"
echo ""
echo "Diagnostic :"
echo "  launchctl list | grep fiduciaire"
echo "  tail -f $LOG_DIR/imap-fetch-${CLIENT_ID}.log"
echo "  tail -f $LOG_DIR/imap-fetch-${CLIENT_ID}.err"
echo ""
echo "Stop :"
echo "  launchctl unload $PLIST_DEST"
