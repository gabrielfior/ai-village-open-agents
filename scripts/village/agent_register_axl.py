#!/usr/bin/env python3
"""
Agent: start a local AXL node (subprocess) using a given PEM, join the mesh, then
register with the Yellow Pages directory over MCP (POST /mcp/<yellow_pages_peer>/directory).

Prerequisites
-------------
- Built `node` binary (e.g. axl/node).
- Yellow Pages host running: MCP router, yellow_pages_mcp.py, AXL node with router_addr set.
- This agent's node must peer into the same mesh (e.g. --peer tls://127.0.0.1:9001).

Example
-------
  python3 agent_register_axl.py \\
    --node-binary ../../axl/node \\
    --config-dir ../../axl \\
    --pem ../../axl/private-b.pem \\
    --yellow-pages-peer-id <64-hex-from-yellow-pages-topology> \\
    --peer tls://127.0.0.1:9001 \\
    --api-port 9012 \\
    --role citizen \\
    --caps chat,trade
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _json_request(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, hdrs, resp.read()
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        body = e.read() if e.fp else b""
        return e.code, hdrs, body


def topology(base: str) -> dict[str, Any]:
    code, _, body = _request_get(base, "/topology")
    if code != 200:
        raise RuntimeError(f"topology HTTP {code}: {body.decode(errors='replace')}")
    return json.loads(body.decode())


def _request_get(base: str, path: str) -> tuple[int, dict[str, str], bytes]:
    return _json_request("GET", f"{base.rstrip('/')}{path}")


def _mcp_url(base: str, yellow_pages_peer: str) -> str:
    return f"{base.rstrip('/')}/mcp/{yellow_pages_peer}/directory"


def mcp_initialize(base: str, yellow_pages_peer: str) -> str:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent-register", "version": "0.1"},
            },
            "id": 0,
        }
    ).encode()
    code, hdrs, resp_body = _json_request(
        "POST", _mcp_url(base, yellow_pages_peer), data=body, headers=_mcp_headers(None)
    )
    if code != 200:
        raise RuntimeError(f"initialize HTTP {code}: {resp_body.decode(errors='replace')}")
    session = hdrs.get("mcp-session-id", "")
    if not session:
        raise RuntimeError("initialize: missing Mcp-Session-Id header on bridge response")
    msg = json.loads(resp_body.decode())
    if "error" in msg:
        raise RuntimeError(f"initialize JSON-RPC error: {msg['error']}")
    return session


def mcp_tools_call(
    base: str,
    yellow_pages_peer: str,
    session: str,
    *,
    name: str,
    arguments: dict[str, Any],
    req_id: int = 1,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": req_id,
        }
    ).encode()
    code, _, resp_body = _json_request(
        "POST",
        _mcp_url(base, yellow_pages_peer),
        data=body,
        headers=_mcp_headers(session),
    )
    if code != 200:
        raise RuntimeError(f"tools/call HTTP {code}: {resp_body.decode(errors='replace')}")
    msg = json.loads(resp_body.decode())
    if "error" in msg:
        raise RuntimeError(f"tools/call error: {msg['error']}")
    return msg.get("result") or {}


def _mcp_headers(session: str | None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if session:
        h["Mcp-Session-Id"] = session
    return h


def write_node_config(
    path: Path,
    *,
    pem: Path,
    peers: list[str],
    listen: list[str],
    api_port: int,
    tcp_port: int,
) -> None:
    cfg = {
        "PrivateKeyPath": str(pem.resolve()),
        "Peers": peers,
        "Listen": listen,
        "api_port": api_port,
        "tcp_port": tcp_port,
    }
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def wait_for_topology(base: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return topology(base)
        except (urllib.error.URLError, json.JSONDecodeError, RuntimeError) as e:
            last_err = e
            time.sleep(0.3)
    raise TimeoutError(f"bridge not ready at {base}: {last_err}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Start AXL node and register with Yellow Pages MCP directory"
    )
    p.add_argument("--node-binary", type=Path, required=True)
    p.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Working directory for node subprocess (default: pem parent)",
    )
    p.add_argument("--pem", type=Path, required=True)
    p.add_argument(
        "--yellow-pages-peer-id",
        required=True,
        help="64-char hex Yellow Pages node's public key (from its /topology)",
    )
    p.add_argument(
        "--peer",
        action="append",
        default=[],
        help="TLS peer URI (repeatable), e.g. tls://127.0.0.1:9001",
    )
    p.add_argument("--api-port", type=int, default=9012)
    p.add_argument("--tcp-port", type=int, default=7000)
    p.add_argument("--role", default="citizen")
    p.add_argument(
        "--caps",
        default="",
        help="Comma-separated capability strings",
    )
    p.add_argument(
        "--keep-node",
        action="store_true",
        help="Do not terminate the node on exit (for debugging)",
    )
    args = p.parse_args()

    if not args.peer:
        print(
            "Warning: no --peer set; node may not reach the Yellow Pages host.",
            file=sys.stderr,
        )

    cwd = args.config_dir if args.config_dir is not None else args.pem.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        dir=cwd,
        prefix="agent-node-",
    ) as tmp:
        cfg_path = Path(tmp.name)
    try:
        write_node_config(
            cfg_path,
            pem=args.pem,
            peers=args.peer,
            listen=[],
            api_port=args.api_port,
            tcp_port=args.tcp_port,
        )

        proc = subprocess.Popen(
            [str(args.node_binary.resolve()), "-config", cfg_path.name],
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:

            def _cleanup() -> None:
                if args.keep_node:
                    return
                if proc.poll() is None:
                    proc.send_signal(signal.SIGTERM)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()

            bridge = f"http://127.0.0.1:{args.api_port}"
            topo = wait_for_topology(bridge)
            my_id = topo["our_public_key"]
            print("Agent public key:", my_id)

            caps = [c.strip() for c in args.caps.split(",") if c.strip()]
            session = mcp_initialize(bridge, args.yellow_pages_peer_id)
            result = mcp_tools_call(
                bridge,
                args.yellow_pages_peer_id,
                session,
                name="register_agent",
                arguments={
                    "peer_id": my_id,
                    "role": args.role,
                    "caps": caps,
                },
            )
            print("register_agent result:", json.dumps(result, indent=2))

            listed = mcp_tools_call(
                bridge,
                args.yellow_pages_peer_id,
                session,
                name="list_agents",
                arguments={},
                req_id=2,
            )
            print("list_agents result:", json.dumps(listed, indent=2))
        finally:
            _cleanup()
    finally:
        try:
            cfg_path.unlink(missing_ok=True)
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, TimeoutError, urllib.error.URLError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
