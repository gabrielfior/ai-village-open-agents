#!/usr/bin/env python3
"""
AI Village citizen: AXL node + GossipSub policy + random v0 brain + orchestrator actions.

Example:
  python citizen.py --node-binary ../../axl/node --pem ../../axl/private-b.pem \\
    --yellow-pages-peer-id <hex> --peer tls://127.0.0.1:9001 \\
    --api-port 9012 --bridge http://127.0.0.1:9012 \\
    --orchestrator http://127.0.0.1:9200 --run-id demo1 --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import deque
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
    recv_raw,
    send_raw,
)


def _json_post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _get(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _mcp_url(base: str, yp: str) -> str:
    return f"{base.rstrip('/')}/mcp/{yp}/directory"


def mcp_init(base: str, yp: str) -> str:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "citizen", "version": "0.1"},
            },
            "id": 0,
        }
    ).encode()
    req = urllib.request.Request(
        _mcp_url(base, yp),
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        sess = hdrs.get("mcp-session-id", "")
    if not sess:
        raise RuntimeError("MCP missing session")
    msg = json.loads(raw)
    if "error" in msg:
        raise RuntimeError(str(msg["error"]))
    return sess


def mcp_call(base: str, yp: str, sess: str, name: str, args: dict[str, Any], rid: int) -> dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
            "id": rid,
        }
    ).encode()
    req = urllib.request.Request(
        _mcp_url(base, yp),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Mcp-Session-Id": sess,
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode())
    if "error" in out:
        raise RuntimeError(str(out["error"]))
    return out.get("result") or {}


def _mcp_text(res: dict[str, Any]) -> str:
    c = res.get("content")
    if isinstance(c, list) and c and isinstance(c[0], dict):
        if c[0].get("type") == "text":
            return str(c[0].get("text", ""))
    sc = res.get("structuredContent")
    if isinstance(sc, dict) and "text" in sc:
        return str(sc["text"])
    return json.dumps(res) if res else ""


def list_peer_citizens(bridge: str, yp: str, sess: str, my_id: str) -> list[str]:
    raw = mcp_call(bridge, yp, sess, "list_peer_ids", {"role_filter": "citizen"}, 1)
    txt = _mcp_text(raw).strip()
    if not txt:
        return []
    try:
        o = json.loads(txt)
        return [str(p).lower() for p in o.get("peer_ids", []) if str(p).lower() != my_id]
    except json.JSONDecodeError:
        return []


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


def wait_topology(base: str, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        t = get_topology(base)
        if t and t.get("our_public_key"):
            return t
        time.sleep(0.3)
    raise TimeoutError(f"topology: {last}")


def enc_village(msg: dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


class RandomCitizenBrain:
    def __init__(self, seed: int, peer_id: str) -> None:
        h = hashlib.sha256(f"{seed}:{peer_id}".encode()).digest()
        self.rng = random.Random(int.from_bytes(h[:8], "big"))

    def pick(
        self,
        *,
        peer_candidates: list[str],
        balance: int,
        earn_remaining: int,
    ) -> tuple[str, dict[str, Any]]:
        r = self.rng.random()
        if not peer_candidates or r < 0.4:
            return "noop", {"type": "noop"}
        if r < 0.7 and earn_remaining > 0:
            amt = min(self.rng.randint(1, 15), earn_remaining)
            return "earn", {"type": "earn", "amount": amt}
        cp = self.rng.choice(peer_candidates)
        give = min(balance, max(1, self.rng.randint(1, min(10, max(1, balance)))))
        want = max(1, self.rng.randint(1, 10))
        oid = f"o{self.rng.getrandbits(48):012x}"
        return "trade", {
            "counterparty": cp,
            "give_amount": give,
            "want_amount": want,
            "offer_id": oid,
        }


def gossip_policy_payload(gs: Any, topic: str, run_id: str, want_epoch: int, timeout: float) -> dict[str, Any] | None:
    import base64

    deadline = time.time() + timeout
    while time.time() < deadline:
        gs.tick()
        for mid in list(gs._received):  # noqa: SLF001
            msg = gs.msg_cache.get(mid)
            if not msg or msg.get("topic") != topic:
                continue
            try:
                raw = base64.b64decode(msg.get("data", ""))
                env = json.loads(raw.decode("utf-8"))
                if env.get("run_id") == run_id and int(env.get("epoch", -1)) == want_epoch:
                    return env
            except (json.JSONDecodeError, ValueError):
                continue
        time.sleep(0.05)
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="AI Village citizen")
    p.add_argument("--node-binary", type=Path, required=True)
    p.add_argument("--config-dir", type=Path, default=None)
    p.add_argument("--pem", type=Path, required=True)
    p.add_argument("--yellow-pages-peer-id", required=True)
    p.add_argument("--peer", action="append", default=[])
    p.add_argument("--api-port", type=int, required=True)
    p.add_argument("--tcp-port", type=int, default=7000)
    p.add_argument(
        "--bridge",
        default="",
        help="Override bridge URL (default http://127.0.0.1:<api-port>)",
    )
    p.add_argument("--orchestrator", default="http://127.0.0.1:9200")
    p.add_argument("--run-id", required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--keep-node", action="store_true")
    args = p.parse_args()

    bridge = args.bridge.strip() or f"http://127.0.0.1:{args.api_port}"
    orch = args.orchestrator.rstrip("/")
    cwd = args.config_dir if args.config_dir else args.pem.parent

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=cwd, prefix="citizen-node-"
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

        def cleanup() -> None:
            if args.keep_node:
                return
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        topo = wait_topology(bridge)
        my_id = str(topo["our_public_key"]).strip().lower()
        print("citizen peer_id", my_id)

        sess = mcp_init(bridge, args.yellow_pages_peer_id)
        mcp_call(
            bridge,
            args.yellow_pages_peer_id,
            sess,
            "register_agent",
            {"peer_id": my_id, "role": "citizen", "caps": ["trade", "chat"]},
            2,
        )

        GossipSub, GossipConfig = load_gossip_sub(_ROOT)
        send_fn, recv_fn = bridge_gossip_fns(bridge)
        gs = GossipSub(GossipConfig(), my_id, send_fn, recv_fn)
        topic = policy_topic(args.run_id)
        gs.subscribe(topic)
        peers_known = {my_id}
        for e in topo.get("tree", []) or []:
            pk = e.get("public_key")
            if isinstance(pk, str) and len(pk) == 64:
                peers_known.add(pk.lower())
        for p in peers_known:
            gs.add_peer(p)

        _json_post(f"{orch}/v1/run/join", {"run_id": args.run_id, "peer_id": my_id})

        brain = RandomCitizenBrain(args.seed, my_id)
        pending_commits: deque[str] = deque()
        pending_accepts: set[str] = set()

        def drain_inbox() -> None:
            while True:
                got = recv_raw(bridge)
                if not got:
                    break
                _from, data = got
                try:
                    m = json.loads(data.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if m.get("village") != "v1":
                    continue
                if m.get("msg") == "trade_accept" and m.get("offer_id"):
                    pending_accepts.add(str(m["offer_id"]))
                    continue
                if m.get("msg") == "trade_offer" and m.get("to") == my_id:
                    oid = str(m.get("offer_id", ""))
                    give = int(m.get("give_amount", 0))
                    want = int(m.get("want_amount", 0))
                    st = _get(f"{orch}/v1/state?run_id={args.run_id}")
                    bal = int(st.get("balances", {}).get(my_id, 0))
                    ok = (
                        bal >= want
                        and give > 0
                        and want > 0
                        and brain.rng.random() < 0.7
                    )
                    if ok:
                        send_raw(
                            bridge,
                            _from,
                            enc_village({"village": "v1", "msg": "trade_accept", "offer_id": oid}),
                        )
                        pending_commits.append(oid)
                    else:
                        send_raw(
                            bridge,
                            _from,
                            enc_village({"village": "v1", "msg": "trade_reject", "offer_id": oid}),
                        )

        run_done = False
        while not run_done:
            for _ in range(20):
                gs.tick()
                drain_inbox()
                time.sleep(0.05)
            try:
                st = _get(f"{orch}/v1/state?run_id={args.run_id}")
            except (urllib.error.URLError, json.JSONDecodeError):
                continue
            phase = st.get("phase")
            epoch = int(st.get("current_epoch", -1))
            max_ep = int(st.get("max_epochs", 999999))
            if phase == "idle":
                continue
            if (
                phase == "closed"
                and max_ep > 0
                and epoch == max_ep - 1
            ):
                run_done = True
                break
            if phase != "action":
                continue

            env = gossip_policy_payload(gs, topic, args.run_id, epoch, timeout=60.0)
            if not env:
                print("no policy gossip for epoch", epoch, flush=True)
                _json_post(
                    f"{orch}/v1/epoch/complete",
                    {"run_id": args.run_id, "peer_id": my_id},
                )
                continue

            sess = mcp_init(bridge, args.yellow_pages_peer_id)
            peer_candidates = list_peer_citizens(
                bridge, args.yellow_pages_peer_id, sess, my_id
            )
            for p in peer_candidates:
                gs.add_peer(p)

            n_actions = int(st.get("actions_per_epoch", 5))
            earn_cap = 100
            while True:
                drain_inbox()
                gs.tick()
                st = _get(f"{orch}/v1/state?run_id={args.run_id}")
                if st.get("phase") != "action":
                    break
                bal = int(st.get("balances", {}).get(my_id, 0))
                used = int(st.get("slots_used", {}).get(my_id, 0))
                if used >= n_actions:
                    break
                eu = int(st.get("earn_used", {}).get(my_id, 0))
                earn_remaining = max(0, earn_cap - eu)
                if pending_commits:
                    oid = pending_commits.popleft()
                    try:
                        _json_post(
                            f"{orch}/v1/action",
                            {
                                "run_id": args.run_id,
                                "peer_id": my_id,
                                "action": {"type": "trade_commit", "offer_id": oid},
                            },
                        )
                    except urllib.error.HTTPError as e:
                        print("trade_commit", e.read().decode(), flush=True)
                    continue

                kind, payload = brain.pick(
                    peer_candidates=peer_candidates,
                    balance=bal,
                    earn_remaining=earn_remaining,
                )
                if kind == "trade":
                    cp = str(payload["counterparty"])
                    oid = str(payload["offer_id"])
                    send_raw(
                        bridge,
                        cp,
                        enc_village(
                            {
                                "village": "v1",
                                "msg": "trade_offer",
                                "offer_id": oid,
                                "run_id": args.run_id,
                                "epoch": epoch,
                                "from": my_id,
                                "to": cp,
                                "give_amount": int(payload["give_amount"]),
                                "want_amount": int(payload["want_amount"]),
                            }
                        ),
                    )
                    t0 = time.time()
                    accepted = False
                    while time.time() - t0 < 15.0:
                        drain_inbox()
                        if oid in pending_accepts:
                            pending_accepts.discard(oid)
                            accepted = True
                            break
                        got = recv_raw(bridge)
                        if not got:
                            time.sleep(0.05)
                            continue
                        frm, data = got
                        try:
                            r = json.loads(data.decode("utf-8"))
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue
                        if (
                            r.get("village") == "v1"
                            and r.get("msg") == "trade_accept"
                            and r.get("offer_id") == oid
                        ):
                            accepted = True
                            break
                        if r.get("msg") == "trade_reject" and r.get("offer_id") == oid:
                            break
                    if accepted:
                        try:
                            _json_post(
                                f"{orch}/v1/action",
                                {
                                    "run_id": args.run_id,
                                    "peer_id": my_id,
                                    "action": {
                                        "type": "trade_prepare",
                                        "offer_id": oid,
                                        "counterparty": cp,
                                        "give_amount": int(payload["give_amount"]),
                                        "want_amount": int(payload["want_amount"]),
                                    },
                                },
                            )
                        except urllib.error.HTTPError as e:
                            print("trade_prepare", e.read().decode(), flush=True)
                else:
                    try:
                        _json_post(
                            f"{orch}/v1/action",
                            {
                                "run_id": args.run_id,
                                "peer_id": my_id,
                                "action": payload,
                            },
                        )
                    except urllib.error.HTTPError:
                        pass

            _json_post(
                f"{orch}/v1/epoch/complete",
                {"run_id": args.run_id, "peer_id": my_id},
            )
            while True:
                try:
                    st2 = _get(f"{orch}/v1/state?run_id={args.run_id}")
                except (urllib.error.URLError, json.JSONDecodeError):
                    time.sleep(0.1)
                    continue
                if st2.get("phase") != "action" or int(st2.get("current_epoch", -99)) != epoch:
                    break
                time.sleep(0.15)
        cleanup()
    finally:
        cfg_path.unlink(missing_ok=True)

    print("citizen exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
