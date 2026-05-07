#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! cmp -s "$ROOT_DIR/AGENTS.md" "$ROOT_DIR/CLAUDE.md"; then
  echo "AGENTS.md and CLAUDE.md have drifted." >&2
  echo "Update both files with identical content before pushing." >&2
  exit 1
fi

echo "AGENTS.md and CLAUDE.md are in sync."
