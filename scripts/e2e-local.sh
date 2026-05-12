#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

wait_for_url() {
  local label="$1"
  local url="$2"
  local tries="${3:-30}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$label ready: $url"
      return 0
    fi
    sleep 1
  done
  echo "$label did not become ready: $url" >&2
  return 1
}

APP_ENV=test \
OPENAI_API_KEY="" \
ANTHROPIC_API_KEY="" \
SERPAPI_API_KEY="" \
FIRECRAWL_API_KEY="" \
TAVILY_API_KEY="" \
LLM_STUB_MODE="${LLM_STUB_MODE:-}" \
BACKEND_PORT="$BACKEND_PORT" \
"$ROOT_DIR/scripts/dev-backend.sh" &
BACKEND_PID=$!
wait_for_url "Backend" "http://127.0.0.1:$BACKEND_PORT/api/calendar" 30

FRONTEND_PORT="$FRONTEND_PORT" "$ROOT_DIR/scripts/dev-frontend.sh" &
FRONTEND_PID=$!
wait_for_url "Frontend" "http://localhost:$FRONTEND_PORT/" 30

cd "$ROOT_DIR/frontend"
E2E_BASE_URL="http://localhost:$FRONTEND_PORT" npm run e2e
