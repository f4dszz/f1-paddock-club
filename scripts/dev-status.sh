#!/usr/bin/env bash
set -euo pipefail

echo "Listening processes on 3000/3001/8000/8001:"
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
