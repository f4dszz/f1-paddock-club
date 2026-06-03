#!/usr/bin/env bash
set -euo pipefail

# Local gate — kept equivalent to .github/workflows/ci.yml so a clean local run
# predicts a green CI run. Each numbered step mirrors a CI step. Tools that are
# CI-managed (ruff/mypy/coverage/gitleaks) degrade gracefully if absent locally
# so the script is still useful on a bare checkout, but CI installs them so they
# are always enforced there.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$("$ROOT_DIR/scripts/python-bin.sh" "$ROOT_DIR")"
PYCACHE_DIR="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/f1-paddock-club-pycache}"
COVERAGE_FLOOR="${COVERAGE_FLOOR:-55}"

if ! "$PYTHON_BIN" -c "import fastapi, langgraph" >/dev/null 2>&1; then
  echo "Backend dependencies are missing for $PYTHON_BIN." >&2
  echo "Run: cd backend && $PYTHON_BIN -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

have_module() { "$PYTHON_BIN" -c "import $1" >/dev/null 2>&1; }

echo "[1/12] Agent guideline sync"
"$ROOT_DIR/scripts/check-agent-doc-sync.sh"

echo "[2/12] Backend compile"
PYTHONPYCACHEPREFIX="$PYCACHE_DIR" "$PYTHON_BIN" -m compileall -q "$ROOT_DIR/backend"

echo "[3/12] Backend lint (ruff)"
if have_module ruff; then
  ( cd "$ROOT_DIR" && "$PYTHON_BIN" -m ruff check backend )
else
  echo "  ruff not installed — skipping (CI enforces it). Install: pip install -r backend/requirements-dev.txt" >&2
fi

echo "[4/12] Backend type-check (mypy)"
if have_module mypy; then
  ( cd "$ROOT_DIR" && "$PYTHON_BIN" -m mypy backend )
else
  echo "  mypy not installed — skipping (CI enforces it). Install: pip install -r backend/requirements-dev.txt" >&2
fi

echo "[5/12] Backend unit tests${COVERAGE_FLOOR:+ (coverage floor ${COVERAGE_FLOOR}%)}"
if have_module coverage; then
  ( cd "$ROOT_DIR/backend" \
    && PYTHONPYCACHEPREFIX="$PYCACHE_DIR" "$PYTHON_BIN" -m coverage run -m unittest discover -s tests -v \
    && "$PYTHON_BIN" -m coverage report --fail-under="$COVERAGE_FLOOR" )
else
  echo "  coverage not installed — running plain unittest (CI enforces the floor)." >&2
  PYTHONPYCACHEPREFIX="$PYCACHE_DIR" "$PYTHON_BIN" -m unittest discover -s "$ROOT_DIR/backend/tests" -v
fi

echo "[6/12] DB migration smoke (alembic up/check/down against throwaway SQLite)"
# Mirror the CI Postgres migrations job at the level a laptop can run cheaply:
# point alembic at a throwaway SQLite file and prove upgrade head -> check ->
# downgrade base all succeed, so a broken/drifting migration is caught locally.
MIGRATE_DB="$(mktemp -t f1pc-migrate.XXXXXX.sqlite3)"
trap 'rm -f "$MIGRATE_DB"' EXIT
(
  cd "$ROOT_DIR/backend"
  # Use TEST_DATABASE_URL so we never touch the developer's real DATABASE_URL/dev DB.
  export TEST_DATABASE_URL="sqlite:///$MIGRATE_DB"
  "$PYTHON_BIN" -m alembic upgrade head
  # alembic check is Postgres/SQLite-agnostic for our single init migration; a
  # non-empty diff means models drifted from migrations.
  "$PYTHON_BIN" -m alembic check
  "$PYTHON_BIN" -m alembic downgrade base
)

echo "[7/12] URL normalizer skill tests"
"$PYTHON_BIN" "$ROOT_DIR/skills/url-normalizer/scripts/test_normalize.py"

echo "[8/12] Secret scan (gitleaks)"
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --no-banner --redact --config "$ROOT_DIR/.gitleaks.toml" --source "$ROOT_DIR"
else
  echo "  gitleaks not installed — skipping (CI enforces it via gitleaks-action)." >&2
  echo "  Install: https://github.com/gitleaks/gitleaks#installing" >&2
fi

echo "[9/12] Frontend clean install"
cd "$ROOT_DIR/frontend"
npm ci

echo "[10/12] Frontend lint + unit tests"
npm run lint
npm test

echo "[11/12] Frontend build"
npm run build

echo "[12/12] Frontend dependency audit"
npm audit --audit-level=moderate
