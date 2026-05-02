#!/usr/bin/env sh
# Start village infrastructure services in one container.
set -e

echo "[infra] Starting Orchestrator (9200) …"

python orchestrator.py \
  --listen-host 0.0.0.0 \
  --listen-port 9200 \
  --runs-dir /app/runs &
ORCH_PID=$!

echo "[infra] Orchestrator pid=$ORCH_PID"

wait $ORCH_PID
