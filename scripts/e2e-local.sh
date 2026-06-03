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

# saved_trips.spec.js needs a deterministic plan first, which only happens under
# LLM_STUB_MODE=1 (same gate refine/quote_incomplete use). So default the
# saved_trips lane ON only when stub mode is active — this makes a local
# `LLM_STUB_MODE=1 ./scripts/e2e-local.sh` match CI (which sets
# E2E_INCLUDE_SAVED=1 LLM_STUB_MODE=1) without making non-stub runs flaky.
# Override explicitly with E2E_INCLUDE_SAVED=1|0 at any time.
if [[ -z "${E2E_INCLUDE_SAVED:-}" && -n "${LLM_STUB_MODE:-}" ]]; then
  E2E_INCLUDE_SAVED=1
fi
export E2E_INCLUDE_SAVED="${E2E_INCLUDE_SAVED:-0}"

cd "$ROOT_DIR/frontend"
E2E_BASE_URL="http://localhost:$FRONTEND_PORT" npm run e2e
