#!/usr/bin/env python3
"""
Single-process village simulation — no subprocesses, no GossipSub.

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


def _mcp(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
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


def next_policy(prev: dict[str, Any], gini: float) -> dict[str, Any]:
    tax = float(prev.get("wealth_tax_rate", 0.1))
    ubi = int(prev.get("ubi", 5))
    if gini > 0.35:
        tax = min(0.45, tax + 0.02)
    else:
        tax = max(0.02, tax - 0.02)
    return {"wealth_tax_rate": round(tax, 4), "ubi": ubi}


# ── citizen brain (random) ────────────────────────────────────────

class CitizenBrain:
    def __init__(self, seed: int, peer_id: str) -> None:
        h = hashlib.sha256(f"{seed}:{peer_id}".encode()).digest()
        self.rng = random.Random(int.from_bytes(h[:8], "big"))

    def pick_action(
        self,
        peer_candidates: list[str],
        balance: int,
        earn_remaining: int,
    ) -> dict[str, Any]:
        r = self.rng.random()
        noop_p = 0.45 if not peer_candidates else 0.2
        if not peer_candidates or r < noop_p:
            return {"type": "noop"}
        if r < 0.65 and earn_remaining > 0:
            amt = min(self.rng.randint(1, 15), earn_remaining)
            return {"type": "earn", "amount": amt}
        cp = self.rng.choice(peer_candidates)
        give = min(balance, max(1, self.rng.randint(1, min(10, max(1, balance)))))
        want = max(1, self.rng.randint(1, 10))
        return {
            "type": "trade_offer",
            "counterparty": cp,
            "give_amount": give,
            "want_amount": want,
        }


# ── in-memory trade exchange ──────────────────────────────────────

class TradeExchange:
    """Thread-safe offer/accept exchange between citizen threads."""

    def __init__(self) -> None:
        self._offers: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}

    def make_offer(
        self,
        offer_id: str,
        from_pid: str,
        to_pid: str,
        give: int,
        want: int,
        timeout: float = 6.0,
    ) -> bool:
        evt = threading.Event()
        with self._lock:
            self._offers[offer_id] = {
                "from": from_pid, "to": to_pid,
                "give": give, "want": want,
            }
            self._events[offer_id] = evt
        try:
            return evt.wait(timeout=timeout)
        finally:
            with self._lock:
                self._offers.pop(offer_id, None)
                self._events.pop(offer_id, None)

    def incoming_offers(self, to_pid: str) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            return [
                (oid, dict(o))
                for oid, o in self._offers.items()
                if o["to"] == to_pid
            ]

    def accept_offer(self, offer_id: str) -> bool:
        with self._lock:
            evt = self._events.get(offer_id)
            if evt is not None:
                evt.set()
                return True
            return False


# ── citizen agent (thread, no subprocess) ─────────────────────────

class CitizenAgent:
    def __init__(
        self,
        peer_id: str,
        orch_url: str,
        yp_url: str,
        seed: int,
        exchange: TradeExchange,
        earn_cap: int = 100,
    ) -> None:
        self.peer_id = peer_id
        self.orch_url = orch_url
        self.yp_url = yp_url
        self.exchange = exchange
        self.earn_cap = earn_cap
        self.brain = CitizenBrain(seed, peer_id)
        self.actions_log: list[dict[str, Any]] = []

    # ── Yellow Pages helpers ─────────────────────────────────────
    def register_yp(self) -> None:
        _mcp(self.yp_url, {
            "jsonrpc": "2.0", "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "citizen", "version": "0.1"},
            },
            "id": 0,
        })
        _mcp(self.yp_url, {
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {
                "name": "register_agent",
                "arguments": {
                    "peer_id": self.peer_id,
                    "role": "citizen",
                    "caps": ["trade", "chat"],
                },
            },
            "id": 1,
        })

    def list_peers_yp(self) -> list[str]:
        raw = _mcp(self.yp_url, {
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {
                "name": "list_peer_ids",
                "arguments": {"role_filter": "citizen"},
            },
            "id": 1,
        })
        content = (raw.get("result") or {}).get("content") or []
        if content and isinstance(content[0], dict) and content[0].get("type") == "text":
            try:
                obj = json.loads(content[0]["text"])
                return [p for p in obj.get("peer_ids", []) if p.lower() != self.peer_id]
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    # ── orchestrator helpers ──────────────────────────────────────
    def state(self, run_id: str) -> dict[str, Any]:
        return _json(f"{self.orch_url}/v1/state?run_id={run_id}")

    def do_action(self, run_id: str, action: dict[str, Any]) -> dict[str, Any]:
        return _post(
            f"{self.orch_url}/v1/action",
            {"run_id": run_id, "peer_id": self.peer_id, "action": action},
        )

    def epoch_complete(self, run_id: str) -> dict[str, Any]:
        return _post(
            f"{self.orch_url}/v1/epoch/complete",
            {"run_id": run_id, "peer_id": self.peer_id},
        )

    def run_epoch(self, run_id: str, epoch: int, n_actions: int) -> None:
        self.actions_log.clear()
        st = self.state(run_id)
        bal = int(st.get("balances", {}).get(self.peer_id, 0))

        self._log("dummy", {"why": "always_on_epoch_start"})
        self.do_action(run_id, {"type": "dummy", "why": "always_on_epoch_start"})

        peer_candidates = self.list_peers_yp()
        earn_used = 0
        pending_commits: list[str] = []
        completed = set()

        while True:
            st = self.state(run_id)
            if st.get("phase") != "action":
                break
            used = int(st.get("slots_used", {}).get(self.peer_id, 0))
            if used >= n_actions:
                break
            bal = int(st.get("balances", {}).get(self.peer_id, 0))
            earn_remaining = max(0, self.earn_cap - earn_used)

            # pending commits (counterparty accepted our trade_prepare)
            if pending_commits:
                oid = pending_commits.pop(0)
                self._log("trade_commit", {"offer_id": oid})
                self.do_action(run_id, {"type": "trade_commit", "offer_id": oid})
                continue

            # incoming trade offers — counterparty must call trade_commit
            handled = False
            for oid, off in self.exchange.incoming_offers(self.peer_id):
                if bal >= off["want"] and self.brain.rng.random() < 0.7:
                    self.exchange.accept_offer(oid)
                    out = self.do_action(run_id, {
                        "type": "trade_commit",
                        "offer_id": oid,
                    })
                    self._log("trade_accept", {
                        "from": off["from"],
                        "give": off["give"],
                        "want": off["want"],
                        "executed": out.get("decision") == "applied",
                    })
                    handled = True
                    break
            if handled:
                continue

            # pick fresh action
            action_def = self.brain.pick_action(
                peer_candidates, bal, earn_remaining
            )
            kind = action_def["type"]

            if kind == "noop":
                self._log("noop", {})
                self.do_action(run_id, action_def)

            elif kind == "earn":
                take = min(action_def["amount"], earn_remaining)
                if take > 0:
                    self._log("earn", {"amount": take})
                    out = self.do_action(run_id, {"type": "earn", "amount": take})
                    if out.get("decision") == "applied":
                        earn_used += take

            elif kind == "trade_offer":
                cp = action_def["counterparty"]
                give = action_def["give_amount"]
                want = action_def["want_amount"]
                oid = f"o{self.brain.rng.getrandbits(48):012x}"

                out = self.do_action(run_id, {
                    "type": "trade_prepare",
                    "offer_id": oid,
                    "counterparty": cp,
                    "give_amount": give,
                    "want_amount": want,
                })
                if out.get("decision") == "applied":
                    accepted = self.exchange.make_offer(
                        oid, self.peer_id, cp, give, want
                    )
                    self._log("trade_offer", {
                        "counterparty": cp, "give": give, "want": want,
                        "accepted": accepted,
                    })
                    if accepted:
                        pending_commits.append(oid)

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
    p.add_argument("--yp-url", default="http://localhost:9105/mcp")
    p.add_argument("--num-citizens", type=int, default=10,
                   help="Number of citizen agents (default 10)")
    p.add_argument("--mesh-ports", type=int, nargs="*", default=None,
                   help="AXL bridge ports (auto-derived from --num-citizens if omitted)")
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

    create = _post(f"{orch}/v1/run/create", {
        "run_id": args.run_id,
        "max_epochs": args.epochs,
        "actions_per_epoch": args.actions_per_epoch,
        "initial_balance": args.initial_balance,
        "citizens": citizen_ids,
    })
    print(f"[main] Run {args.run_id} created  enrolled={len(create.get('enrolled', []))}")

    # ── register agents + join ────────────────────────────────────
    exchange = TradeExchange()
    agents = [
        CitizenAgent(citizen_ids[i], orch, args.yp_url, args.seed + i, exchange)
        for i in range(nc)
    ]
    for a in agents:
        a.register_yp()
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
        print(f"[epoch {epoch}] Running citizens…")

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(agents)) as pool:
            futures = [
                pool.submit(a.run_epoch, args.run_id, epoch, args.actions_per_epoch)
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
            "actions_log": actions_log,
        })
        policy = next_policy(policy, gini)

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
