#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required to run this script." >&2
    exit 1
fi
exec uv run python scripts/seed.py "$@"
