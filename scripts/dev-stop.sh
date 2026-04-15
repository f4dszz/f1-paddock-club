#!/usr/bin/env bash
set -euo pipefail

PORTS=(3000 3001 8000 8001)

find_pids_for_port() {
  local port="$1"
  netstat.exe -ano |
    tr -d '\r' |
    awk -v target=":${port}" '$2 ~ target && $4 == "LISTENING" { print $5 }' |
    sort -u
}

stopped=0
for port in "${PORTS[@]}"; do
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    echo "Stopping PID $pid on port $port"
    taskkill.exe //PID "$pid" //T //F >/dev/null
    stopped=1
  done < <(find_pids_for_port "$port")
done

if [[ "$stopped" -eq 0 ]]; then
  echo "No listeners found on ports: ${PORTS[*]}"
fi
