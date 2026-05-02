#!/usr/bin/env python3
"""
Simple standalone village simulation — zero external services.

  - 2 citizens (default), N epochs (default 2)
  - Random actions per citizen per epoch: noop, earn, or bilateral trade
  - Epoch-close applies wealth tax + UBI, then computes Gini coefficient
  - Writes snapshots and gini_timeseries.json under runs/<run_id>/

Usage:
  uv run python scripts/village/simple_simulation.py
  uv run python scripts/village/simple_simulation.py --epochs 4 --actions-per-epoch 8 --seed 123
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def gini_coefficient(values: list[float]) -> float:
    """Gini on non-negative values; empty or single -> 0.0."""
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


@dataclass
class Citizen:
    peer_id: str
    seed: int = 1
    balance: int = 100
    earn_cap_per_epoch: int = 100
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        h = hashlib.sha256(f"{self.seed}:{self.peer_id}".encode()).digest()
        self.rng = random.Random(int.from_bytes(h[:8], "big"))

    def pick_action(
        self, peers: list[str], earn_remaining: int, balance: int
    ) -> dict[str, Any]:
        """Return action dict. Types: noop, earn, trade_offer."""
        r = self.rng.random()
        noop_p = 0.45 if not peers else 0.2
        if not peers or r < noop_p:
            return {"type": "noop"}
        if r < 0.65 and earn_remaining > 0:
            amt = min(self.rng.randint(1, 15), earn_remaining)
            return {"type": "earn", "amount": amt}
        cp = self.rng.choice(peers)
        give = min(balance, max(1, self.rng.randint(1, min(10, max(1, balance)))))
        want = max(1, self.rng.randint(1, 10))
        return {
            "type": "trade_offer",
            "counterparty": cp,
            "give_amount": give,
            "want_amount": want,
        }


def next_policy(prev: dict[str, Any], gini: float) -> dict[str, Any]:
    """Adaptive tax/UBI rule — targets gini ≤ 0.05."""
    tax = float(prev.get("wealth_tax_rate", 0.1))
    ubi = int(prev.get("ubi", 5))
    target = 0.05
    error = gini - target
    tax = max(0.02, min(0.5, round(tax + error * 5.0, 4)))
    ubi = max(0, min(50, ubi + round(error * 100)))
    return {"wealth_tax_rate": tax, "ubi": ubi}


def run_epoch(
    citizens: list[Citizen],
    epoch: int,
    policy: dict[str, Any],
    actions_per_epoch: int,
) -> dict[str, Any]:
    """
    Open epoch, let every citizen take up to *actions_per_epoch* actions,
    then close (tax + UBI) and return snapshot.
    """
    peer_ids = [c.peer_id for c in citizens]
    earn_used: dict[str, int] = {c.peer_id: 0 for c in citizens}
    slots_used: dict[str, int] = {c.peer_id: 0 for c in citizens}
    actions_log: list[dict[str, Any]] = []

    for c in citizens:
        peers = [p for p in peer_ids if p != c.peer_id]
        for _ in range(actions_per_epoch):
            if slots_used[c.peer_id] >= actions_per_epoch:
                break
            er = max(0, c.earn_cap_per_epoch - earn_used[c.peer_id])
            action = c.pick_action(peers, er, c.balance)
            kind = action["type"]
            entry: dict[str, Any] = {
                "citizen": c.peer_id,
                "slot": slots_used[c.peer_id] + 1,
                "action": kind,
            }

            if kind in ("noop", "dummy"):
                slots_used[c.peer_id] += 1

            elif kind == "earn":
                take = min(action["amount"], max(0, c.earn_cap_per_epoch - earn_used[c.peer_id]))
                if take > 0:
                    c.balance += take
                    earn_used[c.peer_id] += take
                    entry["amount"] = take
                slots_used[c.peer_id] += 1

            elif kind == "trade_offer":
                cp_id = action["counterparty"]
                cp = next((x for x in citizens if x.peer_id == cp_id), None)
                give = int(action["give_amount"])
                want = int(action["want_amount"])
                entry["counterparty"] = cp_id
                entry["give"] = give
                entry["want"] = want
                if cp is None or give <= 0 or want <= 0:
                    entry["outcome"] = "invalid"
                    slots_used[c.peer_id] += 1
                    actions_log.append(entry)
                    continue
                accepted = cp.balance >= want and c.balance >= give and c.rng.random() < 0.7
                entry["accepted"] = accepted
                if accepted:
                    c.balance -= give
                    c.balance += want
                    cp.balance -= want
                    cp.balance += give
                    entry["outcome"] = "executed"
                else:
                    entry["outcome"] = "rejected"
                slots_used[c.peer_id] += 1

            actions_log.append(entry)

    # ---- epoch close: tax then UBI ----
    tax_rate = float(policy.get("wealth_tax_rate", 0.1))
    ubi = int(policy.get("ubi", 5))
    pre_tax = {c.peer_id: c.balance for c in citizens}

    for c in citizens:
        t = int(c.balance * tax_rate)
        c.balance = max(0, c.balance - t)
    for c in citizens:
        c.balance += ubi

    balances = {c.peer_id: c.balance for c in citizens}
    g = gini_coefficient(list(balances.values()))

    return {
        "epoch": epoch,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy_applied": dict(policy),
        "balances": balances,
        "pre_tax_balances": pre_tax,
        "gini": g,
        "slots_used": dict(slots_used),
        "earn_used": dict(earn_used),
        "actions_log": actions_log,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Simple standalone village simulation (no services required)"
    )
    p.add_argument("--run-id", default="simple_demo")
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--actions-per-epoch", type=int, default=5)
    p.add_argument("--initial-balance", type=int, default=100)
    p.add_argument("--initial-tax", type=float, default=0.1)
    p.add_argument("--initial-ubi", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--runs-dir", type=Path, default=Path(__file__).resolve().parent / "runs")
    args = p.parse_args()

    run_dir = args.runs_dir / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    citizens = [
        Citizen(peer_id="citizen_a", seed=args.seed, balance=args.initial_balance),
        Citizen(peer_id="citizen_b", seed=args.seed + 1, balance=args.initial_balance),
    ]

    policy: dict[str, Any] = {
        "wealth_tax_rate": args.initial_tax,
        "ubi": args.initial_ubi,
    }
    series: list[dict[str, Any]] = []

    print(f"run_id={args.run_id} | citizens={len(citizens)} | epochs={args.epochs}")
    print(f"initial_balances={[c.balance for c in citizens]}")
    print("-" * 50)

    for epoch in range(args.epochs):
        snap = run_epoch(citizens, epoch, policy, args.actions_per_epoch)
        series.append(
            {
                "epoch": snap["epoch"],
                "gini": snap["gini"],
                "policy_applied": snap["policy_applied"],
                "balances": snap["balances"],
                "pre_tax_balances": snap["pre_tax_balances"],
                "actions_log": snap["actions_log"],
            }
        )

        (run_dir / f"snapshot_epoch_{epoch:04d}.json").write_text(
            json.dumps(snap, indent=2) + "\n", encoding="utf-8"
        )

        print(f"Epoch {epoch}")
        print(f"  policy       : tax={policy['wealth_tax_rate']}, ubi={policy['ubi']}")
        print(f"  pre-tax      : {snap['pre_tax_balances']}")
        print(f"  post-tax+ubi : {snap['balances']}")
        print(f"  Gini         : {snap['gini']:.4f}")
        print("  actions:")
        for a in snap["actions_log"]:
            line = f"    {a['citizen']} slot{a['slot']}: {a['action']}"
            if a["action"] == "earn":
                line += f" (+{a.get('amount', 0)})"
            elif a["action"] == "trade_offer":
                acc = "accepted" if a.get("accepted") else "rejected"
                line += f" -> {a['counterparty']} give={a['give']} want={a['want']} [{acc}]"
            print(line)

        policy = next_policy(policy, snap["gini"])

    summary = {
        "run_id": args.run_id,
        "max_epochs": args.epochs,
        "actions_per_epoch": args.actions_per_epoch,
        "initial_balance": args.initial_balance,
        "citizen_peer_ids": [c.peer_id for c in citizens],
        "gini_timeseries": series,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out_path = run_dir / "gini_timeseries.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("-" * 50)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
