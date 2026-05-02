#!/usr/bin/env python3
"""
Run policy calibration experiments to find tax/UBI settings that drive Gini down.
"""
import json, subprocess, sys, time

EXPERIMENTS = [
    # (name, tax_adjust, ubi_adjust, gini_target)
    ("baseline",      0.2,  20, 0.05),
    ("tax_aggressive", 0.5,  20, 0.05),
    ("tax_extreme",   1.0,  20, 0.05),
    ("ubi_high",      0.2,  40, 0.05),
    ("ubi_extreme",   0.2,  80, 0.05),
    ("both_aggro",    0.5,  40, 0.05),
    ("both_extreme",  1.0,  80, 0.05),
    ("low_target",    0.2,  20, 0.02),
]

def run_exp(name, tax_mul, ubi_mul, target):
    run_id = f"calib_{name}"
    cmd = [
        sys.executable, "scripts/village/run_village.py",
        "--run-id", run_id,
        "--epochs", "8",
        "--actions-per-epoch", "8",
        "--num-citizens", "6",
        "--tax-adjust", str(tax_mul),
        "--ubi-adjust", str(ubi_mul),
        "--gini-target", str(target),
    ]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    elapsed = time.time() - t0
    # Parse gini from output
    ginis = []
    for line in r.stdout.splitlines():
        if line.startswith("Gini    :"):
            ginis.append(float(line.split(":")[1].strip()))
    return {"name": name, "ginis": ginis, "time": round(elapsed, 1), "params": (tax_mul, ubi_mul, target)}

results = []
for name, tax_mul, ubi_mul, target in EXPERIMENTS:
    print(f"\n{'='*60}")
    print(f"Experiment: {name} (tax_mul={tax_mul}, ubi_mul={ubi_mul}, target={target})")
    print(f"{'='*60}")
    try:
        res = run_exp(name, tax_mul, ubi_mul, target)
        results.append(res)
        print(f"  Ginis: {[round(g,4) for g in res['ginis']]}")
        if len(res['ginis']) >= 2:
            trend = res['ginis'][-1] - res['ginis'][0]
            print(f"  Trend: {trend:+.4f} ({'DOWN' if trend < 0 else 'UP'})")
        print(f"  Time: {res['time']}s")
    except Exception as e:
        print(f"  FAILED: {e}")

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
print(f"{'Name':20s} {'Params':30s} {'Ginis':40s} {'Trend':10s}")
print("-"*100)
for r in results:
    g = [round(x,4) for x in r['ginis']]
    trend = g[-1] - g[0] if len(g) >= 2 else 0
    trend_str = f"{trend:+.4f} ({'DOWN' if trend < 0 else 'UP'})"
    params = f"t={r['params'][0]}, u={r['params'][1]}, tg={r['params'][2]}"
    print(f"{r['name']:20s} {params:30s} {str(g):40s} {trend_str:10s}")
