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
import logging
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

LOG = logging.getLogger("citizen")

# ~2 × 20ms ≈ 40ms between /v1/state polls when idle.
_CITIZEN_POLL_BATCH = 2
_CITIZEN_POLL_SLEEP = 0.02

# Yellow Pages MCP can be slow right after the AXL node boots; avoid hanging forever.
_MCP_HTTP_TIMEOUT = 15.0
_MCP_START_ATTEMPTS = 8
_MCP_START_DELAY_SEC = 1.0


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


def _mcp_endpoint(bridge: str, yp: str, *, mcp_http_url: str | None) -> str:
    """FastMCP Yellow Pages: use direct URL, or AXL bridge path /mcp/<yp>/directory (needs router/mesh)."""
    u = (mcp_http_url or "").strip()
    if u:
        return u.rstrip("/")
    pid = yp.strip().lower()
    return f"{bridge.rstrip('/')}/mcp/{pid}/directory"


def mcp_init(
    bridge: str,
    yp: str,
    *,
    mcp_http_url: str | None = None,
    timeout: float = _MCP_HTTP_TIMEOUT,
) -> str:
    url = _mcp_endpoint(bridge, yp, mcp_http_url=mcp_http_url)
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
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            sess = (hdrs.get("mcp-session-id") or "").strip()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(
            f"MCP initialize HTTP {e.code} at {url}: {detail[:800]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"MCP initialize unreachable at {url} (check --bridge {bridge} or --mcp-http-url): {e}"
        ) from e
    msg = json.loads(raw)
    if "error" in msg:
        raise RuntimeError(str(msg["error"]))
    # Yellow Pages FastMCP uses stateless_http=True — no header on direct :9105/mcp.
    # AXL node bridge initialize still returns Mcp-Session-Id; omit header on calls if empty.
    return sess


def mcp_init_retry(
    bridge: str,
    yp: str,
    *,
    mcp_http_url: str | None = None,
    attempts: int = _MCP_START_ATTEMPTS,
    delay: float = _MCP_START_DELAY_SEC,
    timeout: float = _MCP_HTTP_TIMEOUT,
) -> str:
    """Initialize MCP session with backoff (node / router may need a few seconds)."""
    url = _mcp_endpoint(bridge, yp, mcp_http_url=mcp_http_url)
    last: BaseException | None = None
    for i in range(attempts):
        try:
            if i:
                LOG.info("Yellow Pages MCP retry %s/%s → %s", i + 1, attempts, url)
            else:
                LOG.info("Yellow Pages MCP initialize → %s", url)
            return mcp_init(bridge, yp, mcp_http_url=mcp_http_url, timeout=timeout)
        except (RuntimeError, urllib.error.URLError, OSError, TimeoutError) as e:
            last = e
            LOG.warning("MCP init attempt %s/%s failed: %s", i + 1, attempts, e)
            if i + 1 < attempts:
                time.sleep(delay)
    raise RuntimeError(
        f"Yellow Pages MCP failed after {attempts} attempts at {url}. "
        "If using a citizen --bridge URL, set --mcp-http-url to the local Yellow Pages server "
        "(e.g. http://127.0.0.1:9105/mcp) — /mcp/<peer>/directory on the node only works when "
        "AXL MCP routing to the mayor is configured. "
        "Check: (1) Yellow Pages MCP on 9105 (2) MCP router 9003 (3) --yellow-pages-peer-id. "
        f"Last error: {last}"
    ) from last


def mcp_call(
    bridge: str,
    yp: str,
    sess: str,
    name: str,
    args: dict[str, Any],
    rid: int,
    *,
    mcp_http_url: str | None = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
            "id": rid,
        }
    ).encode()
    url = _mcp_endpoint(bridge, yp, mcp_http_url=mcp_http_url)
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if sess:
        h["Mcp-Session-Id"] = sess
    req = urllib.request.Request(url, data=body, method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(
            f"MCP tools/call HTTP {e.code} {name} at {url}: {detail[:800]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"MCP tools/call {name} unreachable at {url}: {e}") from e
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


def list_peer_citizens(
    bridge: str,
    yp: str,
    sess: str,
    my_id: str,
    *,
    mcp_http_url: str | None = None,
) -> list[str]:
    raw = mcp_call(
        bridge,
        yp,
        sess,
        "list_peer_ids",
        {"role_filter": "citizen"},
        1,
        mcp_http_url=mcp_http_url,
    )
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
        # More noops when alone; with peers, bias toward real ledger actions.
        noop_p = 0.45 if not peer_candidates else 0.2
        if not peer_candidates or r < noop_p:
            return "noop", {"type": "noop"}
        if r < 0.65 and earn_remaining > 0:
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


def policy_from_orchestrator(
    orch: str,
    run_id: str,
    want_epoch: int,
) -> dict[str, Any] | None:
    """When GossipSub misses the mayor's publish, orchestrator still has epoch + policy."""
    try:
        st = _get(f"{orch}/v1/state?run_id={run_id}")
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        LOG.debug("policy_from_orchestrator GET state failed: %s", e)
        return None
    if st.get("phase") != "action":
        return None
    if int(st.get("current_epoch", -999)) != want_epoch:
        return None
    return {
        "run_id": run_id,
        "epoch": want_epoch,
        "policy": st.get("policy") or {},
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
    p.add_argument(
        "--mcp-http-url",
        default="",
        help=(
            "Direct Yellow Pages FastMCP URL, e.g. http://127.0.0.1:9105/mcp. "
            "Strongly recommended locally: citizen --bridge does not proxy /mcp/<mayor>/directory "
            "unless the node has router_addr set. Empty = use AXL path on --bridge."
        ),
    )
    p.add_argument("--orchestrator", default="http://127.0.0.1:9200")
    p.add_argument("--run-id", required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--keep-node", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="Log actions and state transitions")
    p.add_argument(
        "--trade-wait-sec",
        type=float,
        default=8.0,
        help="Max seconds to wait for counterparty trade_accept (default 8)",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
        force=True,
    )

    bridge = args.bridge.strip() or f"http://127.0.0.1:{args.api_port}"
    orch = args.orchestrator.rstrip("/")
    cwd = args.config_dir if args.config_dir else args.pem.parent
    mcp_http = args.mcp_http_url.strip() or None
    if mcp_http:
        LOG.info("Yellow Pages MCP: direct HTTP %s", mcp_http)
    else:
        LOG.info(
            "Yellow Pages MCP: via AXL %s/mcp/%s…/directory (timeouts? use --mcp-http-url)",
            bridge.rstrip("/"),
            args.yellow_pages_peer_id[:16],
        )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=cwd, prefix="citizen-node-"
    ) as tmp:
        cfg_path = Path(tmp.name)
    proc: subprocess.Popen | None = None
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
            if proc is None or proc.poll() is not None:
                return
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        topo = wait_topology(bridge)
        my_id = str(topo["our_public_key"]).strip().lower()
        LOG.info("peer_id=%s bridge=%s run_id=%s", my_id[:16] + "…", bridge, args.run_id)

        try:
            sess = mcp_init_retry(bridge, args.yellow_pages_peer_id, mcp_http_url=mcp_http)
        except RuntimeError as e:
            LOG.error("%s", e)
            return 1
        try:
            mcp_call(
                bridge,
                args.yellow_pages_peer_id,
                sess,
                "register_agent",
                {"peer_id": my_id, "role": "citizen", "caps": ["trade", "chat"]},
                2,
                mcp_http_url=mcp_http,
            )
        except RuntimeError as e:
            LOG.error("register_agent failed: %s", e)
            return 1

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

        join_out: dict[str, Any]
        try:
            join_out = _json_post(
                f"{orch}/v1/run/join", {"run_id": args.run_id, "peer_id": my_id}
            )
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            LOG.error(
                "orchestrator join FAILED run_id=%s peer=%s… HTTP %s %s",
                args.run_id,
                my_id[:16],
                e.code,
                body,
            )
            return 1
        LOG.info("orchestrator join ok balance=%s", join_out.get("balance"))

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
                        LOG.info(
                            "inbox trade_accept send epoch=%s offer_id=%s from=%s…",
                            m.get("epoch"),
                            oid,
                            str(_from)[:16],
                        )
                        send_raw(
                            bridge,
                            _from,
                            enc_village({"village": "v1", "msg": "trade_accept", "offer_id": oid}),
                        )
                        pending_commits.append(oid)
                    else:
                        LOG.info(
                            "inbox trade_reject send offer_id=%s from=%s… (bal=%s need=%s)",
                            oid,
                            str(_from)[:16],
                            bal,
                            want,
                        )
                        send_raw(
                            bridge,
                            _from,
                            enc_village({"village": "v1", "msg": "trade_reject", "offer_id": oid}),
                        )

        run_done = False
        while not run_done:
            for _ in range(_CITIZEN_POLL_BATCH):
                gs.tick()
                drain_inbox()
                time.sleep(_CITIZEN_POLL_SLEEP)
            try:
                st = _get(f"{orch}/v1/state?run_id={args.run_id}")
            except (urllib.error.URLError, json.JSONDecodeError):
                continue
            phase = st.get("phase")
            epoch = int(st.get("current_epoch", -1))
            max_ep = int(st.get("max_epochs", 999999))
            if phase == "idle":
                LOG.debug("poll: phase=idle (waiting for town hall to open epoch)")
                continue
            if (
                phase == "closed"
                and max_ep > 0
                and epoch == max_ep - 1
            ):
                run_done = True
                break
            if phase != "action":
                LOG.debug("poll: phase=%s epoch=%s (skip action loop)", phase, epoch)
                continue

            t_ep = time.perf_counter()
            LOG.info("epoch %s: action phase — fetch policy (orchestrator first; gossip only if needed)", epoch)
            env = policy_from_orchestrator(orch, args.run_id, epoch)
            if env:
                LOG.info(
                    "epoch %s: policy from orchestrator in %.3fs policy=%s",
                    epoch,
                    time.perf_counter() - t_ep,
                    env.get("policy"),
                )
            if not env:
                time.sleep(0.04)
                env = policy_from_orchestrator(orch, args.run_id, epoch)
                if env:
                    LOG.info(
                        "epoch %s: policy from orchestrator (retry) in %.3fs",
                        epoch,
                        time.perf_counter() - t_ep,
                    )
            if not env:
                LOG.warning(
                    "epoch %s: no policy on orchestrator yet after retry; trying GossipSub %.1fs",
                    epoch,
                    0.35,
                )
                env = gossip_policy_payload(gs, topic, args.run_id, epoch, timeout=0.35)
                if env:
                    LOG.info("epoch %s: policy via GossipSub after %.3fs", epoch, time.perf_counter() - t_ep)
            if not env:
                LOG.warning(
                    "epoch %s: no policy yet (gossip+orchestrator); completing epoch with 0 actions",
                    epoch,
                )
                _json_post(
                    f"{orch}/v1/epoch/complete",
                    {"run_id": args.run_id, "peer_id": my_id},
                )
                continue

            # Mandatory ledger touch: does not use Yellow Pages, Gossip, or RNG.
            t_dummy = time.perf_counter()
            try:
                out = _json_post(
                    f"{orch}/v1/action",
                    {
                        "run_id": args.run_id,
                        "peer_id": my_id,
                        "action": {"type": "dummy", "why": "always_on_epoch_start"},
                    },
                )
                LOG.info(
                    "ACTION dummy epoch=%s OK in %.3fs decision=%s balance=%s",
                    epoch,
                    time.perf_counter() - t_dummy,
                    out.get("decision"),
                    out.get("balance"),
                )
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                LOG.error(
                    "ACTION dummy epoch=%s FAILED HTTP %s: %s",
                    epoch,
                    e.code,
                    body,
                )

            try:
                sess = mcp_init_retry(
                    bridge,
                    args.yellow_pages_peer_id,
                    mcp_http_url=mcp_http,
                    attempts=4,
                    delay=0.75,
                )
                peer_candidates = list_peer_citizens(
                    bridge,
                    args.yellow_pages_peer_id,
                    sess,
                    my_id,
                    mcp_http_url=mcp_http,
                )
            except RuntimeError as e:
                LOG.error(
                    "epoch %s: Yellow Pages MCP failed (peer list unavailable): %s",
                    epoch,
                    e,
                )
                peer_candidates = []

            for p in peer_candidates:
                gs.add_peer(p)
            LOG.info(
                "epoch %s: Yellow Pages reports %d trade peers (excl. self): %s",
                epoch,
                len(peer_candidates),
                [p[:12] + "…" for p in peer_candidates[:6]],
            )

            n_actions = int(st.get("actions_per_epoch", 5))
            earn_cap = 100
            t_actions = time.perf_counter()
            LOG.info(
                "epoch %s: starting action loop (target %s slots) +%.3fs from action-phase detect",
                epoch,
                n_actions,
                t_actions - t_ep,
            )
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
                        out = _json_post(
                            f"{orch}/v1/action",
                            {
                                "run_id": args.run_id,
                                "peer_id": my_id,
                                "action": {"type": "trade_commit", "offer_id": oid},
                            },
                        )
                        LOG.info(
                            "ACTION trade_commit epoch=%s offer_id=%s slots=%s/%s out=%s",
                            epoch,
                            oid,
                            used + 1,
                            n_actions,
                            out,
                        )
                    except urllib.error.HTTPError as e:
                        LOG.error("trade_commit HTTP %s: %s", e.code, e.read().decode())
                    continue

                kind, payload = brain.pick(
                    peer_candidates=peer_candidates,
                    balance=bal,
                    earn_remaining=earn_remaining,
                )
                if kind == "trade":
                    cp = str(payload["counterparty"])
                    oid = str(payload["offer_id"])
                    LOG.info(
                        "ACTION trade_offer epoch=%s -> %s give=%s want=%s offer_id=%s slots=%s/%s",
                        epoch,
                        cp[:16] + "…",
                        int(payload["give_amount"]),
                        int(payload["want_amount"]),
                        oid,
                        used,
                        n_actions,
                    )
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
                    tw = float(args.trade_wait_sec)
                    while time.time() - t0 < tw:
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
                            out = _json_post(
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
                            LOG.info(
                                "ACTION trade_prepare epoch=%s offer_id=%s decision=%s slots=%s/%s",
                                epoch,
                                oid,
                                out.get("decision"),
                                used + 1,
                                n_actions,
                            )
                        except urllib.error.HTTPError as e:
                            LOG.error("trade_prepare HTTP %s: %s", e.code, e.read().decode())
                    else:
                        LOG.info(
                            "trade_offer epoch=%s offer_id=%s not accepted in time; no slot used",
                            epoch,
                            oid,
                        )
                else:
                    try:
                        out = _json_post(
                            f"{orch}/v1/action",
                            {
                                "run_id": args.run_id,
                                "peer_id": my_id,
                                "action": payload,
                            },
                        )
                        LOG.info(
                            "ACTION %s epoch=%s payload=%s slots=%s/%s decision=%s",
                            kind,
                            epoch,
                            payload,
                            used + 1,
                            n_actions,
                            out.get("decision"),
                        )
                    except urllib.error.HTTPError as e:
                        body = e.read().decode(errors="replace")
                        LOG.error(
                            "ACTION %s epoch=%s HTTP %s: %s",
                            kind,
                            epoch,
                            e.code,
                            body,
                        )

            LOG.info(
                "epoch %s: action loop finished in %.3fs — submitting epoch_complete",
                epoch,
                time.perf_counter() - t_actions,
            )
            try:
                cr = _json_post(
                    f"{orch}/v1/epoch/complete",
                    {"run_id": args.run_id, "peer_id": my_id},
                )
            except urllib.error.HTTPError as e:
                LOG.error(
                    "epoch %s: epoch_complete HTTP %s %s",
                    epoch,
                    e.code,
                    e.read().decode(errors="replace"),
                )
                raise
            LOG.info(
                "epoch %s: epoch_complete ok — orchestrator reports %s/%s citizens done "
                "(town hall closes epoch after all enrollments complete; then Gini snapshot is written)",
                epoch,
                cr.get("completed_peers"),
                cr.get("enrolled"),
            )
            t_wait_start = time.perf_counter()
            last_slow_log = t_wait_start
            while True:
                try:
                    st2 = _get(f"{orch}/v1/state?run_id={args.run_id}")
                except (urllib.error.URLError, json.JSONDecodeError):
                    time.sleep(0.1)
                    continue
                if st2.get("phase") != "action" or int(st2.get("current_epoch", -99)) != epoch:
                    elapsed = time.perf_counter() - t_wait_start
                    LOG.info(
                        "epoch %s: leaving action wait phase=%s current_epoch=%s after %.3fs "
                        "(post epoch_complete)",
                        epoch,
                        st2.get("phase"),
                        st2.get("current_epoch"),
                        elapsed,
                    )
                    hist = st2.get("gini_history") or []
                    if isinstance(hist, list) and hist:
                        LOG.info(
                            "epoch %s: cumulative Gini history (latest = last closed epoch): %s",
                            epoch,
                            hist,
                        )
                    break
                now = time.perf_counter()
                if now - last_slow_log >= 10.0:
                    ec = st2.get("epoch_complete") or []
                    en = st2.get("enrolled") or []
                    last_slow_log = now
                    LOG.info(
                        "epoch %s: waiting for town hall /epoch/close (~%.0fs since epoch_complete) — "
                        "orchestrator epoch_quorum_ready=%s | epoch_complete %d/%d (registered roster)",
                        epoch,
                        now - t_wait_start,
                        st2.get("epoch_quorum_ready"),
                        len(ec),
                        len(en),
                    )
                time.sleep(0.05)
        cleanup()
    finally:
        cfg_path.unlink(missing_ok=True)

    LOG.info("citizen exit run_id=%s", args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
