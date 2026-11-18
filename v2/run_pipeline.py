"""Run the current pipeline from any working directory, with input checks."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

import config

PIPELINE_DIR = Path(__file__).resolve().parent
STEPS = [
    "s01_segment_roads.py",
    "s02_coverage_layer.py",
    "s03_demand_and_supply.py",
    "s04_merge_and_snap.py",
    "s05_grid_feasibility.py",
    "s06_prioritize_and_output.py",
]


def check_inputs():
    """Check files without importing analysis libraries or writing outputs."""
    required = [config.ROADS_GPKG, config.EV_BASELINE_CSV,
                config.GRID_SUBS_GPKG, config.EV_PROJECTION_JSON]
    missing = []
    for relative in required:
        path = (PIPELINE_DIR / relative).resolve()
        exists = path.is_file() and path.stat().st_size > 0
        print(f"{'OK' if exists else 'MISSING'}: {relative}")
        if not exists:
            missing.append(relative)
    amenities = (PIPELINE_DIR / config.AMENITIES_DIR).resolve()
    for name in ("fuel", "service_areas", "restaurants", "supermarkets", "hotels"):
        if not (amenities / f"{name}.geojson").is_file():
            print(f"WARNING: missing amenity layer {name}; scoring/siting will differ.")
    if missing:
        print("Restore required inputs using docs/REPRODUCING.md before running.")
    return not missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inputs", action="store_true",
                        help="report input availability without running analysis")
    args = parser.parse_args()
    ready = check_inputs()
    if args.check_inputs or not ready:
        return 0 if ready else 1

    os.chdir(PIPELINE_DIR)
    print("V2 HYBRID EV CHARGING NETWORK PIPELINE", flush=True)
    started = time.monotonic()
    for index, step in enumerate(STEPS, 1):
        print(f"\nRunning {step} ({index}/{len(STEPS)})", flush=True)
        result = subprocess.run([sys.executable, step], check=False)
        if result.returncode:
            print(f"ERROR: {step} failed with exit code {result.returncode}")
            return result.returncode
    print(f"PIPELINE COMPLETE — {time.monotonic() - started:.0f}s total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
