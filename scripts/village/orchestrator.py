#!/usr/bin/env python3
"""
AI Village orchestrator: authoritative ledger, epoch lifecycle, tax/UBI/Gini snapshots.

HTTP API (JSON body). Optional Town Hall audit MCP (--audit-mcp-url) receives append_event
via streamable JSON-RPC (stateless sessions), same pattern as yellow_pages_mcp.

Example:
  python orchestrator.py --listen-host 127.0.0.1 --listen-port 9200 \\
    --runs-dir ./runs --audit-mcp-url http://127.0.0.1:9106/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


@dataclass
class PendingTrade:
    initiator: str
    counterparty: str
    give_amount: int
    want_amount: int
    epoch: int


@dataclass
class RunState:
    run_id: str
    max_epochs: int
    actions_per_epoch: int
    balances: dict[str, int] = field(default_factory=dict)
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
                if self._mcp_session:
                    h["Mcp-Session-Id"] = self._mcp_session
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
            "balances": dict(st.balances),
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
        actions_per_epoch = int(body.get("actions_per_epoch", 5))
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
                    st.balances[p] = initial
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
                "balances": dict(st.balances),
            }
        )

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
                st.balances.setdefault(peer_id, initial)
            self._persist_manifest(st)
        await self._audit(
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
        return web.json_response({"ok": True, "balance": st.balances.get(peer_id, 0)})

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
        if kind == "noop":
            async with self._lock:
                st.slots_used[peer_id] = st.slots_used.get(peer_id, 0) + 1
        elif kind == "earn":
            amount = int(action.get("amount", 10))
            async with self._lock:
                eu = st.earn_used.get(peer_id, 0)
                remain = max(0, self.earn_cap_per_epoch - eu)
                take = min(amount, remain)
                if take <= 0:
                    decision = "rejected"
                    reason = "earn cap"
                else:
                    st.balances[peer_id] = st.balances.get(peer_id, 0) + take
                    st.earn_used[peer_id] = eu + take
                    st.slots_used[peer_id] = st.slots_used.get(peer_id, 0) + 1
        elif kind == "trade_prepare":
            offer_id = str(action.get("offer_id", "")).strip()
            to = str(action.get("counterparty", "")).strip().lower()
            give = int(action.get("give_amount", 0))
            want = int(action.get("want_amount", 0))
            async with self._lock:
                if not offer_id or to not in st.enrolled or to == peer_id:
                    decision = "rejected"
                    reason = "bad offer"
                elif offer_id in st.pending_trades:
                    decision = "rejected"
                    reason = "duplicate offer_id"
                elif give <= 0 or want <= 0:
                    decision = "rejected"
                    reason = "amounts"
                elif st.balances.get(peer_id, 0) < give:
                    decision = "rejected"
                    reason = "insufficient initiator balance"
                else:
                    st.pending_trades[offer_id] = PendingTrade(
                        initiator=peer_id,
                        counterparty=to,
                        give_amount=give,
                        want_amount=want,
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
                elif st.balances.get(pend.counterparty, 0) < pend.want_amount:
                    decision = "rejected"
                    reason = "insufficient counterparty balance"
                elif st.balances.get(pend.initiator, 0) < pend.give_amount:
                    decision = "rejected"
                    reason = "initiator short"
                else:
                    st.balances[pend.initiator] -= pend.give_amount
                    st.balances[pend.initiator] += pend.want_amount
                    st.balances[pend.counterparty] -= pend.want_amount
                    st.balances[pend.counterparty] += pend.give_amount
                    del st.pending_trades[offer_id]
                    st.slots_used[peer_id] = st.slots_used.get(peer_id, 0) + 1
        else:
            return web.json_response({"error": f"unknown action {kind}"}, status=400)
        payload_log = json.dumps(action)
        await self._audit(
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
        async with self._lock:
            bal = st.balances.get(peer_id, 0) if st else 0
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
            n = len(st.epoch_complete)
            total = len(st.enrolled)
        await self._audit(
            "append_event",
            {
                "run_id": run_id,
                "epoch": st.current_epoch,
                "peer_id": peer_id,
                "kind": "epoch_complete",
                "payload_json": "{}",
                "decision": "applied",
                "reason": "",
                "counterparty_peer_id": "",
            },
            req_id=5,
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
            pre_tax = {p: st.balances.get(p, 0) for p in st.enrolled}
            for p in st.enrolled:
                b = st.balances.get(p, 0)
                t = int(b * tax_rate)
                st.balances[p] = max(0, b - t)
            for p in st.enrolled:
                st.balances[p] = st.balances.get(p, 0) + ubi
            vals = [float(st.balances[p]) for p in sorted(st.enrolled)]
            g = gini_coefficient(vals)
            st.gini_history.append(g)
            snap = {
                "epoch": st.current_epoch,
                "updated_at": _utc(),
                "policy_applied": dict(st.policy),
                "balances": {p: st.balances[p] for p in sorted(st.enrolled)},
                "gini": g,
                "pre_tax_balances": pre_tax,
            }
            st.snapshots.append(snap)
            st.phase = "closed"
            epoch = st.current_epoch
        self._persist_snapshot(st, snap)
        self._persist_manifest(st)
        await self._audit(
            "append_epoch_summary",
            {
                "run_id": run_id,
                "epoch": epoch,
                "summary_json": json.dumps(snap),
            },
            req_id=6,
        )
        return web.json_response(snap)

    async def handle_state(self, request: web.Request) -> web.Response:
        run_id = request.query.get("run_id", "").strip()
        async with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return web.json_response({"error": "unknown run"}, status=404)
            return web.json_response(
                {
                    "run_id": st.run_id,
                    "current_epoch": st.current_epoch,
                    "phase": st.phase,
                    "policy": dict(st.policy),
                    "balances": dict(st.balances),
                    "enrolled": sorted(st.enrolled),
                    "actions_per_epoch": st.actions_per_epoch,
                    "slots_used": dict(st.slots_used),
                    "gini_history": list(st.gini_history),
                }
            )


def build_app(orch: Orchestrator) -> web.Application:
    app = web.Application()
    app.router.add_post("/v1/run/create", orch.handle_create_run)
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
