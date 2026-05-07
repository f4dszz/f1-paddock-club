#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKEND_DIR="$ROOT_DIR/backend"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  if [[ "$PYTHON_BIN" == */* && -x "$PYTHON_BIN" ]]; then
    echo "$PYTHON_BIN"
    exit 0
  fi
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    command -v "$PYTHON_BIN"
    exit 0
  fi
  echo "PYTHON_BIN is set but not executable or on PATH: $PYTHON_BIN" >&2
  exit 1
fi

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  echo "$BACKEND_DIR/.venv/bin/python"
  exit 0
fi

for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    command -v "$candidate"
    exit 0
  fi
done

echo "No usable Python found. Install Python 3.11+ or create backend/.venv." >&2
exit 1
