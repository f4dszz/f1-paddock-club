#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$("$ROOT_DIR/scripts/python-bin.sh" "$ROOT_DIR")"
PYCACHE_DIR="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/f1-paddock-club-pycache}"

if ! "$PYTHON_BIN" -c "import fastapi, langgraph" >/dev/null 2>&1; then
  echo "Backend dependencies are missing for $PYTHON_BIN." >&2
  echo "Run: cd backend && $PYTHON_BIN -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

echo "[1/7] Agent guideline sync"
"$ROOT_DIR/scripts/check-agent-doc-sync.sh"

echo "[2/7] Backend compile"
PYTHONPYCACHEPREFIX="$PYCACHE_DIR" "$PYTHON_BIN" -m compileall -q "$ROOT_DIR/backend"

echo "[3/7] Backend unit tests"
PYTHONPYCACHEPREFIX="$PYCACHE_DIR" "$PYTHON_BIN" -m unittest discover -s "$ROOT_DIR/backend/tests" -v

echo "[4/7] URL normalizer skill tests"
"$PYTHON_BIN" "$ROOT_DIR/skills/url-normalizer/scripts/test_normalize.py"

echo "[5/7] Frontend clean install"
cd "$ROOT_DIR/frontend"
npm ci

echo "[6/7] Frontend build"
npm run build

echo "[7/7] Frontend dependency audit"
npm audit --audit-level=moderate
