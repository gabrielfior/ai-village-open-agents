# AI Village (multi-node AXL) — runbook

Village **v0** uses: Yellow Pages MCP, **Town Hall MCP** (audit log), **orchestrator** HTTP API, **GossipSub** for policy propagation over AXL, and **citizen** processes using a **random brain** (no LLM).

## Port matrix (example, local demo)

| Service | Port |
|--------|------|
| MCP router | 9003 |
| Yellow Pages FastMCP | 9105 |
| Town Hall audit FastMCP | 9106 |
| Orchestrator | 9200 |
| Yellow Pages AXL node API | 9002 |
| Town hall AXL API | e.g. 9004 |
| Citizen A | 9012 |
| Citizen B | 9013 |

Each process uses its own AXL `node` binary with a distinct PEM and `--api-port`.

## Startup order

1. **MCP router** (from `axl/integrations`):  
   `python -m mcp_routing.mcp_router --port 9003`

2. **Yellow Pages MCP**:  
   `python yellow_pages_mcp.py --listen-port 9105 --roster ./yellow-pages-roster.json --register-router http://127.0.0.1:9003`

3. **Town Hall MCP** (audit / UI):  
   `python town_hall_mcp.py --listen-port 9106 --register-router http://127.0.0.1:9003`

4. **Orchestrator**:  
   `python orchestrator.py --listen-port 9200 --audit-mcp-url http://127.0.0.1:9106/mcp`

   Smoke test (must return JSON with `service: village-orchestrator`):  
   `curl -s http://127.0.0.1:9200/v1/health`

   Probe several ports:  
   `uv run python scripts/village/check_village_ports.py --orchestrator http://127.0.0.1:9200 --bridge http://127.0.0.1:9002`

5. **AXL nodes** — one for Yellow Pages host, one for town hall, one per citizen, each peering into the same mesh (`tls://...` from your setup). Each Yellow Pages node config must set `router_addr` / `router_port` if you call directory over the bridge.

6. **Create run** (after citizens will join, or pre-seed citizen ids):  
   `curl -s -X POST http://127.0.0.1:9200/v1/run/create -H 'Content-Type: application/json' -d '{"run_id":"demo1","max_epochs":3,"actions_per_epoch":5,"initial_balance":100,"citizens":["<peer_a>","<peer_b>"]}'`

7. **Register** mayor + citizens on Yellow Pages (`register_agent` via each node’s bridge — see `agent_register_axl.py` / `citizen.py`).

8. **Start citizens** (each terminal):  
   `python citizen.py --node-binary …/axl/node --pem …/private-a.pem --yellow-pages-peer-id $YP_PEER --peer tls://… --api-port 9012 --orchestrator http://127.0.0.1:9200 --run-id demo1 --seed 1`

9. **Town hall driver** (town hall node’s bridge):  
   `python town_hall.py --bridge http://127.0.0.1:9004 --yellow-pages-peer-id $YP_PEER --orchestrator http://127.0.0.1:9200 --run-id demo1 --max-epochs 3`

## Artifacts

- **Orchestrator** writes `scripts/village/runs/<run_id>/manifest.json` and `snapshot_epoch_*.json`.
- **Town Hall MCP** writes `scripts/village/town-hall-data/<run_id>/events.jsonl` and epoch summaries (query via MCP tools `get_timeline`, `query_actions`).

## Tests

From repo root (stdlib only):

`python3 -m unittest discover -s tests -p "test_village_fiscal.py" -v`

## Notes

- Policy is delivered on Gossip topic `village/<run_id>/policy`.
- Bilateral trades use **raw JSON** envelopes on AXL (`village` / `v1` / `trade_offer` / `trade_accept`).
- UI consumers should read **Town Hall MCP**, not the orchestrator, for citizen-facing timelines.
