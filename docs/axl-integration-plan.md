# AXL Integration Plan — 3 Phases
## Phase 1 — AXL `send/recv` for trade offers
**Goal:** Replace in-memory `TradeExchange` with actual AXL bridge HTTP calls.
**Files changed:** `scripts/village/run_village.py`
### What changes
| Before (in-memory) | After (AXL bridge) |
|---|---|
| `CitizenAgent` takes `exchange: TradeExchange` | Takes `bridge_url: str` (AXL node HTTP endpoint) |
| `exchange.make_offer(...)` blocks on `threading.Event` | `send_raw(bridge, cp_id, village_msg)` then poll `recv_raw()` with 6s timeout |
| `exchange.incoming_offers(my_id)` reads a dict | Poll `recv_raw(bridge)` loop (like `drain_inbox()` in `citizen.py:495`) |
| `exchange.accept_offer()` sets Event | `send_raw(bridge, initiator_id, trade_accept_msg)` |
| `TradeExchange` class (49 lines) | **Removed** |
| `main()`: `exchange = TradeExchange()` shared across agents | Each agent gets its own `bridge_url`; no shared state |
### Trade message protocol
```python
# Offer (A → B via A's bridge :9012)
{"village": "v1", "msg": "trade_offer", "offer_id": oid,
 "run_id": ..., "from": A_id, "to": B_id,
 "give_resource": "wood", "give_amount": 5,
 "want_resource": "grain", "want_amount": 3, "epoch": N}
# Accept (B → A via B's bridge :9013)
{"village": "v1", "msg": "trade_accept", "offer_id": oid}
# Reject
{"village": "v1", "msg": "trade_reject", "offer_id": oid}
Verification
docker compose --profile mesh up -d
python3 scripts/village/run_village.py --run-id phase1 --epochs 2 --actions-per-epoch 4 --num-citizens 6
# Open http://localhost:8080, check action logs show trades over AXL mesh
---
Phase 2 — GossipSub for policy distribution
Goal: Distribute epoch policy over AXL GossipSub instead of citizens polling orchestrator.
Files changed: scripts/village/run_village.py
What changes
1. Town hall (main thread) publishes policy via GossipSub on mayor's bridge
2. Each citizen subscribes, reads policy from shared variable
3. Dedicated GossipSub tick thread for message propagation
4. Fallback to orchestrator HTTP if GossipSub unavailable
Verification
python3 scripts/village/run_village.py --run-id phase2
# Logs show "policy via GossipSub" vs "policy from orchestrator"
---
Phase 3 — Remove Yellow Pages MCP
Goal: Citizens discover each other via AXL /topology instead of centralized registry.
Files changed: scripts/village/run_village.py, docker-compose.yml
What changes
1. New find_peers_via_mesh() queries bridge /topology, cross-references with orchestrator's enrolled list
2. Remove register_yp() and list_peers_yp() from CitizenAgent
3. Remove --yp-url argument
4. Remove Yellow Pages from Docker Compose (port 9105, process in start-infra.sh)
Verification
docker compose down && docker compose --profile mesh up -d
# Only orchestrator (9200) runs — no Yellow Pages
python3 scripts/village/run_village.py --run-id phase3 --epochs 2
# Citizens still find each other and trade via AXL
Copy that into `docs/axl-integration-plan.md` and reference it in the new session