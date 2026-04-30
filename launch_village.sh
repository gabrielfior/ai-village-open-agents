#!/usr/bin/env bash
# One-command village launcher.
#
# Usage:
#   ./launch_village.sh                                # default (mesh + 2 epochs)
#   ./launch_village.sh --epochs 5 --actions 8         # custom params
#   ./launch_village.sh --simple                       # simple standalone sim (no Docker)
#   ./launch_village.sh down                           # stop everything
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ "${1:-}" = "down" ]; then
  docker compose --profile mesh down
  exit 0
fi

if [ "${1:-}" = "--simple" ]; then
  echo "[launcher] Running simple standalone simulation (no Docker needed)…"
  exec python3 scripts/village/simple_simulation.py
fi

# Start Docker infra + mesh
echo "[launcher] Starting village infrastructure + mesh…"
docker compose --profile mesh up -d

# Wait for mesh health (all 4 AXL bridges must respond)
echo "[launcher] Waiting for mesh (all 4 bridges)…"
for i in $(seq 1 30); do
  if curl -fsS http://localhost:9012/topology >/dev/null 2>&1 \
     && curl -fsS http://localhost:9013/topology >/dev/null 2>&1; then
    echo "[launcher] Mesh ready"
    break
  fi
  sleep 2
done

# Run simulation
echo "[launcher] Running village simulation…"
exec python3 scripts/village/run_village.py "$@"
