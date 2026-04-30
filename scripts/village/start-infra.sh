#!/usr/bin/env sh
# Start village infrastructure services in one container.
# Uses direct HTTP (no MCP Router) — citizens pass --mcp-http-url.
set -e

echo "[infra] Starting Yellow Pages MCP (9105) + Orchestrator (9200) …"

python yellow_pages_mcp.py \
  --listen-host 0.0.0.0 \
  --listen-port 9105 \
  --roster /app/yellow-pages-roster.json &
YP_PID=$!

python orchestrator.py \
  --listen-host 0.0.0.0 \
  --listen-port 9200 \
  --runs-dir /app/runs &
ORCH_PID=$!

echo "[infra] Yellow Pages pid=$YP_PID  Orchestrator pid=$ORCH_PID"

wait $YP_PID $ORCH_PID
