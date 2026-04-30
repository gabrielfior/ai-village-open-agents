#!/usr/bin/env python3
"""Probe village-related HTTP ports; exit 1 if orchestrator is not the village API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode(errors="replace")
    except OSError as e:
        return -1, str(e)


def main() -> int:
    p = argparse.ArgumentParser(description="Check village HTTP endpoints")
    p.add_argument("--orchestrator", default="http://127.0.0.1:9200")
    p.add_argument("--bridge", default="", help="AXL node bridge, e.g. http://127.0.0.1:9002")
    p.add_argument("--yellow-pages-mcp", default="", help="e.g. http://127.0.0.1:9105/mcp")
    p.add_argument("--town-hall-mcp", default="", help="e.g. http://127.0.0.1:9106/mcp")
    args = p.parse_args()

    orch = args.orchestrator.rstrip("/")
    ok_all = True

    url = f"{orch}/v1/health"
    code, body = _get(url)
    if code == 200:
        try:
            j = json.loads(body)
            if j.get("service") == "village-orchestrator":
                print(f"OK  orchestrator  {url}  -> {j}")
            else:
                print(f"WARN orchestrator {url}  unexpected JSON: {body[:200]}")
                ok_all = False
        except json.JSONDecodeError:
            print(f"FAIL orchestrator {url}  not JSON: {body[:200]}")
            ok_all = False
    else:
        print(f"FAIL orchestrator {url}  HTTP {code}  {body[:300]}")
        print("     Start:  uv run python scripts/village/orchestrator.py --listen-port 9200")
        ok_all = False

    if args.bridge:
        turl = f"{args.bridge.rstrip('/')}/topology"
        code, body = _get(turl)
        if code == 200:
            print(f"OK  axl-bridge    {turl}")
        else:
            print(f"FAIL axl-bridge   {turl}  HTTP {code}  {body[:200]}")
            ok_all = False

    if args.yellow_pages_mcp:
        # OPTIONS or POST initialize — minimal check: POST initialize
        init = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "port-check", "version": "0.1"},
                },
                "id": 0,
            }
        ).encode()
        req = urllib.request.Request(
            args.yellow_pages_mcp,
            data=init,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode()
                if resp.status == 200 and "result" in raw:
                    print(f"OK  yellow-pages  {args.yellow_pages_mcp}")
                else:
                    print(f"FAIL yellow-pages {args.yellow_pages_mcp} HTTP {resp.status}")
                    ok_all = False
        except OSError as e:
            print(f"FAIL yellow-pages {args.yellow_pages_mcp}  {e}")
            ok_all = False

    if args.town_hall_mcp:
        init = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "port-check", "version": "0.1"},
                },
                "id": 0,
            }
        ).encode()
        req = urllib.request.Request(
            args.town_hall_mcp,
            data=init,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode()
                if resp.status == 200 and "result" in raw:
                    print(f"OK  town-hall-mcp {args.town_hall_mcp}")
                else:
                    print(f"FAIL town-hall-mcp {args.town_hall_mcp} HTTP {resp.status}")
                    ok_all = False
        except OSError as e:
            print(f"FAIL town-hall-mcp {args.town_hall_mcp}  {e}")
            ok_all = False

    if not ok_all:
        print("\nFix failures above, then create the run and start town_hall.", file=sys.stderr)
        return 1
    print("\nAll probed services OK. Example town_hall:")
    print(
        "  uv run python scripts/village/town_hall.py \\\n"
        "    --bridge http://127.0.0.1:9002 \\\n"
        "    --yellow-pages-peer-id $PEER_MAYOR \\\n"
        "    --orchestrator http://127.0.0.1:9200 \\\n"
        "    --run-id demo3 \\\n"
        "    --max-epochs 1"
    )
    print("\nEnsure you already: curl -X POST .../v1/run/create ... with matching citizen peer ids.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
