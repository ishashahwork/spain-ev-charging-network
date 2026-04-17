"""
Grid Viability Analysis — Spatial Join & Friction Point Detection
=================================================================
For each proposed station (from 03_optimization.py), finds the nearest
electricity substation and estimates whether the local grid can absorb
the added EV charging demand.

Grid status classification (thresholds justified below):
  Sufficient  — demand < 20% of estimated substation capacity
  Moderate    — 20% ≤ demand < 60% of estimated substation capacity
  Congested   — demand ≥ 60% of estimated substation capacity

Capacity estimation:
  Where capacity_mw > 0: use directly.
  Where capacity_mw = 0 (majority of substations): estimate from voltage_kv
  using standard Spanish grid capacity rules of thumb:
    132 kV → 120 MW   (AT, alta tensión — transmission level)
    110 kV → 80 MW
     66 kV → 40 MW
     45 kV → 20 MW
     30 kV → 10 MW
    ≤25 kV → 5 MW     (MT, media tensión — distribution level)

Inputs:
  data/processed/proposed_stations.gpkg       ← from 03_optimization.py
  data/processed/grid_substations_dedup.csv   ← from 01c_deduplicate_grid.py

Outputs:
  outputs/File 2.csv                          ← updated with real grid_status
  outputs/File 3.csv                          ← friction points only
  data/processed/grid_analysis.gpkg           ← full spatial result
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings("ignore")

os.makedirs("outputs", exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
CHARGER_KW = 150  # fixed by competition rules

# Voltage → estimated substation capacity (MW)
# Based on Spanish REE / distributor published norms
VOLTAGE_TO_CAPACITY_MW = {
    132: 120.0,
    110:  80.0,
     66:  40.0,
     55:  30.0,
     45:  20.0,
     30:  10.0,
     25:   5.0,
     20:   4.0,
     15:   3.0,
     13:   2.0,
     11:   2.0,
     10:   1.5,
}

# Grid status thresholds (fraction of substation capacity)
# Justified: 20% threshold = standard Spanish distributor planning reserve
# 60% threshold = congestion flag used by i-DE in capacity maps
SUFFICIENT_THRESHOLD  = 0.20   # < 20% → grid can absorb easily
MODERATE_THRESHOLD    = 0.60   # 20–60% → reinforcement may be needed
# ≥ 60% → Congested

CRS_METRIC = "EPSG:3857"
CRS_WGS84  = "EPSG:4326"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load proposed stations
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1 — Load proposed stations")
print("=" * 60)

STATIONS_FILE = "data/processed/proposed_stations.gpkg"
if not os.path.exists(STATIONS_FILE):
    raise FileNotFoundError(
        f"{STATIONS_FILE} not found. Run 03_optimization.py first."
    )

stations = gpd.read_file(STATIONS_FILE).to_crs(CRS_WGS84)
print(f"  Loaded {len(stations):,} proposed stations")
print(f"  Columns: {list(stations.columns)}")

# Compute estimated_demand_kw for each station
stations["estimated_demand_kw"] = stations["n_chargers_proposed"] * CHARGER_KW
print(f"  Total demand: {stations['estimated_demand_kw'].sum():,} kW "
      f"({stations['estimated_demand_kw'].sum()/1000:.1f} MW)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Load grid substations
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2 — Load grid substations")
print("=" * 60)

substations = pd.read_csv("data/processed/grid_substations_dedup.csv")
print(f"  Loaded {len(substations):,} substations")
print(f"  Distributors: {substations['distributor_network'].value_counts().to_dict()}")
print(f"  capacity_mw > 0: {(substations['capacity_mw'] > 0).sum()} "
      f"({(substations['capacity_mw'] > 0).mean()*100:.1f}%)")

# Estimate capacity where missing (capacity_mw = 0)
def estimate_capacity_mw(row):
    if row["capacity_mw"] > 0:
        return row["capacity_mw"]
    # Find closest voltage level in lookup table
    voltage = row["voltage_kv"]
    voltages = sorted(VOLTAGE_TO_CAPACITY_MW.keys())
    closest = min(voltages, key=lambda v: abs(v - voltage))
    # Scale up for substations with multiple voltage levels (more infrastructure)
    n_levels = row.get("n_voltage_levels", 1)
    multiplier = 1.0 + (n_levels - 1) * 0.3  # each extra level adds 30%
    return VOLTAGE_TO_CAPACITY_MW[closest] * multiplier

substations["capacity_mw_estimated"] = substations.apply(estimate_capacity_mw, axis=1)
substations["capacity_kw_estimated"] = substations["capacity_mw_estimated"] * 1000

print(f"\n  Estimated capacity stats (MW):")
print(substations["capacity_mw_estimated"].describe().round(2).to_string())

# Convert to GeoDataFrame
sub_gdf = gpd.GeoDataFrame(
    substations,
    geometry=gpd.points_from_xy(substations["longitude"], substations["latitude"]),
    crs=CRS_WGS84,
)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Spatial join: nearest substation for each station
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3 — Nearest substation spatial join")
print("=" * 60)

# Project both to metric CRS for distance calculation
stations_m    = stations.to_crs(CRS_METRIC)
substations_m = sub_gdf.to_crs(CRS_METRIC)

# geopandas sjoin_nearest (requires geopandas >= 0.10)
joined = gpd.sjoin_nearest(
    stations_m,
    substations_m[["geometry", "distributor_network", "substation_name",
                   "capacity_mw_estimated", "capacity_kw_estimated",
                   "voltage_kv", "province_name"]],
    how="left",
    distance_col="dist_to_substation_m",
)

joined["dist_to_substation_km"] = (joined["dist_to_substation_m"] / 1000).round(2)
joined = joined.drop(columns=["index_right"], errors="ignore")

print(f"  Joined {len(joined):,} stations to nearest substation")
print(f"  Distance stats (km):")
print(joined["dist_to_substation_km"].describe().round(2).to_string())

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Classify grid_status
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 4 — Classify grid_status")
print("=" * 60)

def classify_grid_status(demand_kw, capacity_kw):
    """
    Thresholds:
      Sufficient  : demand_kw < 20% of capacity_kw
      Moderate    : 20% ≤ demand_kw < 60% of capacity_kw
      Congested   : demand_kw ≥ 60% of capacity_kw
    """
    if capacity_kw <= 0:
        return "Congested"  # unknown capacity = conservative flag
    ratio = demand_kw / capacity_kw
    if ratio < SUFFICIENT_THRESHOLD:
        return "Sufficient"
    elif ratio < MODERATE_THRESHOLD:
        return "Moderate"
    else:
        return "Congested"

joined["grid_status"] = joined.apply(
    lambda r: classify_grid_status(r["estimated_demand_kw"], r["capacity_kw_estimated"]),
    axis=1,
)

status_counts = joined["grid_status"].value_counts()
print(f"\n  Grid status distribution:")
print(status_counts.to_string())
print(f"\n  Thresholds used:")
print(f"    Sufficient  : demand < {SUFFICIENT_THRESHOLD*100:.0f}% of substation capacity")
print(f"    Moderate    : {SUFFICIENT_THRESHOLD*100:.0f}% ≤ demand < {MODERATE_THRESHOLD*100:.0f}%")
print(f"    Congested   : demand ≥ {MODERATE_THRESHOLD*100:.0f}%")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Update File 2 with real grid_status
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 5 — Update File 2 with grid_status")
print("=" * 60)

joined_wgs = joined.to_crs(CRS_WGS84)
joined_wgs["latitude"]  = joined_wgs.geometry.y.round(6)
joined_wgs["longitude"] = joined_wgs.geometry.x.round(6)

file2_cols = [
    "location_id", "latitude", "longitude",
    "route_segment", "n_chargers_proposed", "grid_status"
]
file2 = joined_wgs[file2_cols].copy()
file2.to_csv("outputs/File 2.csv", index=False, encoding="utf-8")
print(f"  Saved outputs/File 2.csv  ({len(file2):,} rows)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Build File 3 (friction points: Moderate + Congested only)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 6 — Build File 3 (friction points)")
print("=" * 60)

friction = joined_wgs[joined_wgs["grid_status"].isin(["Moderate", "Congested"])].copy()
friction = friction.reset_index(drop=True)
friction["bottleneck_id"] = [f"FRIC_{i+1:03d}" for i in range(len(friction))]

# Map location_id → distributor (from nearest substation join)
file3_cols = [
    "bottleneck_id", "latitude", "longitude",
    "route_segment", "distributor_network",
    "estimated_demand_kw", "grid_status"
]
file3 = friction[file3_cols].copy()
file3["estimated_demand_kw"] = file3["estimated_demand_kw"].round(1)

file3.to_csv("outputs/File 3.csv", index=False, encoding="utf-8")
print(f"  Saved outputs/File 3.csv  ({len(file3):,} rows)")
print(f"\n  Friction breakdown:")
print(file3["grid_status"].value_counts().to_string())
print(f"\n  Top friction distributors:")
print(file3["distributor_network"].value_counts().to_string())

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Save full spatial result
# ─────────────────────────────────────────────────────────────────────────────
save_cols = [c for c in joined_wgs.columns if c not in ["x_m", "y_m"]]
joined_wgs[save_cols].to_file("data/processed/grid_analysis.gpkg", driver="GPKG")
print(f"\n  Saved data/processed/grid_analysis.gpkg")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Generate File 1 KPIs (partial — total_proposed_stations,
#          total_friction_points, total_ev_projected_2027)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 8 — File 1 KPI preview")
print("=" * 60)

import json
with open("data/processed/ev_projection_results.json") as f:
    ev_proj = json.load(f)

# total_existing_stations_baseline: count ev_charging_baseline filtered to
# interurban roads (spatial join needed — done in 05_generate_outputs.py)
# For now print what we have
print(f"  total_proposed_stations:    {len(file2):,}     (= File 2 row count)")
print(f"  total_friction_points:      {len(file3):,}     (= File 3 row count)")
print(f"  total_ev_projected_2027:    {ev_proj['total_ev_projected_2027']:,}")
print(f"  total_existing_baseline:    TBD (needs interurban spatial filter)")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("GRID ANALYSIS SUMMARY")
print("=" * 60)
print(f"  Proposed stations:          {len(file2):,}")
print(f"  Sufficient (no action):     {status_counts.get('Sufficient', 0):,}")
print(f"  Moderate (reinforcement?):  {status_counts.get('Moderate', 0):,}")
print(f"  Congested (must reinforce): {status_counts.get('Congested', 0):,}")
print(f"  Total friction points:      {len(file3):,}")
print(f"  Total EV demand:            {joined['estimated_demand_kw'].sum()/1000:.1f} MW")
print(f"\n  Classification thresholds justified:")
print(f"    <{SUFFICIENT_THRESHOLD*100:.0f}% capacity  → Sufficient  (standard planning reserve)")
print(f"    <{MODERATE_THRESHOLD*100:.0f}% capacity  → Moderate    (i-DE congestion threshold)")
print(f"    ≥{MODERATE_THRESHOLD*100:.0f}% capacity  → Congested   (requires grid reinforcement)")
