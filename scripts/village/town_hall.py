#!/usr/bin/env python3
"""
Town hall driver: open/close epochs on orchestrator, publish policy via GossipSub.

Assumes local AXL node is already running (bridge at --bridge). Seeds GossipSub mesh
with peer ids from Yellow Pages (citizens).

Example:
  python town_hall.py --bridge http://127.0.0.1:9002 \\
    --yellow-pages-peer-id <64hex> \\
    --orchestrator http://127.0.0.1:9200 \\
    --run-id demo1 --max-epochs 3 --actions-per-epoch 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from village_axl import (  # noqa: E402
    bridge_gossip_fns,
    get_topology,
    load_gossip_sub,
    policy_topic,
)


def _json_req(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _mcp_url(base: str, yellow_pages_peer: str) -> str:
    return f"{base.rstrip('/')}/mcp/{yellow_pages_peer}/directory"


def mcp_init(base: str, yellow_pages_peer: str) -> str:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "town-hall", "version": "0.1"},
            },
            "id": 0,
        }
    ).encode()
    req = urllib.request.Request(
        _mcp_url(base, yellow_pages_peer),
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        session = hdrs.get("mcp-session-id", "")
    if not session:
        raise RuntimeError("MCP initialize: missing Mcp-Session-Id")
    msg = json.loads(raw)
    if "error" in msg:
        raise RuntimeError(f"MCP initialize error: {msg['error']}")
    return session


def mcp_tools_call(
    base: str,
    yellow_pages_peer: str,
    session: str,
    name: str,
    arguments: dict[str, Any],
    req_id: int,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": req_id,
        }
    ).encode()
    req = urllib.request.Request(
        _mcp_url(base, yellow_pages_peer),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Mcp-Session-Id": session,
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode())
    if "error" in out:
        raise RuntimeError(f"tools/call error: {out['error']}")
    return out.get("result") or {}


def _mcp_text_result(result: dict[str, Any]) -> str:
    if not result:
        return ""
    sc = result.get("structuredContent")
    if isinstance(sc, dict) and "text" in sc:
        return str(sc["text"])
    content = result.get("content")
    if isinstance(content, list) and content:
        item = content[0]
        if isinstance(item, dict) and item.get("type") == "text":
            return str(item.get("text", ""))
    if isinstance(result, str):
        return result
    return json.dumps(result)


def list_citizen_peer_ids(
    bridge: str, yellow_pages_peer: str, session: str
) -> list[str]:
    raw = mcp_tools_call(
        bridge,
        yellow_pages_peer,
        session,
        "list_peer_ids",
        {"role_filter": "citizen"},
        1,
    )
    txt = _mcp_text_result(raw).strip()
    if not txt:
        return []
    try:
        o = json.loads(txt)
        return [str(p).lower() for p in o.get("peer_ids", [])]
    except json.JSONDecodeError:
        return []


def next_policy(prev: dict[str, Any], gini: float) -> dict[str, Any]:
    tax = float(prev.get("wealth_tax_rate", 0.1))
    ubi = int(prev.get("ubi", 5))
    if gini > 0.35:
        tax = min(0.45, tax + 0.02)
    else:
        tax = max(0.02, tax - 0.02)
    return {"wealth_tax_rate": round(tax, 4), "ubi": ubi}


def run_loop(args: argparse.Namespace) -> int:
    topo = get_topology(args.bridge)
    if not topo:
        print("topology unavailable; is the AXL node up?", file=sys.stderr)
        return 1
    my_id = str(topo.get("our_public_key", "")).strip().lower()
    print("town hall bridge peer_id:", my_id)

    session = mcp_init(args.bridge, args.yellow_pages_peer_id)

    GossipSub, GossipConfig = load_gossip_sub(_ROOT)
    send_fn, recv_fn = bridge_gossip_fns(args.bridge)
    gs = GossipSub(GossipConfig(), my_id, send_fn, recv_fn)
    topic = policy_topic(args.run_id)
    gs.subscribe(topic)

    peers = set(list_citizen_peer_ids(args.bridge, args.yellow_pages_peer_id, session))
    peers.add(my_id)
    for p in peers:
        gs.add_peer(p)

    orch = args.orchestrator.rstrip("/")
    policy: dict[str, Any] = {
        "wealth_tax_rate": args.initial_tax,
        "ubi": args.initial_ubi,
    }

    for epoch in range(args.max_epochs):
        print(f"--- epoch {epoch} policy={policy} ---")
        _json_req(f"{orch}/v1/epoch/open", {"run_id": args.run_id, "epoch": epoch, "policy": policy})

        envelope = {
            "run_id": args.run_id,
            "epoch": epoch,
            "policy": policy,
            "orchestrator_base_url": orch,
            "deadline_ts": time.time() + args.epoch_timeout_sec,
        }
        payload = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        gs.publish(topic, payload)

        deadline = time.time() + args.epoch_timeout_sec
        while time.time() < deadline:
            gs.tick()
            try:
                st = _get_json(f"{orch}/v1/state?run_id={args.run_id}")
            except (urllib.error.URLError, json.JSONDecodeError):
                time.sleep(0.2)
                continue
            if st.get("phase") != "action":
                break
            enrolled = st.get("enrolled") or []
            done = set(st.get("epoch_complete") or [])
            if len(enrolled) > 0 and done.issuperset(set(enrolled)):
                break
            time.sleep(0.3)

        snap = _json_req(f"{orch}/v1/epoch/close", {"run_id": args.run_id})
        gini = float(snap.get("gini", 0.0))
        print("closed epoch", epoch, "gini=", gini, "balances=", snap.get("balances"))
        policy = next_policy(policy, gini)

    print("town hall finished")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="AI Village town hall driver")
    p.add_argument("--bridge", required=True, help="Local AXL HTTP API base")
    p.add_argument("--yellow-pages-peer-id", required=True)
    p.add_argument("--orchestrator", default="http://127.0.0.1:9200")
    p.add_argument("--run-id", required=True)
    p.add_argument("--max-epochs", type=int, default=5)
    p.add_argument("--actions-per-epoch", type=int, default=5)
    p.add_argument("--initial-tax", type=float, default=0.1)
    p.add_argument("--initial-ubi", type=int, default=5)
    p.add_argument("--epoch-timeout-sec", type=float, default=120.0)
    args = p.parse_args()
    return run_loop(args)


if __name__ == "__main__":
    raise SystemExit(main())
