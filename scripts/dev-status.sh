#!/usr/bin/env bash
set -euo pipefail

PORTS=(3000 3001 8000 8001)

echo "Listening processes on 3000/3001/8000/8001:"

if command -v netstat.exe >/dev/null 2>&1; then
  netstat.exe -ano |
    tr -d '\r' |
    awk '
      $4 == "LISTENING" {
        split($2, parts, ":");
        port = parts[length(parts)];
        if (port == "3000" || port == "3001" || port == "8000" || port == "8001") {
          print $0
        }
      }
    '
elif command -v lsof >/dev/null 2>&1; then
  for port in "${PORTS[@]}"; do
    lsof -nP -iTCP:"$port" -sTCP:LISTEN || true
  done
else
  echo "Neither netstat.exe nor lsof is available."
  exit 1
fi
