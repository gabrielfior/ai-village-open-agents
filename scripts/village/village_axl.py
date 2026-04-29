"""AXL HTTP bridge helpers for village scripts (send/recv/topology)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


def get_topology(bridge_base: str) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(f"{bridge_base.rstrip('/')}/topology")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def send_raw(bridge_base: str, dest_peer_id: str, data: bytes) -> bool:
    try:
        req = urllib.request.Request(
            f"{bridge_base.rstrip('/')}/send",
            data=data,
            method="POST",
            headers={
                "X-Destination-Peer-Id": dest_peer_id,
                "Content-Type": "application/octet-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def recv_raw(bridge_base: str) -> tuple[str, bytes] | None:
    try:
        req = urllib.request.Request(f"{bridge_base.rstrip('/')}/recv")
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 204:
                return None
            if resp.status != 200:
                return None
            sender = resp.headers.get("X-From-Peer-Id", "") or ""
            return sender, resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return None
        return None
    except (urllib.error.URLError, OSError):
        return None


def load_gossip_sub(repo_root: Path) -> tuple[type, type]:
    """Load GossipSub from axl/examples/python-client/gossipsub/gossipsub.py."""
    import importlib.util
    import sys

    path = (
        repo_root
        / "axl"
        / "examples"
        / "python-client"
        / "gossipsub"
        / "gossipsub.py"
    )
    name = "axl_gossipsub"
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load gossipsub from {path}")
    mod = importlib.util.module_from_spec(spec)
    # Required before exec_module: @dataclass resolves cls.__module__ via sys.modules.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.GossipSub, mod.GossipConfig


def bridge_gossip_fns(
    bridge_base: str,
) -> tuple[Callable[[str, bytes], None], Callable[[], tuple[str, bytes] | None]]:
    def send_fn(dest_key: str, data: bytes) -> None:
        send_raw(bridge_base, dest_key, data)

    def recv_fn() -> tuple[str, bytes] | None:
        return recv_raw(bridge_base)

    return send_fn, recv_fn


def policy_topic(run_id: str) -> str:
    return f"village/{run_id}/policy"
