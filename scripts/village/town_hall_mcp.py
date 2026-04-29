#!/usr/bin/env python3
"""
Town Hall MCP: append-only audit log for AI Village (UI / replay).

FastMCP streamable HTTP, stateless_http=True (AXL-router compatible pattern).
Orchestrator calls append_event / append_epoch_summary via direct HTTP JSON-RPC
to this service.

Example:
  python town_hall_mcp.py --listen-port 9106 --data-dir ./town-hall-data \\
    --register-router http://127.0.0.1:9003
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("town-hall-mcp")

SERVICE_NAME = "townhall"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StoreState:
    data_dir: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    seq_by_run: dict[str, int] = field(default_factory=dict)

    def run_path(self, run_id: str) -> Path:
        p = self.data_dir / run_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def events_path(self, run_id: str) -> Path:
        return self.run_path(run_id) / "events.jsonl"


def build_mcp(
    state: StoreState,
    *,
    register_router: str,
    public_endpoint: str,
) -> FastMCP:
    @lifespan
    async def router_registration(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        if register_router:
            url = register_router.rstrip("/") + "/register"
            payload = {"service": SERVICE_NAME, "endpoint": public_endpoint}
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Router register failed {resp.status_code}: {resp.text}"
                    )
            logger.info("Registered service %r -> %s", SERVICE_NAME, public_endpoint)
        yield {}

    mcp = FastMCP(
        "town-hall-audit",
        instructions=(
            "AI Village audit log: append_event (orchestrator), query_actions, "
            "get_timeline, append_epoch_summary."
        ),
        lifespan=router_registration,
    )

    def _next_seq(run_id: str) -> int:
        state.seq_by_run[run_id] = state.seq_by_run.get(run_id, 0) + 1
        return state.seq_by_run[run_id]

    @mcp.tool
    async def append_event(
        run_id: str,
        epoch: int,
        peer_id: str,
        kind: str,
        payload_json: str,
        decision: str,
        reason: str,
        counterparty_peer_id: str,
    ) -> str:
        """Append one orchestrator-validated event (single writer: orchestrator)."""
        run_id = run_id.strip()
        if not run_id:
            return json.dumps({"error": "run_id required"})
        async with state.lock:
            seq = _next_seq(run_id)
            try:
                payload = json.loads(payload_json) if payload_json else {}
            except json.JSONDecodeError:
                payload = {"raw": payload_json}
            rec = {
                "seq": seq,
                "run_id": run_id,
                "epoch": epoch,
                "peer_id": peer_id.strip().lower(),
                "kind": kind,
                "payload": payload,
                "decision": decision,
                "reason": reason,
                "counterparty_peer_id": counterparty_peer_id.strip().lower(),
                "ts": _utc(),
            }
            path = state.events_path(run_id)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return json.dumps({"ok": True, "seq": seq})

    @mcp.tool
    async def append_epoch_summary(run_id: str, epoch: int, summary_json: str) -> str:
        """Store end-of-epoch fiscal summary (Gini, balances, policy)."""
        run_id = run_id.strip()
        async with state.lock:
            sp = state.run_path(run_id)
            fn = sp / f"epoch_{epoch:05d}_summary.json"
            data = json.loads(summary_json) if summary_json else {}
            fn.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return json.dumps({"ok": True, "path": str(fn)})

    @mcp.tool
    async def query_actions(
        run_id: str,
        peer_id: str = "",
        epoch: int = -12345,
        limit: int = 200,
    ) -> str:
        """Return recent events, optionally filter by citizen or epoch."""
        run_id = run_id.strip()
        path = state.events_path(run_id)
        if not path.exists():
            return json.dumps({"events": [], "count": 0})
        want_peer = peer_id.strip().lower()
        rows: list[dict[str, Any]] = []
        async with state.lock:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if want_peer and o.get("peer_id") != want_peer:
                        continue
                    if epoch != -12345 and int(o.get("epoch", -1)) != epoch:
                        continue
                    rows.append(o)
        tail = rows[-limit:] if limit > 0 else rows
        return json.dumps({"events": tail, "count": len(tail)}, indent=2)

    @mcp.tool
    async def get_timeline(run_id: str, limit: int = 500) -> str:
        """Last N events for run_id (all citizens)."""
        run_id = run_id.strip()
        path = state.events_path(run_id)
        if not path.exists():
            return json.dumps({"events": [], "count": 0})
        async with state.lock:
            lines = path.read_text(encoding="utf-8").splitlines()
        rows = []
        for line in lines[-limit:]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return json.dumps({"events": rows, "count": len(rows)}, indent=2)

    return mcp


def main() -> None:
    p = argparse.ArgumentParser(description="Town Hall audit MCP")
    p.add_argument("--listen-host", default="127.0.0.1")
    p.add_argument("--listen-port", type=int, default=9106)
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "town-hall-data",
    )
    p.add_argument("--register-router", default="")
    args = p.parse_args()

    state = StoreState(data_dir=args.data_dir)
    public_endpoint = f"http://{args.listen_host}:{args.listen_port}/mcp"
    mcp = build_mcp(
        state,
        register_router=args.register_router,
        public_endpoint=public_endpoint,
    )
    logger.info("Town Hall MCP %s data_dir=%s", public_endpoint, args.data_dir)
    mcp.run(
        transport="streamable-http",
        host=args.listen_host,
        port=args.listen_port,
        path="/mcp",
        json_response=True,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
