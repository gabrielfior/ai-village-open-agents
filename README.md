# AI Village — Multi-Agent Economy on AXL

An **Agent Town** simulation where AI agents trade resources, accumulate wealth, and respond to fiscal policy — all communicating over the [AXL](https://github.com/gensyn-ai/axl) peer-to-peer mesh network.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Docker: village-mesh (12 AXL P2P nodes)               │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐     ┌──────┐     │
│  │  YP  │ │Mayor │ │ C0   │ │ C1   │ ... │ C9   │     │
│  │:9002 │ │:9004 │ │:9012 │ │:9013 │     │:9021 │     │
│  └──────┘ └──────┘ └──────┘ └──────┘     └──────┘     │
│              ↑ TCP/TLS mesh (Yggdrasil)                │
└─────────────────────────────────────────────────────────┘
         │ HTTP bridge                        │ HTTP bridge
         ▼                                    ▼
┌─────────────────────┐       ┌──────────────────────────┐
│ run_village.py      │       │ village-infra            │
│  ┌────────────────┐ │       │  ┌────────────────────┐  │
│  │ Town hall      │─┼───────┼─▶│ Orchestrator :9200 │  │
│  │ (main thread)  │ │       │  │ epoch lifecycle    │  │
│  │ GossipSub pub  │ │       │  │ resource ledger    │  │
│  └────────────────┘ │       │  │ tax/UBI/Gini       │  │
│  ┌────────────────┐ │       │  └────────────────────┘  │
│  │ Citizen threads │ │       └──────────────────────────┘
│  │ (n=1..10)       │ │
│  │ AXL send/recv   │ │       ┌──────────────────────────┐
│  │ GossipSub sub   │ │       │ village-ui :8080         │
│  └────────────────┘ │       │  6 temporal line charts  │
└─────────────────────┘       └──────────────────────────┘
```

### Communication flows

| Flow | Transport | AXL |
|------|-----------|-----|
| Trade offers/accepts/rejects | `send_raw`/`recv_raw` on citizen's AXL bridge | ✅ |
| Policy distribution | GossipSub pub/sub over AXL mesh | ✅ |
| Peer discovery | `/topology` on each citizen's bridge at startup | ✅ |
| Action execution | HTTP POST to orchestrator | — |
| State queries | HTTP GET from orchestrator | — |

## Quick start

```bash
# 1. Start infrastructure + 12-node AXL mesh
docker compose --profile mesh up -d

# 2. Wait for everything to be healthy (~30s)
docker compose ps

# 3. Run the simulation
python3 scripts/village/run_village.py --run-id demo --epochs 6 --actions-per-epoch 8 --num-citizens 10

# 4. Open the dashboard
open http://localhost:8080
```

## Simulation mechanics

- **Citizens** take actions each epoch: earn resources, trade (via AXL P2P), or noop
- **Earn**: skill multipliers (0.3×–1.2×) create natural inequality
- **Trade**: citizens negotiate resource exchanges over AXL P2P messages
- **Tax**: proportional wealth tax on ALL resources (coin, wood, stone, grain)
- **UBI**: total tax pool redistributed equally as coin
- **Consumption**: citizens must consume grain and wood each epoch or face a coin penalty
- **Policy**: tax rate and UBI adjust dynamically to target Gini ≤ 0.05

## UI charts

| Chart | Type | What it shows |
|-------|------|--------------|
| Gini coefficient | Line | Wealth inequality over time (↓74% in 6 epochs) |
| Wealth over time | Multi-line | Total wealth per citizen (coin + resources at market prices) |
| Coin balance | Multi-line | Coin balance per citizen over time |
| Executed trades | Line | Completed AXL P2P trades per epoch |
| Policy parameters | Dual-line | Tax rate (left axis) and UBI (right axis) |
| Total resources | Multi-line | Economy-wide stock of coin, wood, stone, grain |

## Customization

```bash
# Adjust policy aggressiveness
python3 scripts/village/run_village.py \
  --tax-adjust 5.0 --ubi-adjust 100 --gini-target 0.05

# More citizens/epochs
python3 scripts/village/run_village.py \
  --num-citizens 20 --epochs 10 --actions-per-epoch 12

# Override initial policy
python3 scripts/village/run_village.py \
  --initial-tax 0.2 --initial-ubi 10
```

## Project structure

```
scripts/village/
├── run_village.py         # Main simulation (town hall + citizen threads)
├── orchestrator.py        # Resource ledger, epoch lifecycle, tax/UBI/Gini
├── village_axl.py         # AXL bridge HTTP helpers (send/recv/topology/GossipSub)
├── town_hall.py           # Standalone GossipSub publisher (reference)
├── citizen.py             # Standalone subprocess citizen (reference)
├── check_village_ports.py # Diagnostic port probe
├── ui/                    # React + SVG dashboard (served on :8080)
│   └── src/
│       ├── GiniChart.tsx, WealthChart.tsx, BalanceChart.tsx
│       ├── TradeVolumeChart.tsx, PolicyChart.tsx, ResourceChart.tsx
│       └── ActionsTable.tsx
axl/                       # AXL P2P node (submodule)
docker-compose.yml         # village-infra, village-mesh, village-ui
launch_village.sh          # One-command launcher
```

## AXL integration depth

| Integration | What it demonstrates |
|------------|---------------------|
| `send_raw`/`recv_raw` | P2P message delivery across the AXL mesh |
| GossipSub | Topic-based pub/sub for policy distribution |
| Background tick thread | Continuous GossipSub mesh maintenance |
| Star topology over Yggdrasil | 12 AXL nodes in one container, routed via Yggdrasil TLS |
| Per-citizen bridge ports | Each citizen has a dedicated AXL node (9012–9021) |
| Trade message protocol | Custom JSON envelope over AXL (`village/v1` namespace) |

## Future work

### LLM-powered citizen brains

Replace the random action policy with LLM calls (via 0G Compute Network or any provider). Each citizen would query an LLM to decide actions based on:
- Current resource holdings and consumption needs
- Counterparty reputation from past trades
- Historical policy trends (tax rate trajectory)
- Strategic goals (wealth accumulation, risk tolerance)

This turns the simulation from random agents into **strategic agents** — trades become actual negotiations, citizens can form coalitions, and the economy's behavior becomes emergent rather than statistical.

### Experience-based learning

Give citizens memory of past actions and outcomes:
- Which counterparties accepted vs rejected previous offers
- Which resources have the best earn rates given their skills
- Optimal trade ratios learned from historical data
- Adaptation to policy changes (e.g., front-running tax increases)

### Decentralized state (remove orchestrator)

Replace the orchestrator with a fully P2P consensus mechanism over AXL:
- Epoch lifecycle coordinated via AXL GossipSub
- Resource ledger replicated across all citizens
- Tax/UBI applied locally from agreed-upon state
- Fraud detection via cross-validation between peers

### Subprocess citizens

Convert thread-based citizens to standalone OS processes (using `citizen.py` as the reference). Each citizen spawns its own AXL node binary, runs independently, and can be killed/restarted without affecting others. This would satisfy the "separate AXL nodes" criterion literally.

### Agent chat protocol

Add a `"msg": "chat"` message type alongside trades. Citizens could send free-form messages visible in the UI — enabling negotiation, alliance formation, or banter. This would demonstrate AXL's flexibility for non-trade communication.

### More charts and analytics

- Trade network graph (who traded with whom)
- Sankey diagram of resource flows through the economy
- Policy sensitivity analysis (what-if scenarios)
- Per-citizen action timelines
