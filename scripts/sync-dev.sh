#!/usr/bin/env bash
# Reinstall the local zil-ai dev build into all tmp/ project venvs.
# Run from repo root: ./scripts/sync-dev.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR="${REPO_ROOT}/tmp"

if [ ! -d "$TMP_DIR" ]; then
    echo "No tmp/ directory found."
    exit 0
fi

echo "→ Syncing local zil-ai into tmp/ project venvs..."

for venv in "$TMP_DIR"/*/.venv; do
    [ -d "$venv" ] || continue
    project="$(dirname "$venv")"
    name="$(basename "$project")"

    pip_bin="$venv/bin/pip"
    [ -f "$pip_bin" ] || pip_bin="$venv/Scripts/pip.exe"

    if [ ! -f "$pip_bin" ]; then
        echo "  ⚠ $name — no pip found, skipping"
        continue
    fi

    echo "  → $name"
    "$pip_bin" install -e "${REPO_ROOT}[adk,eval]" --quiet 2>&1 | grep -v "already satisfied" || true
    echo "  ✓ $name updated"
done

echo ""
echo "Done. Run 'zil --version' in any tmp/ project to verify."
