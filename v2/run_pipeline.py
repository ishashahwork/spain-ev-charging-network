"""
V2 Pipeline Runner — Hybrid EV Charging Network
=================================================
Runs all steps sequentially. Execute from the v2/ directory.
"""
import subprocess, sys, os, time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

steps = [
    "s01_segment_roads.py",
    "s02_coverage_layer.py",
    "s03_demand_and_supply.py",
    "s04_merge_and_snap.py",
    "s05_grid_feasibility.py",
    "s06_prioritize_and_output.py",
]

print("=" * 60)
print("V2 HYBRID EV CHARGING NETWORK PIPELINE")
print("=" * 60)

t0 = time.time()
for i, step in enumerate(steps):
    print(f"\n{'#' * 60}")
    print(f"# Running {step} ({i+1}/{len(steps)})")
    print(f"{'#' * 60}\n")

    result = subprocess.run(
        [sys.executable, step],
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"\nERROR: {step} failed with exit code {result.returncode}")
        sys.exit(1)

elapsed = time.time() - t0
print(f"\n{'=' * 60}")
print(f"PIPELINE COMPLETE — {elapsed:.0f}s total")
print(f"{'=' * 60}")
