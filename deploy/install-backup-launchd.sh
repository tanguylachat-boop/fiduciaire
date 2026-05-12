#!/bin/bash
# Installe le LaunchAgent backup quotidien fiduciaire.
#
# Usage : ./deploy/install-backup-launchd.sh
#
# Le plist install dans ~/Library/LaunchAgents/ et active le schedule 03:00.

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/fiduciaire}"
VENV_PYTHON="${VENV_PYTHON:-$REPO_ROOT/worker/.venv/bin/python}"
USER_NAME="${USER}"
PLIST_DEST="$HOME/Library/LaunchAgents/com.lxstudio.fiduciaire.backup.plist"
LOG_DIR="$HOME/Library/Logs/fiduciaire"
BACKUP_DIR="$REPO_ROOT/data/backups"

[[ -d "$REPO_ROOT" ]] || { echo "✗ REPO_ROOT introuvable : $REPO_ROOT" >&2; exit 2; }
[[ -x "$VENV_PYTHON" ]] || { echo "✗ venv Python introuvable : $VENV_PYTHON" >&2; exit 2; }
[[ -f "$REPO_ROOT/deploy/backup.plist.template" ]] || \
    { echo "✗ template introuvable" >&2; exit 2; }

mkdir -p "$LOG_DIR" "$BACKUP_DIR" "$(dirname "$PLIST_DEST")"

sed \
    -e "s|@@REPO_ROOT@@|${REPO_ROOT}|g" \
    -e "s|@@VENV_PYTHON@@|${VENV_PYTHON}|g" \
    -e "s|@@USER@@|${USER_NAME}|g" \
    "$REPO_ROOT/deploy/backup.plist.template" > "$PLIST_DEST"

echo "✓ plist installé : $PLIST_DEST"

launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "✓ launchd loaded : com.lxstudio.fiduciaire.backup"
echo ""
echo "Schedule : tous les jours à 03:00"
echo "Diagnostic :"
echo "  launchctl list | grep fiduciaire.backup"
echo "  tail -f $LOG_DIR/backup.log"
echo ""
echo "Backup manuel : $REPO_ROOT/worker/.venv/bin/python $REPO_ROOT/worker/scripts/backup_now.py --verify"
echo ""
echo "Stop : launchctl unload $PLIST_DEST"
