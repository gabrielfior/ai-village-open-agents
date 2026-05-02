#!/usr/bin/env bash
# One-command village launcher.
# Usage:
#   ./launch_village.sh                                    # default (mesh + 6 epochs)
#   ./launch_village.sh --epochs 10 --actions-per-epoch 8  # custom params
#   ./launch_village.sh down                               # stop everything
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ "${1:-}" = "down" ]; then
  docker compose --profile mesh down
  exit 0
fi

# Start Docker infra + mesh
echo "[launcher] Starting village infrastructure + AXL mesh…"
docker compose --profile mesh up -d

# Wait for mesh readiness
echo "[launcher] Waiting for mesh…"
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
