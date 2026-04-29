#!/usr/bin/env bash
# Example launcher (adjust paths and peer IDs for your mesh).
# See README-village.md for full startup order.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts/village:${PYTHONPATH:-}"

ROUTER="${ROUTER:-http://127.0.0.1:9003}"
YP_PEER="${YP_PEER:?set YP_PEER to Yellow Pages node 64-hex public key}"
ORCH="${ORCH:-http://127.0.0.1:9200}"
AUDIT="${AUDIT:-http://127.0.0.1:9106/mcp}"
RUN_ID="${RUN_ID:-demo1}"

echo "Ensure MCP router, yellow_pages_mcp, town_hall_mcp, orchestrator are already running."
echo "Then start town hall on its bridge and citizens on their bridges (not automated here)."
