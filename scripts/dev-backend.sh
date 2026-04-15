#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8001}"

cd "$ROOT_DIR/backend"
exec python -m uvicorn main:app --host 127.0.0.1 --port "$BACKEND_PORT"
