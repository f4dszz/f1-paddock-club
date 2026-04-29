#!/bin/bash
# F1 Paddock Club — Start both backend and frontend
#
# Usage: ./start.sh
# Backend: http://localhost:8001 (API + WebSocket)
# Frontend: http://localhost:3000 (Vite may open a browser tab depending on environment)
#
# Prerequisites:
#   Backend:  pip install -r backend/requirements.txt + .env with API keys
#   Frontend: cd frontend && npm install

set -e

echo "=== F1 Paddock Club ==="
echo ""

# Start backend
echo "[1/2] Starting backend on :8001..."
cd backend
PYTHON_BIN="${PYTHON_BIN:-python}"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi
PYTHONIOENCODING=utf-8 "$PYTHON_BIN" -m uvicorn main:app --reload --port 8001 &
BACKEND_PID=$!
cd ..

# Wait for backend to be ready
echo "      Waiting for backend..."
for i in $(seq 1 15); do
  CURL_AUTH=()
  if [ -n "${DEMO_ACCESS_TOKEN:-}" ]; then
    CURL_AUTH=(-H "Authorization: Bearer ${DEMO_ACCESS_TOKEN}")
  fi
  if curl -s "${CURL_AUTH[@]}" http://localhost:8001/api/calendar > /dev/null 2>&1; then
    echo "      Backend ready."
    break
  fi
  sleep 1
done

# Start frontend
echo "[2/2] Starting frontend on :3000..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "=== Both services running ==="
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both."

# Cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
