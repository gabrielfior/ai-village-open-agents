#!/usr/bin/env python3
"""
Yellow Pages / registrar: MCP service `directory` backed by a local JSON roster.

Built with FastMCP (https://gofastmcp.com/) — streamable HTTP on `/mcp`.
Uses JSON bodies (`json_response=True`) so the AXL aiohttp MCP router can `resp.json()`.
Uses `stateless_http=True` because the AXL bridge assigns its own `Mcp-Session-Id` and the
router forwards only JSON-RPC (not that header), so FastMCP must treat each POST as a fresh,
already-initialized session — otherwise `tools/call` returns 400 after a successful `initialize`.

AXL layout (run in order on the host that runs this service):
  1. MCP router:  python -m mcp_routing.mcp_router --port 9003
     (from axl/integrations after pip install -e .)
  2. This server: python yellow_pages_mcp.py --listen-port 9105 \\
       --roster ./yellow-pages-roster.json --register-router http://127.0.0.1:9003
  3. AXL node with router enabled, e.g. node-config:
       "router_addr": "http://127.0.0.1", "router_port": 9003

Remote agents call (on their own node's bridge):
  POST http://127.0.0.1:<api>/mcp/<yellow_pages_peer_hex>/directory
  JSON-RPC: initialize, then tools/call register_agent / list_agents / list_peer_ids /
  get_neighbors.

The router forwards X-From-Peer-Id (TCP remote → Yggdrasil GetKey). That can disagree
with bridge ``/topology`` ``our_public_key`` (gVisor userspace addresses may pad with
0xff). We treat obvious corrupt headers as suspect and use the tool ``peer_id``; if
both are well-formed hex and differ, registration fails (spoof guard).

Install: pip install -r scripts/village/requirements.txt
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.lifespan import lifespan

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yellow-pages")

SERVICE_NAME = "directory"


@dataclass
class RosterState:
    path: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_roster(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"updated_at": _utc_now(), "agents": {}}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if "agents" not in data:
        data = {"agents": {}, **data}
    return data


def _save_roster(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = _utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _from_peer_header() -> str:
    h = get_http_headers()
    v = h.get("x-from-peer-id") or h.get("X-From-Peer-Id") or ""
    return str(v).strip().lower()


def _is_hex64(s: str) -> bool:
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _tcp_derived_peer_id_suspect(mesh: str) -> bool:
    """True if X-From-Peer-Id looks like a padded / partial gVisor TCP key (0xff fill)."""
    if not _is_hex64(mesh):
        return True
    tail = mesh[32:]
    return tail.count("f") >= 28


def _canonical_peer_id(peer_arg: str, from_mesh: str) -> str:
    """Resolve roster key from tool arg and optional mesh header."""
    if _is_hex64(peer_arg) and _is_hex64(from_mesh):
        if peer_arg == from_mesh:
            return peer_arg
        if _tcp_derived_peer_id_suspect(from_mesh):
            logger.warning(
                "X-From-Peer-Id looks corrupt vs topology (padded ff); using peer_id arg"
            )
            return peer_arg
        raise ToolError(
            "peer_id does not match X-From-Peer-Id; refuse spoofed registration"
        )
    if _is_hex64(peer_arg):
        return peer_arg
    if _is_hex64(from_mesh):
        if _tcp_derived_peer_id_suspect(from_mesh):
            raise ToolError(
                "Mesh-derived peer id looks corrupt; pass peer_id from GET /topology"
            )
        return from_mesh
    raise ToolError("peer_id must be 64 lowercase hex characters (ed25519 public key)")


def _tau() -> float:
    return 2.0 * math.pi


def _deterministic_angle_rad(peer_id: str) -> float:
    """Map peer_id into [0, 2*pi) deterministically (virtual ring placement)."""
    h = hashlib.sha256(peer_id.encode("ascii")).digest()
    u = int.from_bytes(h[:8], "big") / float(2**64)
    return u * _tau()


def _angle_rad_for_record(peer_id: str, rec: dict[str, Any]) -> float:
    """Prefer stored angle on refresh; otherwise deterministic placement on first register."""
    stored = rec.get("angle_rad")
    if isinstance(stored, int | float) and math.isfinite(float(stored)):
        return float(stored) % _tau()
    return _deterministic_angle_rad(peer_id) % _tau()


def _circular_arc_distance_rad(a: float, b: float) -> float:
    d = abs(a - b) % _tau()
    return min(d, _tau() - d)


def build_mcp(
    state: RosterState,
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
        "yellow-pages",
        instructions=(
            "Yellow Pages registrar: virtual ring angles in [0,2*pi); register_agent (HELLO), "
            "list_agents, list_peer_ids (optional role filter), get_neighbors(n) angular nearest."
        ),
        lifespan=router_registration,
    )

    @mcp.tool
    async def list_agents() -> str:
        """Return the current roster (peer_id, role, caps, angle_rad, last_seen)."""
        async with state.lock:
            data = _load_roster(state.path)
        return json.dumps(data, indent=2)

    @mcp.tool
    async def list_peer_ids(role_filter: str = "") -> str:
        """List every registered peer_id. Set role_filter (e.g. \"citizen\") to only include that role (case-insensitive)."""
        want = role_filter.strip().lower()
        async with state.lock:
            data = _load_roster(state.path)
        agents: dict[str, Any] = data.get("agents") or {}
        rows: list[dict[str, str]] = []
        for pid, rec in agents.items():
            r = str(rec.get("role", "")).strip().lower()
            if want and r != want:
                continue
            rows.append({"peer_id": pid, "role": str(rec.get("role", "")).strip()})
        rows.sort(key=lambda x: x["peer_id"])
        out = {
            "peer_ids": [x["peer_id"] for x in rows],
            "entries": rows,
            "count": len(rows),
            "role_filter": want or None,
        }
        lines = [f"{len(rows)} peer_id(s)" + (f" (role={want})" if want else "")]
        lines.extend(x["peer_id"] for x in rows)
        out["text"] = "\n".join(lines)
        return json.dumps(out, indent=2)

    @mcp.tool
    async def register_agent(peer_id: str, role: str, caps: list[str]) -> str:
        """HELLO / heartbeat: register or refresh an agent on the roster."""
        peer_arg = peer_id.strip().lower()
        role = role.strip()
        if not role:
            raise ToolError("role is required")
        from_mesh = _from_peer_header()
        if not peer_arg and not from_mesh:
            raise ToolError("peer_id is required (or call over AXL with a mesh header)")
        canonical = _canonical_peer_id(peer_arg, from_mesh)
        async with state.lock:
            data = _load_roster(state.path)
            agents: dict[str, Any] = data.setdefault("agents", {})
            prior = agents.get(canonical)
            prior_rec = prior if isinstance(prior, dict) else {}
            angle_rad = _angle_rad_for_record(canonical, prior_rec)

            agents[canonical] = {
                "peer_id": canonical,
                "role": role,
                "caps": [str(c) for c in caps],
                "angle_rad": angle_rad,
                "last_seen": _utc_now(),
            }
            _save_roster(state.path, data)
            rec = agents[canonical]
        logger.info("Registered / heartbeat peer_id=%s role=%s", canonical[:16], role)
        return json.dumps(rec, indent=2)

    @mcp.tool
    async def get_neighbors(n: int, peer_id: str = "") -> str:
        """
        Return up to ``n`` other peers nearest on the virtual circle (shortest arc distance).
        Optional ``peer_id`` identifies the caller when mesh X-From-Peer-Id is absent.
        Ignores role (everyone participates). Caller must already be registered.
        """
        if n < 1:
            raise ToolError("n must be >= 1")
        if n > 4096:
            raise ToolError("n must be at most 4096")
        peer_arg = peer_id.strip().lower()
        from_mesh = _from_peer_header()
        if not peer_arg and not from_mesh:
            raise ToolError("peer_id is required (or call over AXL with a mesh header)")
        caller = _canonical_peer_id(peer_arg, from_mesh)

        async with state.lock:
            data = _load_roster(state.path)
            agents: dict[str, Any] = data.get("agents") or {}

            if caller not in agents:
                raise ToolError(
                    "caller is not registered; call register_agent first"
                )

            my_rec = agents[caller] if isinstance(agents[caller], dict) else {}
            my_angle = _angle_rad_for_record(caller, my_rec)

            scored: list[tuple[float, str, float]] = []
            for pid, raw in agents.items():
                if pid == caller:
                    continue
                rec = raw if isinstance(raw, dict) else {}
                theta = _angle_rad_for_record(pid, rec)
                dist = _circular_arc_distance_rad(my_angle, theta)
                scored.append((dist, pid, theta))

        scored.sort(key=lambda t: (t[0], t[1]))
        top = scored[:n]
        neighbors = [
            {
                "peer_id": pid,
                "angle_rad": theta,
                "distance_rad": dist,
            }
            for dist, pid, theta in top
        ]
        out: dict[str, Any] = {
            "caller_peer_id": caller,
            "caller_angle_rad": my_angle,
            "n_requested": n,
            "neighbors": neighbors,
            "count": len(neighbors),
        }
        return json.dumps(out, indent=2)

    return mcp


def main() -> None:
    p = argparse.ArgumentParser(description="Yellow Pages MCP directory (FastMCP) + JSON roster")
    p.add_argument(
        "--roster",
        type=Path,
        default=Path("yellow-pages-roster.json"),
        help="Path to roster JSON file",
    )
    p.add_argument(
        "--listen-host",
        default="127.0.0.1",
        help="Bind address for MCP HTTP",
    )
    p.add_argument(
        "--listen-port",
        type=int,
        default=9105,
        help="Port for streamable MCP HTTP",
    )
    p.add_argument(
        "--register-router",
        default="",
        help="If set, POST /register to this router base (e.g. http://127.0.0.1:9003)",
    )
    args = p.parse_args()

    state = RosterState(path=args.roster)
    public_endpoint = f"http://{args.listen_host}:{args.listen_port}/mcp"
    mcp = build_mcp(
        state,
        register_router=args.register_router,
        public_endpoint=public_endpoint,
    )

    logger.info(
        "Yellow Pages directory (FastMCP) %s roster=%s", public_endpoint, args.roster
    )
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
