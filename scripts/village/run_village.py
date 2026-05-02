#!/usr/bin/env python3
"""
Single-process village simulation — AXL P2P trades, GossipSub policy, no Yellow Pages.

Citizens run as threading.Threads in the same process, talking to
Docker services via HTTP.  AXL nodes are already running inside Docker.

Usage:
  docker compose --profile mesh up -d
  python scripts/village/run_village.py
  python scripts/village/run_village.py --epochs 4 --actions 8
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from village_axl import recv_raw, send_raw, load_gossip_sub, bridge_gossip_fns, policy_topic

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── helpers ───────────────────────────────────────────────────────

def _json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def gini_coefficient(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    xs = sorted(max(0.0, float(x)) for x in values)
    n = len(xs)
    cum = s = 0.0
    for i, x in enumerate(xs, start=1):
        s += x
        cum += i * x
    if s <= 0:
        return 0.0
    return (2.0 * cum / (n * s)) - (n + 1.0) / n


def next_policy(
    prev: dict[str, Any],
    gini: float,
    *,
    multiplier: float = 0.2,
    ubi_multiplier: float = 20.0,
    target: float = 0.05,
) -> dict[str, Any]:
    tax = float(prev.get("wealth_tax_rate", 0.1))
    ubi = int(prev.get("ubi", 5))
    error = gini - target
    tax = max(0.02, min(0.5, round(tax + error * multiplier, 4)))
    ubi = max(0, min(50, ubi + round(error * ubi_multiplier)))
    return {"wealth_tax_rate": tax, "ubi": ubi}


# ── citizen brain (random) ────────────────────────────────────────

RESOURCES = ["coin", "wood", "stone", "grain"]


def enc_village(msg: dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def gossip_policy(gs: Any, gs_lock: threading.Lock, topic: str, run_id: str, want_epoch: int, timeout: float) -> dict[str, Any] | None:
    import base64
    deadline = time.time() + timeout
    while time.time() < deadline:
        with gs_lock:
            for mid in list(gs._received):
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


class CitizenBrain:
    def __init__(self, seed: int, peer_id: str) -> None:
        h = hashlib.sha256(f"{seed}:{peer_id}".encode()).digest()
        self.rng = random.Random(int.from_bytes(h[:8], "big"))

    def pick_action(
        self,
        peer_candidates: list[str],
        resources: dict[str, int],
        earn_remaining: int,
    ) -> dict[str, Any]:
        r = self.rng.random()
        noop_p = 0.45 if not peer_candidates else 0.2
        if not peer_candidates or r < noop_p:
            return {"type": "noop"}
        if r < 0.65 and earn_remaining > 0:
            resource = self.rng.choice(RESOURCES)
            amt = min(self.rng.randint(1, 15), earn_remaining)
            return {"type": "earn", "resource": resource, "amount": amt}
        cp = self.rng.choice(peer_candidates)
        give_resource = self.rng.choice(RESOURCES)
        want_resource = self.rng.choice([r for r in RESOURCES if r != give_resource])
        give = max(1, min(resources.get(give_resource, 0), self.rng.randint(1, 10)))
        want = max(1, self.rng.randint(1, 10))
        return {
            "type": "trade_offer",
            "counterparty": cp,
            "give_resource": give_resource,
            "give_amount": give,
            "want_resource": want_resource,
            "want_amount": want,
        }


# ── citizen agent (thread, no subprocess) ─────────────────────────

class CitizenAgent:
    def __init__(
        self,
        peer_id: str,
        orch_url: str,
        bridge_url: str,
        seed: int,
        earn_cap: int = 100,
    ) -> None:
        self.peer_id = peer_id
        self.orch_url = orch_url
        self.bridge_url = bridge_url
        self.earn_cap = earn_cap
        self.brain = CitizenBrain(seed, peer_id)
        self.actions_log: list[dict[str, Any]] = []
        self._pending_accepts: set[str] = set()
        self._pending_commits: list[str] = []
        self._policy: dict[str, Any] | None = None

        GossipSub, GossipConfig = load_gossip_sub(REPO_ROOT)
        send_fn, recv_fn = bridge_gossip_fns(bridge_url)
        self._gs = GossipSub(GossipConfig(), peer_id, send_fn, recv_fn)
        self._gs_lock = threading.Lock()
        self._tick_running = True
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def _tick_loop(self) -> None:
        while getattr(self, '_tick_running', True):
            try:
                with self._gs_lock:
                    self._gs.tick()
            except Exception:
                pass
            time.sleep(0.05)

    def _stop_tick(self) -> None:
        self._tick_running = False

    # ── orchestrator helpers ──────────────────────────────────────
    def state(self, run_id: str) -> dict[str, Any]:
        return _json(f"{self.orch_url}/v1/state?run_id={run_id}")

    def do_action(self, run_id: str, action: dict[str, Any]) -> dict[str, Any]:
        return _post(
            f"{self.orch_url}/v1/action",
            {"run_id": run_id, "peer_id": self.peer_id, "action": action},
        )

    def _drain_inbox(self, run_id: str) -> None:
        with self._gs_lock:
            self._gs.tick()
        while True:
            got = recv_raw(self.bridge_url)
            if not got:
                break
            _from, data = got
            try:
                msg = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if msg.get("village") != "v1":
                continue
            if msg.get("msg") == "trade_accept" and msg.get("offer_id"):
                self._pending_accepts.add(str(msg["offer_id"]))
                continue
            if msg.get("msg") == "trade_offer" and msg.get("to") == self.peer_id:
                oid = str(msg.get("offer_id", ""))
                want_resource = str(msg.get("want_resource", "coin"))
                want_amount = int(msg.get("want_amount", 0))
                give_amount = int(msg.get("give_amount", 0))
                st = self.state(run_id)
                resources = st.get("resources", {}).get(self.peer_id, {})
                have_amt = int(resources.get(want_resource, 0))
                ok = have_amt >= want_amount and want_amount > 0 and give_amount > 0 and self.brain.rng.random() < 0.7
                if ok:
                    send_raw(self.bridge_url, _from,
                        enc_village({"village": "v1", "msg": "trade_accept", "offer_id": oid}))
                    self._pending_commits.append(oid)
                else:
                    send_raw(self.bridge_url, _from,
                        enc_village({"village": "v1", "msg": "trade_reject", "offer_id": oid}))

    def epoch_complete(self, run_id: str) -> dict[str, Any]:
        return _post(
            f"{self.orch_url}/v1/epoch/complete",
            {"run_id": run_id, "peer_id": self.peer_id},
        )

    def _my_resources(self, st: dict[str, Any]) -> dict[str, int]:
        raw = st.get("resources", {}).get(self.peer_id, {})
        return {r: int(raw.get(r, 0)) for r in RESOURCES}

    def run_epoch(self, run_id: str, epoch: int, n_actions: int, all_peer_ids: list[str] | None = None) -> None:
        self.actions_log.clear()
        self._pending_accepts.clear()
        self._pending_commits.clear()

        # Subscribe to GossipSub policy topic for this run
        topic = policy_topic(run_id)
        self._gs.subscribe(topic)
        # Seed GossipSub mesh with ALL peer IDs for routing
        if all_peer_ids:
            for pid in all_peer_ids:
                self._gs.add_peer(pid)

        # Try to get policy from GossipSub first, fall back to orchestrator
        env = gossip_policy(self._gs, self._gs_lock, topic, run_id, epoch, timeout=0.5)
        if env:
            self._policy = env.get("policy")
            print(f"  [gossip] citizen {self.peer_id[:16]}… policy via GossipSub epoch={epoch}")
        else:
            st = self.state(run_id)
            self._policy = st.get("policy")
            print(f"  [gossip] citizen {self.peer_id[:16]}… policy from orchestrator epoch={epoch}")

        st = self.state(run_id)
        my_res = self._my_resources(st)

        self._log("dummy", {"why": "always_on_epoch_start"})
        self.do_action(run_id, {"type": "dummy", "why": "always_on_epoch_start"})

        peer_candidates = [
            p for p in (st.get("enrolled") or [])
            if p.lower() != self.peer_id
        ]
        earn_used = 0

        while True:
            st = self.state(run_id)
            if st.get("phase") != "action":
                break
            used = int(st.get("slots_used", {}).get(self.peer_id, 0))
            if used >= n_actions:
                break
            my_res = self._my_resources(st)
            earn_remaining = max(0, self.earn_cap - earn_used)

            self._drain_inbox(run_id)

            # pending commits (counterparty accepted our trade_prepare, or incoming offer accepted)
            if self._pending_commits:
                oid = self._pending_commits.pop(0)
                out = self.do_action(run_id, {"type": "trade_commit", "offer_id": oid})
                if out.get("decision") == "applied":
                    self._log("trade_commit", {"offer_id": oid, "executed": True})
                continue

            # pick fresh action
            action_def = self.brain.pick_action(
                peer_candidates, my_res, earn_remaining
            )
            kind = action_def["type"]

            if kind == "noop":
                self._log("noop", {})
                self.do_action(run_id, action_def)

            elif kind == "earn":
                resource = action_def.get("resource", "coin")
                take = min(action_def["amount"], earn_remaining)
                if take > 0:
                    self._log("earn", {"resource": resource, "amount": take})
                    out = self.do_action(run_id, {"type": "earn", "resource": resource, "amount": take})
                    if out.get("decision") == "applied":
                        earn_used += take

            elif kind == "trade_offer":
                cp = action_def["counterparty"]
                give_resource = action_def.get("give_resource", "coin")
                give_amount = action_def.get("give_amount", 0)
                want_resource = action_def.get("want_resource", "coin")
                want_amount = action_def.get("want_amount", 0)
                oid = f"o{self.brain.rng.getrandbits(48):012x}"

                out = self.do_action(run_id, {
                    "type": "trade_prepare",
                    "offer_id": oid,
                    "counterparty": cp,
                    "give_resource": give_resource,
                    "give_amount": give_amount,
                    "want_resource": want_resource,
                    "want_amount": want_amount,
                })
                if out.get("decision") == "applied":
                    send_raw(self.bridge_url, cp,
                        enc_village({
                            "village": "v1", "msg": "trade_offer",
                            "offer_id": oid, "run_id": run_id,
                            "from": self.peer_id, "to": cp,
                            "give_resource": give_resource, "give_amount": give_amount,
                            "want_resource": want_resource, "want_amount": want_amount,
                            "epoch": epoch,
                        }))
                    t0 = time.time()
                    accepted = False
                    trade_wait = 6.0
                    while time.time() - t0 < trade_wait:
                        self._drain_inbox(run_id)
                        if oid in self._pending_accepts:
                            self._pending_accepts.discard(oid)
                            accepted = True
                            break
                        time.sleep(0.05)
                    self._log("trade_offer", {
                        "counterparty": cp,
                        "give_resource": give_resource, "give": give_amount,
                        "want_resource": want_resource, "want": want_amount,
                        "accepted": accepted,
                    })
                    if accepted:
                        self._pending_commits.append(oid)

        self.epoch_complete(run_id)

    def _log(self, kind: str, extra: dict[str, Any]) -> None:
        self.actions_log.append({
            "citizen": self.peer_id,
            "slot": len(self.actions_log) + 1,
            "action": kind,
            **extra,
        })


# ── main ──────────────────────────────────────────────────────────

def discover_peers(
    ports: list[int],
    names: list[str] | None = None,
    *,
    host: str = "localhost",
    timeout_per_port: float = 30.0,
) -> dict[str, str]:
    """Query each bridge /topology, return dict of names → peer_id."""
    if names is None:
        names = [f"p{p}" for p in ports]
    result: dict[str, str] = {}
    for port, name in zip(ports, names):
        t0 = time.time()
        pk = ""
        while time.time() - t0 < timeout_per_port:
            try:
                r = _json(f"http://{host}:{port}/topology")
                pk = r.get("our_public_key", "")
                if pk:
                    result[name] = pk.lower()
                    break
            except Exception:
                pass
            time.sleep(0.3)
        print(f"[discover] {name}={pk[:16] if pk else 'N/A'}… (port {port})")
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Single-process village simulation")
    p.add_argument("--run-id", default="village_run")
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--actions-per-epoch", type=int, default=5)
    p.add_argument("--initial-balance", type=int, default=100)
    p.add_argument("--initial-tax", type=float, default=0.1)
    p.add_argument("--initial-ubi", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--orch-url", default="http://localhost:9200")
    p.add_argument("--num-citizens", type=int, default=10,
                   help="Number of citizen agents (default 10)")
    p.add_argument("--mesh-ports", type=int, nargs="*", default=None,
                   help="AXL bridge ports (auto-derived from --num-citizens if omitted)")
    p.add_argument("--tax-adjust", type=float, default=5.0,
                   help="Tax adjustment rate per unit of gini error (default 5.0)")
    p.add_argument("--ubi-adjust", type=float, default=100.0,
                   help="UBI adjustment rate per unit of gini error (default 100)")
    p.add_argument("--gini-target", type=float, default=0.05,
                   help="Target Gini coefficient (default 0.05)")
    p.add_argument("--runs-dir", type=Path,
                   default=Path(__file__).resolve().parent / "runs")
    args = p.parse_args()

    nc = max(1, args.num_citizens)
    run_dir = args.runs_dir / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    orch = args.orch_url.rstrip("/")

    # ── build port list ──────────────────────────────────────────
    if args.mesh_ports is not None:
        mesh_ports = list(args.mesh_ports)
    else:
        mesh_ports = [9002, 9004] + [9012 + i for i in range(nc)]
    port_names = (["yellow_pages_peer_id", "mayor_peer_id"]
                  + [f"citizen_{i}_peer_id" for i in range(nc)])

    # ── discover peers from mesh ──────────────────────────────────
    print(f"[main] Discovering {len(mesh_ports)} mesh peers…")
    peers = discover_peers(mesh_ports, port_names)
    yp_id = peers.get("yellow_pages_peer_id", "")
    citizen_ids = [peers.get(f"citizen_{i}_peer_id", "") for i in range(nc)]
    missing = [i for i, p in enumerate(citizen_ids) if not p]
    if not yp_id or missing:
        print(f"[main] ERROR: mesh not ready (missing {len(missing)} citizens)")
        return 1

    # ── create run ────────────────────────────────────────────────
    try:
        _post(f"{orch}/v1/run/delete", {"run_id": args.run_id})
    except urllib.error.HTTPError:
        pass

    # ── init GossipSub for town hall (mayor's bridge) ────────────
    mayor_bridge = "http://localhost:9004"
    mayor_topo = _json(f"{mayor_bridge}/topology")
    mayor_id = str(mayor_topo.get("our_public_key", "")).strip().lower()
    GossipSub, GossipConfig = load_gossip_sub(REPO_ROOT)
    mayor_send, mayor_recv = bridge_gossip_fns(mayor_bridge)
    town_hall_gs = GossipSub(GossipConfig(), mayor_id, mayor_send, mayor_recv)
    gossip_topic = policy_topic(args.run_id)
    town_hall_gs.subscribe(gossip_topic)
    # Seed with ALL known peer IDs for GossipSub mesh routing
    for pid in citizen_ids:
        town_hall_gs.add_peer(pid)

    create = _post(f"{orch}/v1/run/create", {
        "run_id": args.run_id,
        "max_epochs": args.epochs,
        "actions_per_epoch": args.actions_per_epoch,
        "initial_balance": args.initial_balance,
        "citizens": citizen_ids,
    })
    print(f"[main] Run {args.run_id} created  enrolled={len(create.get('enrolled', []))}")

    # ── register agents + join ────────────────────────────────────
    agents = [
        CitizenAgent(
            citizen_ids[i], orch,
            bridge_url=f"http://localhost:{mesh_ports[2 + i]}",
            seed=args.seed + i,
        )
        for i in range(nc)
    ]
    for a in agents:
        bal = _post(f"{orch}/v1/run/join", {"run_id": args.run_id, "peer_id": a.peer_id})
        print(f"[main] {a.peer_id[:16]}… joined  balance={bal.get('balance')}")

    policy: dict[str, Any] = {
        "wealth_tax_rate": args.initial_tax,
        "ubi": args.initial_ubi,
    }
    series: list[dict[str, Any]] = []

    # ── epoch loop ────────────────────────────────────────────────
    for epoch in range(args.epochs):
        print(f"\n{'='*50}")
        print(f"Epoch {epoch}")
        print(f"{'='*50}")
        print(f"policy: tax={policy['wealth_tax_rate']} ubi={policy['ubi']}")

        _post(f"{orch}/v1/epoch/open", {
            "run_id": args.run_id, "epoch": epoch, "policy": policy,
        })

        # Publish policy via GossipSub
        envelope = {
            "run_id": args.run_id, "epoch": epoch, "policy": dict(policy),
        }
        payload = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        town_hall_gs.publish(gossip_topic, payload)
        # Tick to flush IHAVE/IWANT
        for _ in range(5):
            town_hall_gs.tick()
            time.sleep(0.01)
        print(f"[epoch {epoch}] Running citizens… (policy published via GossipSub)")

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(agents)) as pool:
            futures = [
                pool.submit(a.run_epoch, args.run_id, epoch, args.actions_per_epoch, citizen_ids)
                for a in agents
            ]
            wait(futures)
            for f in futures:
                exc = f.exception()
                if exc:
                    print(f"[epoch {epoch}] Citizen error: {exc}")

        print(f"[epoch {epoch}] Actions done in {time.perf_counter()-t0:.2f}s — waiting for quorum…")

        deadline = time.time() + 30.0
        while time.time() < deadline:
            st = _json(f"{orch}/v1/state?run_id={args.run_id}")
            if st.get("phase") != "action":
                break
            enrolled = set(st.get("enrolled") or [])
            done = set(st.get("epoch_complete") or [])
            if enrolled and enrolled.issubset(done):
                break
            time.sleep(0.1)

        snap = _post(f"{orch}/v1/epoch/close", {"run_id": args.run_id})
        gini = float(snap.get("gini", 0.0))
        balances = snap.get("balances", {})
        pre_tax = snap.get("pre_tax_balances", {})

        actions_log: list[dict[str, Any]] = []
        for a in agents:
            actions_log.extend(a.actions_log)

        print(f"pre-tax : {pre_tax}")
        print(f"post-tax: {balances}")
        print(f"Gini    : {gini:.4f}")
        print(f"actions : {len(actions_log)} total")

        snap_with_log = dict(snap)
        snap_with_log["actions_log"] = actions_log

        snap_path = run_dir / f"snapshot_epoch_{epoch:04d}.json"
        snap_path.write_text(json.dumps(snap_with_log, indent=2) + "\n", encoding="utf-8")

        series.append({
            "epoch": epoch,
            "gini": gini,
            "policy_applied": dict(policy),
            "balances": balances,
            "pre_tax_balances": pre_tax,
            "resources": snap.get("resources", {}),
            "wealth": snap.get("wealth", {}),
            "actions_log": actions_log,
        })
        policy = next_policy(policy, gini, multiplier=args.tax_adjust, ubi_multiplier=args.ubi_adjust, target=args.gini_target)

    # ── write summary ────────────────────────────────────────────
    summary = {
        "run_id": args.run_id,
        "max_epochs": args.epochs,
        "actions_per_epoch": args.actions_per_epoch,
        "citizen_peer_ids": citizen_ids,
        "gini_timeseries": series,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out_path = run_dir / "gini_timeseries.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
