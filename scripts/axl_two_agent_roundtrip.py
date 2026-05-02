#!/usr/bin/env python3
"""
Two agents, one round-trip over Gensyn AXL (raw /send + /recv).

Prerequisites
-------------
1. Build and run two AXL nodes (separate processes), each with its own key and
   api_port. Use the same tcp_port on every node (default 7000): the node's
   /send dial uses its own tcp_port as the destination port on the peer.

2. Peers must be able to reach each other on the mesh (local example: one node
   listens, the other peers to it — see configs).

3. Docs: https://docs.gensyn.ai/tech/agent-exchange-layer
   API: https://github.com/gensyn-ai/axl/blob/main/docs/api.md

Usage
-----
Terminal 1: ./node -config axl-node-a.example.json
Terminal 2: ./node -config axl-node-b.example.json
Terminal 3:

  python3 scripts/axl_two_agent_roundtrip.py \\
    --alice-api http://127.0.0.1:9002 \\
    --bob-api http://127.0.0.1:9012
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class RecvResult:
    from_peer: str
    body: bytes


def _request(
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, hdrs, resp.read()
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        body = e.read() if e.fp else b""
        return e.code, hdrs, body


def topology(base: str) -> dict[str, Any]:
    code, _, body = _request("GET", f"{base.rstrip('/')}/topology")
    if code != 200:
        raise RuntimeError(f"topology failed: HTTP {code} {body!r}")
    return json.loads(body.decode())


def send_message(base: str, dest_peer_hex: str, payload: bytes) -> None:
    code, _, body = _request(
        "POST",
        f"{base.rstrip('/')}/send",
        data=payload,
        headers={"X-Destination-Peer-Id": dest_peer_hex},
    )
    if code != 200:
        raise RuntimeError(f"send failed: HTTP {code} {body!r}")


def recv_once(base: str) -> RecvResult | None:
    code, hdrs, body = _request("GET", f"{base.rstrip('/')}/recv")
    if code == 204:
        return None
    if code != 200:
        raise RuntimeError(f"recv failed: HTTP {code} {body!r}")
    from_peer = hdrs.get("x-from-peer-id", "")
    if not from_peer:
        raise RuntimeError("recv missing X-From-Peer-Id header")
    return RecvResult(from_peer=from_peer, body=body)


def recv_wait(
    base: str,
    *,
    expect_from: str | None = None,
    timeout_sec: float = 60.0,
    poll_sec: float = 0.25,
) -> RecvResult:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        msg = recv_once(base)
        if msg is None:
            time.sleep(poll_sec)
            continue
        if expect_from is not None and msg.from_peer.lower() != expect_from.lower():
            # Drain unexpected sender (should not happen in this demo).
            time.sleep(poll_sec)
            continue
        return msg
    raise TimeoutError(f"no message on {base} within {timeout_sec}s")


def main() -> int:
    p = argparse.ArgumentParser(description="AXL two-agent one-round dialogue.")
    p.add_argument(
        "--alice-api",
        default="http://127.0.0.1:9002",
        help="Base URL for Alice's local AXL HTTP bridge",
    )
    p.add_argument(
        "--bob-api",
        default="http://127.0.0.1:9012",
        help="Base URL for Bob's local AXL HTTP bridge",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for each recv",
    )
    args = p.parse_args()

    alice_base: str = args.alice_api
    bob_base: str = args.bob_api

    alice_topo = topology(alice_base)
    bob_topo = topology(bob_base)
    alice_key = alice_topo["our_public_key"]
    bob_key = bob_topo["our_public_key"]

    print("AXL two-agent round (Alice → Bob → Alice)\n")
    print(f"Alice public key: {alice_key}")
    print(f"Bob public key:   {bob_key}\n")

    alice_opening = json.dumps(
        {"agent": "Alice", "text": "Hi Bob — checking in over AXL. One round-trip OK?"}
    ).encode()

    print("Alice sends:", alice_opening.decode())
    send_message(alice_base, bob_key, alice_opening)

    bob_got = recv_wait(bob_base, expect_from=alice_key, timeout_sec=args.timeout)
    print("Bob received: ", bob_got.body.decode())

    bob_reply = json.dumps(
        {
            "agent": "Bob",
            "text": "Hi Alice — copy. AXL recv looks good on my node.",
        }
    ).encode()
    print("Bob sends:  ", bob_reply.decode())
    send_message(bob_base, alice_key, bob_reply)

    alice_got = recv_wait(alice_base, expect_from=bob_key, timeout_sec=args.timeout)
    print("Alice received:", alice_got.body.decode())
    print("\nDone — one conversational round complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TimeoutError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
