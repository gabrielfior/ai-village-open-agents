#!/usr/bin/env python3
"""
End-to-end village simulation driver:

  1. POST /v1/run/create (or rely on discover + create)
  2. Spawn one citizen.py per citizen (random actions)
  3. Run town hall epoch loop (policy gossip + open/close)
  4. Write gini_timeseries.json under runs/<run_id>/
  5. Optionally append summary event to Town Hall MCP (audit)

Prerequisites: orchestrator, MCP router, Yellow Pages, Town Hall MCP (optional),
AXL mesh reachable via bootstrap_peers.

Example:
  uv run python scripts/village/run_simulation.py --config scripts/village/simulation.example.json --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from citizen import write_node_config  # noqa: E402
from town_hall import run_loop as town_hall_run_loop  # noqa: E402
from village_axl import get_topology  # noqa: E402

LOG = logging.getLogger("run_simulation")


def _json_post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _repo_path(rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        return p
    return Path.cwd() / p


def discover_peer_id(
    *,
    node_binary: Path,
    pem: Path,
    peers: list[str],
    api_port: int,
    tcp_port: int,
    cwd: Path,
    timeout: float = 90.0,
) -> str:
    """Boot AXL node once and read our_public_key, then stop the node."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=cwd, prefix="discover-node-"
    ) as tmp:
        cfg_path = Path(tmp.name)
    proc: subprocess.Popen | None = None
    try:
        write_node_config(
            cfg_path,
            pem=pem,
            peers=peers,
            listen=[],
            api_port=api_port,
            tcp_port=tcp_port,
        )
        proc = subprocess.Popen(
            [str(node_binary.resolve()), "-config", cfg_path.name],
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        bridge = f"http://127.0.0.1:{api_port}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            t = get_topology(bridge)
            if t and t.get("our_public_key"):
                return str(t["our_public_key"]).strip().lower()
            time.sleep(0.25)
        raise TimeoutError(f"topology not ready on {bridge}")
    finally:
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        cfg_path.unlink(missing_ok=True)


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def collect_gini_series(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    d = runs_dir / run_id
    if not d.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for p in sorted(d.glob("snapshot_epoch_*.json")):
        try:
            snap = json.loads(p.read_text(encoding="utf-8"))
            rows.append(
                {
                    "epoch": int(snap.get("epoch", -1)),
                    "gini": float(snap.get("gini", 0.0)),
                    "policy_applied": snap.get("policy_applied"),
                    "balances": snap.get("balances"),
                    "snapshot_file": p.name,
                }
            )
        except (json.JSONDecodeError, OSError, TypeError):
            continue
    rows.sort(key=lambda r: r["epoch"])
    return rows


def mcp_one_shot_call(
    mcp_url: str,
    tool: str,
    arguments: dict[str, Any],
) -> None:
    """Stateless JSON-RPC (each call initialize + tools/call)."""
    init = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "run_simulation", "version": "0.1"},
            },
            "id": 0,
        }
    ).encode()
    req = urllib.request.Request(
        mcp_url,
        data=init,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            init_raw = resp.read().decode()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            sess = (hdrs.get("mcp-session-id") or "").strip()
    except OSError as e:
        LOG.warning("Town Hall MCP unreachable: %s", e)
        return
    try:
        init_msg = json.loads(init_raw)
    except json.JSONDecodeError:
        LOG.warning("MCP initialize: not JSON (%s)", init_raw[:200])
        return
    if isinstance(init_msg, dict) and "error" in init_msg:
        LOG.warning("MCP initialize error: %s", init_msg["error"])
        return
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
            "id": 1,
        }
    ).encode()
    h2 = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if sess:
        h2["Mcp-Session-Id"] = sess
    req2 = urllib.request.Request(mcp_url, data=body, method="POST", headers=h2)
    try:
        with urllib.request.urlopen(req2, timeout=60) as resp:
            raw = json.loads(resp.read().decode())
        if "error" in raw:
            LOG.warning("MCP %s error: %s", tool, raw["error"])
    except OSError as e:
        LOG.warning("MCP tools/call failed: %s", e)


def main() -> int:
    p = argparse.ArgumentParser(description="Run full village simulation (create run + citizens + town hall)")
    p.add_argument("--config", type=Path, required=True, help="JSON config (see simulation.example.json)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    cfg_path = args.config
    if not cfg_path.is_absolute():
        cfg_path = Path.cwd() / cfg_path
    cfg = load_config(cfg_path)
    run_id = str(cfg["run_id"]).strip()
    orch = str(cfg.get("orchestrator", "http://127.0.0.1:9200")).rstrip("/")
    yp = str(cfg["yellow_pages_peer_id"]).strip()
    mayor_bridge = str(cfg["mayor_bridge"]).strip()
    max_epochs = int(cfg.get("max_epochs", 5))
    actions_per_epoch = int(cfg.get("actions_per_epoch", 5))
    initial_balance = int(cfg.get("initial_balance", 100))
    node_bin = _repo_path(str(cfg.get("node_binary", "axl/node")))
    cwd = _repo_path(str(cfg.get("config_dir", ".")))
    bootstrap = [str(x) for x in cfg.get("bootstrap_peers") or []]
    startup_delay = float(cfg.get("startup_delay_sec", 8.0))
    citizen_wait = float(cfg.get("citizen_wait_sec", 600.0))
    audit_url = str(cfg.get("audit_mcp_url", "")).strip()
    discover = bool(cfg.get("discover_peer_ids", False))
    runs_dir = _repo_path(str(cfg.get("runs_dir", str(_SCRIPTS / "runs"))))

    citizens_cfg: list[dict[str, Any]] = list(cfg.get("citizens") or [])
    if len(citizens_cfg) < 1:
        LOG.error("config.citizens must be a non-empty list")
        return 1

    peer_ids: list[str] = []
    for i, c in enumerate(citizens_cfg):
        if not discover:
            if not c.get("peer_id"):
                LOG.error("citizen %d: set peer_id or enable discover_peer_ids", i)
                return 1
            peer_ids.append(str(c["peer_id"]).strip().lower())
            continue
        pem = _repo_path(str(c["pem"]))
        api = int(c["api_port"])
        tcp = int(c.get("tcp_port", 7000 + i))
        LOG.info("Discovering peer_id for %s (api_port=%s)…", pem, api)
        pid = discover_peer_id(
            node_binary=node_bin,
            pem=pem,
            peers=bootstrap,
            api_port=api,
            tcp_port=tcp,
            cwd=cwd,
        )
        peer_ids.append(pid)
        LOG.info("  -> %s", pid)

    if len(peer_ids) != len(set(peer_ids)):
        LOG.error("Duplicate peer_ids in config/discovery")
        return 1

    citizen_py = _SCRIPTS / "citizen.py"

    if cfg.get("recreate_run_if_exists", False):
        try:
            _json_post(f"{orch}/v1/run/delete", {"run_id": run_id})
            LOG.info("Orchestrator run %s cleared before create (recreate_run_if_exists)", run_id)
        except urllib.error.HTTPError as e:
            LOG.warning(
                "run/delete: %s %s",
                e.code,
                e.read().decode(errors="replace"),
            )

    # Do not pre-seed orchestrator enrolment from discovery: discovered keys can differ from
    # each citizen node's live /topology pubkey (startup timing / mesh quirks). Enrollment is
    # authoritative via POST /v1/run/join so epoch_complete quorum matches orchestrator enrolled.
    LOG.info(
        "POST /v1/run/create … (citizens=[]; enrolling via join with topology-derived peer_id)"
    )
    try:
        out = _json_post(
            f"{orch}/v1/run/create",
            {
                "run_id": run_id,
                "max_epochs": max_epochs,
                "actions_per_epoch": actions_per_epoch,
                "initial_balance": initial_balance,
                "citizens": [],
            },
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 409 and cfg.get("recreate_run_if_exists", False):
            LOG.warning("create 409; forcing delete+create: %s", body)
            try:
                _json_post(f"{orch}/v1/run/delete", {"run_id": run_id})
            except urllib.error.HTTPError as e2:
                LOG.warning(
                    "retry delete: %s %s",
                    e2.code,
                    e2.read().decode(errors="replace"),
                )
            out = _json_post(
                f"{orch}/v1/run/create",
                {
                    "run_id": run_id,
                    "max_epochs": max_epochs,
                    "actions_per_epoch": actions_per_epoch,
                    "initial_balance": initial_balance,
                    "citizens": [],
                },
            )
            LOG.info("create ok (orchestrator enrolled=%s until join)", out.get("enrolled"))
        elif e.code == 409:
            LOG.warning("run exists (409); continuing: %s", body)
        else:
            LOG.error("create_run failed: %s %s", e.code, body)
            return 1
    else:
        LOG.info("create ok (orchestrator enrolled=%s until join)", out.get("enrolled"))

    log_dir = runs_dir / run_id
    log_dir.mkdir(parents=True, exist_ok=True)

    procs: list[subprocess.Popen] = []
    for i, c in enumerate(citizens_cfg):
        pem = _repo_path(str(c["pem"]))
        api = int(c["api_port"])
        tcp = int(c.get("tcp_port", 7000 + i))
        seed = int(c.get("seed", 1))
        bridge = c.get("bridge") or f"http://127.0.0.1:{api}"
        cmd = [
            sys.executable,
            str(citizen_py),
            "--node-binary",
            str(node_bin.resolve()),
            "--pem",
            str(pem.resolve()),
            "--yellow-pages-peer-id",
            yp,
            "--api-port",
            str(api),
            "--tcp-port",
            str(tcp),
            "--bridge",
            str(bridge),
            "--orchestrator",
            orch,
            "--run-id",
            run_id,
            "--seed",
            str(seed),
            "--config-dir",
            str(cwd.resolve()),
        ]
        for bp in bootstrap:
            cmd.extend(["--peer", bp])
        if args.verbose:
            cmd.append("--verbose")
        tw = cfg.get("trade_wait_sec")
        if tw is not None:
            cmd.extend(["--trade-wait-sec", str(float(tw))])
        yp_mcp = str(cfg.get("yellow_pages_mcp_http", "")).strip()
        if yp_mcp:
            cmd.extend(["--mcp-http-url", yp_mcp])
        pid = peer_ids[i]
        log_path = log_dir / f"citizen_{pid[:12]}.log"
        lf = log_path.open("w", encoding="utf-8")
        LOG.info("Spawn citizen %s log=%s", pid[:16], log_path)
        procs.append(
            subprocess.Popen(
                cmd,
                cwd=str(cwd.resolve()),
                stdout=lf,
                stderr=subprocess.STDOUT,
            )
        )

    LOG.info("Waiting %ss for citizens to register on mesh…", startup_delay)
    time.sleep(startup_delay)

    yp_mcp = str(cfg.get("yellow_pages_mcp_http", "")).strip()
    th_args = argparse.Namespace(
        bridge=mayor_bridge,
        yellow_pages_peer_id=yp,
        orchestrator=orch,
        run_id=run_id,
        max_epochs=max_epochs,
        actions_per_epoch=actions_per_epoch,
        initial_tax=float(cfg.get("initial_tax", 0.1)),
        initial_ubi=int(cfg.get("initial_ubi", 5)),
        epoch_timeout_sec=float(cfg.get("epoch_timeout_sec", 60.0)),
        mcp_http_url=yp_mcp,
        verbose=args.verbose,
    )
    LOG.info("Starting town hall driver…")
    th_code = town_hall_run_loop(th_args)
    if th_code != 0:
        LOG.error("town hall exited %s", th_code)

    LOG.info("Waiting for citizen processes (max %ss)…", citizen_wait)
    deadline = time.monotonic() + citizen_wait
    for pr in procs:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            pr.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            LOG.warning("citizen pid=%s still running; sending SIGTERM", pr.pid)
            pr.terminate()

    series = collect_gini_series(Path(runs_dir), run_id)
    summary = {
        "run_id": run_id,
        "max_epochs": max_epochs,
        "actions_per_epoch": actions_per_epoch,
        "citizen_peer_ids": peer_ids,
        "gini_timeseries": series,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out_path = log_dir / "gini_timeseries.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    LOG.info("Wrote %s (%d epochs)", out_path, len(series))

    if audit_url:
        mcp_one_shot_call(
            audit_url,
            "append_event",
            {
                "run_id": run_id,
                "epoch": max_epochs,
                "peer_id": "run_simulation",
                "kind": "simulation_complete",
                "payload_json": json.dumps({"gini_timeseries": series}),
                "decision": "applied",
                "reason": "",
                "counterparty_peer_id": "",
            },
        )
        mcp_one_shot_call(
            audit_url,
            "append_epoch_summary",
            {
                "run_id": run_id,
                "epoch": max_epochs,
                "summary_json": json.dumps(summary),
            },
        )

    for i, pr in enumerate(procs):
        if pr.poll() is None:
            pr.kill()
    return 0 if th_code == 0 else th_code


if __name__ == "__main__":
    raise SystemExit(main())
