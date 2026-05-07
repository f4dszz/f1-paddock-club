#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8001}"
PYTHON_BIN="$("$ROOT_DIR/scripts/python-bin.sh" "$ROOT_DIR")"

cd "$ROOT_DIR/backend"
if ! "$PYTHON_BIN" -c "import uvicorn" >/dev/null 2>&1; then
  echo "Backend dependencies are missing for $PYTHON_BIN." >&2
  echo "Run: cd backend && $PYTHON_BIN -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi
exec "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port "$BACKEND_PORT"
