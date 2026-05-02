#!/usr/bin/env python3
"""
AI Village orchestrator: authoritative ledger, epoch lifecycle, tax/UBI/Gini snapshots.

HTTP API (JSON body). Optional Town Hall audit MCP (--audit-mcp-url) receives append_event
via streamable JSON-RPC (stateless sessions), same pattern as yellow_pages_mcp.

`POST /v1/run/delete` drops in-memory run state (simulation reset); snapshots on disk are untouched.

Example:
  python orchestrator.py --listen-host 127.0.0.1 --listen-port 9200 \\
    --runs-dir ./runs --audit-mcp-url http://127.0.0.1:9106/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESOURCES = ["coin", "wood", "stone", "grain"]
INITIAL_RESOURCES = {"coin": 100, "wood": 5, "stone": 5, "grain": 5}
RESOURCE_PRICES = {"coin": 1, "wood": 3, "stone": 4, "grain": 5}
CONSUMPTION_BASKET = {"grain": 2, "wood": 1}

from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def assign_skills(seed_str: str) -> dict[str, float]:
    rng = random.Random(hash(seed_str) & 0xFFFFFFFF)
    return {r: round(rng.uniform(0.3, 1.2), 2) for r in RESOURCES}


@dataclass
class PendingTrade:
    initiator: str
    counterparty: str
    give_resource: str
    give_amount: int
    want_resource: str
    want_amount: int
    epoch: int


@dataclass
class RunState:
    run_id: str
    max_epochs: int
    actions_per_epoch: int
    resources: dict[str, dict[str, int]] = field(default_factory=dict)
    skills: dict[str, dict[str, float]] = field(default_factory=dict)
    consumption_basket: dict[str, int] = field(default_factory=lambda: dict(CONSUMPTION_BASKET))
    enrolled: set[str] = field(default_factory=set)
    current_epoch: int = -1
    phase: str = "idle"  # idle | action | closed
    policy: dict[str, Any] = field(default_factory=dict)
    slots_used: dict[str, int] = field(default_factory=dict)
    earn_used: dict[str, int] = field(default_factory=dict)
    epoch_complete: set[str] = field(default_factory=set)
    pending_trades: dict[str, PendingTrade] = field(default_factory=dict)
    gini_history: list[float] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        runs_dir: Path,
        *,
        audit_mcp_url: str = "",
        earn_cap_per_epoch: int = 100,
    ) -> None:
        self._runs: dict[str, RunState] = {}
        self._lock = asyncio.Lock()
        self.runs_dir = runs_dir
        self.audit_mcp_url = audit_mcp_url.rstrip("/")
        self.earn_cap_per_epoch = earn_cap_per_epoch
        self._mcp_session: str | None = None
        self._audit_sess_lock = threading.Lock()

    async def _audit(
        self,
        tool: str,
        arguments: dict[str, Any],
        req_id: int = 1,
    ) -> None:
        if not self.audit_mcp_url:
            return
        base = self.audit_mcp_url

        def _call() -> None:
            try:
                with self._audit_sess_lock:
                    sess = self._mcp_session
                    if not sess:
                        init = json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "method": "initialize",
                                "params": {
                                    "protocolVersion": "2024-11-05",
                                    "capabilities": {},
                                    "clientInfo": {"name": "orchestrator", "version": "0.1"},
                                },
                                "id": 0,
                            }
                        ).encode()
                        req = urllib.request.Request(
                            base,
                            data=init,
                            method="POST",
                            headers={
                                "Content-Type": "application/json",
                                "Accept": "application/json",
                            },
                        )
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            hdrs = {k.lower(): v for k, v in resp.headers.items()}
                            self._mcp_session = hdrs.get("mcp-session-id", "")
                    sess = self._mcp_session or ""
                body = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {"name": tool, "arguments": arguments},
                        "id": req_id,
                    }
                ).encode()
                h = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                if sess:
                    h["Mcp-Session-Id"] = sess
                req = urllib.request.Request(base, data=body, method="POST", headers=h)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp.read()
            except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
                logger.warning("audit MCP %s failed: %s", tool, e)

        await asyncio.to_thread(_call)

    def _run_dir(self, run_id: str) -> Path:
        d = self.runs_dir / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _persist_manifest(self, st: RunState) -> None:
        d = self._run_dir(st.run_id)
        manifest = {
            "run_id": st.run_id,
            "max_epochs": st.max_epochs,
            "actions_per_epoch": st.actions_per_epoch,
            "updated_at": _utc(),
            "resources": {p: dict(r) for p, r in st.resources.items()},
            "skills": {p: dict(s) for p, s in st.skills.items()},
            "enrolled": sorted(st.enrolled),
        }
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def _persist_snapshot(self, st: RunState, snap: dict[str, Any]) -> None:
        d = self._run_dir(st.run_id)
        ep = snap.get("epoch", 0)
        (d / f"snapshot_epoch_{ep:04d}.json").write_text(
            json.dumps(snap, indent=2) + "\n", encoding="utf-8"
        )

    async def handle_create_run(self, request: web.Request) -> web.Response:
        body = await request.json()
        run_id = str(body.get("run_id", "")).strip()
        if not run_id:
            return web.json_response({"error": "run_id required"}, status=400)
        max_epochs = int(body.get("max_epochs", 10))
        actions_per_epoch = max(1, int(body.get("actions_per_epoch", 5)))
        initial = int(body.get("initial_balance", 100))
        citizens = body.get("citizens")
        if citizens is None:
            return web.json_response({"error": "citizens: list of peer_id required"}, status=400)
        async with self._lock:
            if run_id in self._runs:
                return web.json_response({"error": "run exists"}, status=409)
            st = RunState(
                run_id=run_id,
                max_epochs=max_epochs,
                actions_per_epoch=actions_per_epoch,
            )
            for pid in citizens:
                p = str(pid).strip().lower()
                if len(p) == 64:
                    res = dict(INITIAL_RESOURCES)
                    res["coin"] = initial
                    st.resources[p] = res
                    st.skills[p] = assign_skills(p)
                    st.enrolled.add(p)
            self._runs[run_id] = st
            self._persist_manifest(st)
        await self._audit(
            "append_event",
            {
                "run_id": run_id,
                "epoch": -1,
                "peer_id": "orchestrator",
                "kind": "run_created",
                "payload_json": json.dumps(
                    {"max_epochs": max_epochs, "actions_per_epoch": actions_per_epoch, "initial": initial}
                ),
                "decision": "applied",
                "reason": "",
                "counterparty_peer_id": "",
            },
        )
        return web.json_response(
            {
                "run_id": run_id,
                "enrolled": sorted(st.enrolled),
                "balances": {p: st.resources[p].get("coin", 0) for p in sorted(st.enrolled)},
            }
        )

    async def handle_delete_run(self, request: web.Request) -> web.Response:
        """Drop run state in memory (dev / simulation). On-disk files are not removed."""
        body = await request.json()
        run_id = str(body.get("run_id", "")).strip()
        if not run_id:
            return web.json_response({"error": "run_id required"}, status=400)
        async with self._lock:
            existed = run_id in self._runs
            self._runs.pop(run_id, None)
        return web.json_response({"ok": True, "run_id": run_id, "existed": existed})

    async def handle_join_run(self, request: web.Request) -> web.Response:
        body = await request.json()
        run_id = str(body.get("run_id", "")).strip()
        peer_id = str(body.get("peer_id", "")).strip().lower()
        initial = int(body.get("initial_balance", 100))
        async with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return web.json_response({"error": "unknown run"}, status=404)
            if peer_id not in st.enrolled:
                st.enrolled.add(peer_id)
                st.resources.setdefault(peer_id, dict(INITIAL_RESOURCES))
                st.resources[peer_id].setdefault("coin", initial)
                st.skills.setdefault(peer_id, assign_skills(peer_id))
            self._persist_manifest(st)
            bal = st.resources.get(peer_id, {}).get("coin", 0)
        asyncio.create_task(
            self._audit(
                "append_event",
                {
                    "run_id": run_id,
                    "epoch": -1,
                    "peer_id": peer_id,
                    "kind": "join_run",
                    "payload_json": json.dumps({"initial_balance": initial}),
                    "decision": "applied",
                    "reason": "",
                    "counterparty_peer_id": "",
                },
                req_id=2,
            )
        )
        return web.json_response({"ok": True, "balance": bal})

    async def handle_open_epoch(self, request: web.Request) -> web.Response:
        body = await request.json()
        run_id = str(body.get("run_id", "")).strip()
        epoch = int(body.get("epoch", 0))
        policy = body.get("policy") or {}
        async with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return web.json_response({"error": "unknown run"}, status=404)
            st.current_epoch = epoch
            st.policy = dict(policy)
            st.phase = "action"
            st.slots_used = {p: 0 for p in st.enrolled}
            st.earn_used = {p: 0 for p in st.enrolled}
            st.epoch_complete = set()
            st.pending_trades.clear()
        await self._audit(
            "append_event",
            {
                "run_id": run_id,
                "epoch": epoch,
                "peer_id": "orchestrator",
                "kind": "epoch_open",
                "payload_json": json.dumps(policy),
                "decision": "applied",
                "reason": "",
                "counterparty_peer_id": "",
            },
            req_id=3,
        )
        return web.json_response({"ok": True, "epoch": epoch})

    async def handle_action(self, request: web.Request) -> web.Response:
        body = await request.json()
        run_id = str(body.get("run_id", "")).strip()
        peer_id = str(body.get("peer_id", "")).strip().lower()
        action = body.get("action") or {}
        kind = str(action.get("type", "noop")).lower()
        async with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return web.json_response({"error": "unknown run"}, status=404)
            if st.phase != "action":
                return web.json_response({"error": "epoch not open for actions"}, status=409)
            if peer_id not in st.enrolled:
                return web.json_response({"error": "not enrolled"}, status=403)
            used = st.slots_used.get(peer_id, 0)
            if used >= st.actions_per_epoch:
                return web.json_response({"error": "action slots exhausted"}, status=409)
            epoch = st.current_epoch
        decision = "applied"
        reason = ""
        if kind in ("noop", "dummy"):
            async with self._lock:
                st.slots_used[peer_id] = st.slots_used.get(peer_id, 0) + 1
        elif kind == "earn":
            resource = str(action.get("resource", "coin"))
            amount = int(action.get("amount", 10))
            if resource not in RESOURCES:
                return web.json_response({"error": f"unknown resource {resource}"}, status=400)
            async with self._lock:
                eu = st.earn_used.get(peer_id, 0)
                remain = max(0, self.earn_cap_per_epoch - eu)
                skill = st.skills.get(peer_id, {}).get(resource, 1.0)
                produced = max(1, int(amount * skill))
                take = min(produced, remain)
                if take <= 0:
                    decision = "rejected"
                    reason = "earn cap"
                else:
                    st.resources[peer_id][resource] = st.resources[peer_id].get(resource, 0) + take
                    st.earn_used[peer_id] = eu + take
                    st.slots_used[peer_id] = st.slots_used.get(peer_id, 0) + 1
        elif kind == "trade_prepare":
            offer_id = str(action.get("offer_id", "")).strip()
            to = str(action.get("counterparty", "")).strip().lower()
            give_resource = str(action.get("give_resource", ""))
            give_amount = int(action.get("give_amount", 0))
            want_resource = str(action.get("want_resource", ""))
            want_amount = int(action.get("want_amount", 0))
            async with self._lock:
                if not offer_id or to not in st.enrolled or to == peer_id:
                    decision = "rejected"
                    reason = "bad offer"
                elif offer_id in st.pending_trades:
                    decision = "rejected"
                    reason = "duplicate offer_id"
                elif give_resource not in RESOURCES or want_resource not in RESOURCES:
                    decision = "rejected"
                    reason = "invalid resource"
                elif give_amount <= 0 or want_amount <= 0:
                    decision = "rejected"
                    reason = "amounts"
                elif st.resources[peer_id].get(give_resource, 0) < give_amount:
                    decision = "rejected"
                    reason = "insufficient initiator resource"
                else:
                    st.pending_trades[offer_id] = PendingTrade(
                        initiator=peer_id,
                        counterparty=to,
                        give_resource=give_resource,
                        give_amount=give_amount,
                        want_resource=want_resource,
                        want_amount=want_amount,
                        epoch=st.current_epoch,
                    )
                    st.slots_used[peer_id] = st.slots_used.get(peer_id, 0) + 1
        elif kind == "trade_commit":
            offer_id = str(action.get("offer_id", "")).strip()
            async with self._lock:
                pend = st.pending_trades.get(offer_id)
                if not pend:
                    decision = "rejected"
                    reason = "unknown offer"
                elif peer_id != pend.counterparty:
                    decision = "rejected"
                    reason = "not counterparty"
                elif st.resources[pend.counterparty].get(pend.want_resource, 0) < pend.want_amount:
                    decision = "rejected"
                    reason = "insufficient counterparty resource"
                elif st.resources[pend.initiator].get(pend.give_resource, 0) < pend.give_amount:
                    decision = "rejected"
                    reason = "initiator short"
                else:
                    st.resources[pend.initiator][pend.give_resource] -= pend.give_amount
                    st.resources[pend.initiator][pend.want_resource] += pend.want_amount
                    st.resources[pend.counterparty][pend.want_resource] -= pend.want_amount
                    st.resources[pend.counterparty][pend.give_resource] += pend.give_amount
                    del st.pending_trades[offer_id]
                    st.slots_used[peer_id] = st.slots_used.get(peer_id, 0) + 1
        else:
            return web.json_response({"error": f"unknown action {kind}"}, status=400)
        payload_log = json.dumps(action)
        async with self._lock:
            bal = st.resources.get(peer_id, {}).get("coin", 0) if st else 0
        # Do not block HTTP on Town Hall MCP; ledger is already updated.
        asyncio.create_task(
            self._audit(
                "append_event",
                {
                    "run_id": run_id,
                    "epoch": epoch,
                    "peer_id": peer_id,
                    "kind": kind,
                    "payload_json": payload_log,
                    "decision": decision,
                    "reason": reason,
                    "counterparty_peer_id": str(action.get("counterparty", "") or ""),
                },
                req_id=4,
            )
        )
        return web.json_response(
            {"ok": decision == "applied", "decision": decision, "reason": reason, "balance": bal}
        )

    async def handle_epoch_complete(self, request: web.Request) -> web.Response:
        body = await request.json()
        run_id = str(body.get("run_id", "")).strip()
        peer_id = str(body.get("peer_id", "")).strip().lower()
        async with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return web.json_response({"error": "unknown run"}, status=404)
            if peer_id in st.enrolled:
                st.epoch_complete.add(peer_id)
            elif peer_id:
                logger.warning(
                    "epoch_complete ignored run_id=%s peer=%s… (not in enrolled census)",
                    run_id,
                    peer_id[:16],
                )
            n = len(st.epoch_complete)
            total = len(st.enrolled)
            audit_epoch = st.current_epoch
        asyncio.create_task(
            self._audit(
                "append_event",
                {
                    "run_id": run_id,
                    "epoch": audit_epoch,
                    "peer_id": peer_id,
                    "kind": "epoch_complete",
                    "payload_json": "{}",
                    "decision": "applied",
                    "reason": "",
                    "counterparty_peer_id": "",
                },
                req_id=5,
            )
        )
        return web.json_response({"ok": True, "completed_peers": n, "enrolled": total})

    async def handle_close_epoch(self, request: web.Request) -> web.Response:
        body = await request.json()
        run_id = str(body.get("run_id", "")).strip()
        async with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return web.json_response({"error": "unknown run"}, status=404)
            tax_rate = float(st.policy.get("wealth_tax_rate", 0.1))
            ubi = int(st.policy.get("ubi", 5))
            pre_tax_resources = {p: dict(st.resources[p]) for p in st.enrolled}

            # Wealth tax on coin only
            for p in st.enrolled:
                coin = st.resources[p].get("coin", 0)
                tax = int(coin * tax_rate)
                st.resources[p]["coin"] = max(0, coin - tax)

            # UBI in coin
            for p in st.enrolled:
                st.resources[p]["coin"] = st.resources[p].get("coin", 0) + ubi

            # Consumption: citizens must consume from basket or face penalty
            consumption_shortfalls: dict[str, dict[str, int]] = {}
            for p in st.enrolled:
                missing: dict[str, int] = {}
                for rsrc, needed in st.consumption_basket.items():
                    available = st.resources[p].get(rsrc, 0)
                    consumed = min(available, needed)
                    st.resources[p][rsrc] = available - consumed
                    if consumed < needed:
                        missing[rsrc] = needed - consumed
                if missing:
                    consumption_shortfalls[p] = missing
                    penalty = sum(missing.values()) * 10
                    st.resources[p]["coin"] = max(0, st.resources[p].get("coin", 0) - penalty)

            # Wealth = total value at market prices
            wealth: dict[str, float] = {}
            for p in st.enrolled:
                w = sum(st.resources[p].get(r, 0) * RESOURCE_PRICES.get(r, 1) for r in RESOURCES)
                wealth[p] = w

            vals = [wealth[p] for p in sorted(st.enrolled)]
            g = gini_coefficient(vals)
            st.gini_history.append(g)
            snap = {
                "epoch": st.current_epoch,
                "updated_at": _utc(),
                "policy_applied": dict(st.policy),
                "balances": {p: st.resources[p].get("coin", 0) for p in sorted(st.enrolled)},
                "resources": {p: dict(st.resources[p]) for p in sorted(st.enrolled)},
                "skills": {p: dict(st.skills[p]) for p in sorted(st.enrolled)},
                "consumption_basket": dict(st.consumption_basket),
                "wealth": {p: round(w, 1) for p, w in wealth.items()},
                "consumption_shortfalls": consumption_shortfalls,
                "gini": g,
                "pre_tax_resources": pre_tax_resources,
                "pre_tax_balances": {p: pre_tax_resources[p].get("coin", 0) for p in pre_tax_resources},
            }
            st.snapshots.append(snap)
            st.phase = "closed"
            epoch = st.current_epoch
        self._persist_snapshot(st, snap)
        self._persist_manifest(st)
        asyncio.create_task(
            self._audit(
                "append_epoch_summary",
                {
                    "run_id": run_id,
                    "epoch": epoch,
                    "summary_json": json.dumps(snap),
                },
                req_id=6,
            )
        )
        return web.json_response(snap)

    async def handle_state(self, request: web.Request) -> web.Response:
        run_id = request.query.get("run_id", "").strip()
        async with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return web.json_response({"error": "unknown run"}, status=404)
            enrolled = sorted(st.enrolled)
            done = sorted(st.epoch_complete)
            quorum = bool(st.enrolled and st.enrolled.issubset(st.epoch_complete))
            return web.json_response(
                {
                    "run_id": st.run_id,
                    "current_epoch": st.current_epoch,
                    "phase": st.phase,
                    "max_epochs": st.max_epochs,
                    "policy": dict(st.policy),
                    "balances": {p: st.resources[p].get("coin", 0) for p in enrolled},
                    "resources": {p: dict(st.resources[p]) for p in enrolled},
                    "skills": {p: dict(st.skills[p]) for p in enrolled},
                    "enrolled": enrolled,
                    "actions_per_epoch": st.actions_per_epoch,
                    "slots_used": dict(st.slots_used),
                    "earn_used": dict(st.earn_used),
                    "epoch_complete": done,
                    "epoch_quorum_ready": quorum,
                    "gini_history": list(st.gini_history),
                }
            )


async def handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "village-orchestrator"})


def build_app(orch: Orchestrator) -> web.Application:
    app = web.Application()
    app.router.add_get("/v1/health", handle_health)
    app.router.add_post("/v1/run/create", orch.handle_create_run)
    app.router.add_post("/v1/run/delete", orch.handle_delete_run)
    app.router.add_post("/v1/run/join", orch.handle_join_run)
    app.router.add_post("/v1/epoch/open", orch.handle_open_epoch)
    app.router.add_post("/v1/action", orch.handle_action)
    app.router.add_post("/v1/epoch/complete", orch.handle_epoch_complete)
    app.router.add_post("/v1/epoch/close", orch.handle_close_epoch)
    app.router.add_get("/v1/state", orch.handle_state)
    return app


def main() -> None:
    p = argparse.ArgumentParser(description="AI Village orchestrator")
    p.add_argument("--listen-host", default="127.0.0.1")
    p.add_argument("--listen-port", type=int, default=9200)
    p.add_argument(
        "--runs-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "runs",
    )
    p.add_argument(
        "--audit-mcp-url",
        default="",
        help="Town Hall MCP HTTP endpoint e.g. http://127.0.0.1:9106/mcp",
    )
    p.add_argument("--earn-cap", type=int, default=100)
    args = p.parse_args()
    orch = Orchestrator(
        args.runs_dir,
        audit_mcp_url=args.audit_mcp_url,
        earn_cap_per_epoch=args.earn_cap,
    )
    app = build_app(orch)
    web.run_app(app, host=args.listen_host, port=args.listen_port, print=lambda _: None)
    logger.info("Listening http://%s:%s", args.listen_host, args.listen_port)


if __name__ == "__main__":
    main()
