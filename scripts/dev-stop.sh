#!/usr/bin/env bash
set -euo pipefail

PORTS=(3000 3001 8000 8001)

find_pids_for_port() {
  local port="$1"
  if command -v netstat.exe >/dev/null 2>&1; then
    netstat.exe -ano |
      tr -d '\r' |
      awk -v target=":${port}" '$2 ~ target && $4 == "LISTENING" { print $5 }' |
      sort -u
  elif command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
  fi
}

kill_pid() {
  local pid="$1"
  if command -v taskkill.exe >/dev/null 2>&1; then
    taskkill.exe //PID "$pid" //T //F >/dev/null
  else
    kill "$pid" >/dev/null 2>&1 || true
  fi
}

stopped=0
for port in "${PORTS[@]}"; do
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    echo "Stopping PID $pid on port $port"
    kill_pid "$pid"
    stopped=1
  done < <(find_pids_for_port "$port")
done

if [[ "$stopped" -eq 0 ]]; then
  echo "No listeners found on ports: ${PORTS[*]}"
fi
