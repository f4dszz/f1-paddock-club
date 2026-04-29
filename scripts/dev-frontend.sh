#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

cd "$ROOT_DIR/frontend"
exec npm run dev -- --host localhost --port "$FRONTEND_PORT" --strictPort
