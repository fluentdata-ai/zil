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

# Ensure uv is available
if ! command -v uv &>/dev/null; then
    echo "Error: uv not found. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "→ Syncing local zil-ai into tmp/ project venvs..."

for venv in "$TMP_DIR"/*/.venv; do
    [ -d "$venv" ] || continue
    project="$(dirname "$venv")"
    name="$(basename "$project")"

    echo "  → $name"
    VIRTUAL_ENV="$venv" uv pip install -e "${REPO_ROOT}[adk,serve,eval]" --quiet 2>&1 || true
    echo "  ✓ $name updated"
done

echo ""
echo "Done. Run 'zil --version' in any tmp/ project to verify."
