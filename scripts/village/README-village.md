# AI Village — runbook

## Simplified topology

The original setup required 4+ Python services (MCP router, Yellow Pages MCP,
Town Hall MCP, Orchestrator) and 4+ AXL node processes.  This has been
**simplified to 1 Python container + host-managed AXL nodes**:

| Before | After |
|--------|-------|
| MCP Router (port 9003) | **Eliminated** — citizens use `--mcp-http-url` |
| Yellow Pages MCP (9105) | **Kept** — runs in Docker |
| Town Hall MCP (9106) | **Eliminated** — optional audit, orchestrator writes snapshots |
| Orchestrator (9200) | **Kept** — runs in Docker |
| AXL nodes (4 processes) | **Kept** — spawned on host by `run_simulation.py` |

**Result:** one Docker container with 2 Python processes (Yellow Pages +
Orchestrator). AXL nodes are spawned on the host as before.

---

## Quick start (recommended)

```bash
# One command — starts Docker infra, waits for health, runs simulation
./launch_village.sh

# Just the simple standalone simulation (no Docker, no AXL)
./launch_village.sh --simple
```

Or step by step:

```bash
# 1. Start infrastructure (Yellow Pages + Orchestrator)
docker compose up -d

# 2. Verify both are healthy
curl http://localhost:9200/v1/health
curl -sS -X POST http://localhost:9105/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"0.1"}},"id":0}'

# 3. Run simulation (spawns AXL nodes + citizens on host)
python scripts/village/run_simulation.py --config scripts/village/simulation.example.json

# 4. Run again with different parameters (infrastructure stays up)
python scripts/village/run_simulation.py --config scripts/village/simulation2.json

# 5. Stop infrastructure
docker compose down
```

---

## What changed & why

| Change | Reason |
|--------|--------|
| **MCP Router removed** | `citizen.py` has `--mcp-http-url` for direct HTTP to Yellow Pages; no AXL bridge MCP routing needed |
| **Town Hall MCP removed** | It's an optional audit log; orchestrator writes snapshot JSON files directly |
| **Yellow Pages + Orchestrator combined in one container** | Both are Python, same dependencies, run side-by-side |
| **AXL nodes stay on host** | `run_simulation.py` already manages them as subprocesses; containerizing would require refactoring |
| **`town_hall.py` now accepts `--mcp-http-url`** | Same direct-HTTP pattern as `citizen.py`, bypasses AXL bridge MCP routing |
| **`mcp_router.py` accepts `--host`** | Enables `0.0.0.0` binding for Docker (backward compatible) |

---

## Starting a new simulation

The infrastructure (Yellow Pages + Orchestrator) is **persistent** across runs.
To start a new simulation:

```bash
# Just run the simulation driver again with a different config
python scripts/village/run_simulation.py --config scripts/village/simulation2.json
```

To **reset all state** (orchestrator is in-memory):

```bash
docker compose restart
```

---

## Docker Compose reference

```bash
docker compose up -d            # Start infra in background
docker compose logs -f          # Tail logs
docker compose restart          # Restart (clears in-memory orchestrator state)
docker compose down             # Stop and remove
```

The compose file exposes:

| Port | Service |
|------|---------|
| 9105 | Yellow Pages MCP (direct HTTP) |
| 9200 | Orchestrator HTTP API |

---

## Port matrix (current)

| Service | Port | Runs in |
|---------|------|---------|
| Yellow Pages MCP | 9105 | Docker |
| Orchestrator | 9200 | Docker |
| Yellow Pages AXL node | 9002 | Host (by `run_simulation.py`) |
| Town hall AXL node | 9004 | Host |
| Citizen A AXL node | 9012 | Host |
| Citizen B AXL node | 9013 | Host |

---

## Artifacts

- **Orchestrator** writes `scripts/village/runs/<run_id>/manifest.json`,
  `snapshot_epoch_*.json`, and `gini_timeseries.json`.

---

## Tests

```bash
python3 -m unittest discover -s tests -p "test_village_fiscal.py" -v
```
