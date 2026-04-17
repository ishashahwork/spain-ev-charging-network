"""
STEP 5 — Grid Feasibility + Adaptive Sizing
=============================================
1. Match each candidate to nearest grid substation
2. Compute grid load ratio
3. Adaptive sizing loop: adjust chargers based on grid feasibility
4. Identify friction points

Input:  v2/intermediate/unified_candidates.gpkg
        data/processed/grid_substations_dedup.gpkg
Output: v2/intermediate/final_candidates.gpkg
        v2/intermediate/friction_points.gpkg
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.strtree import STRtree
import warnings, os, sys
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from config import *

# ─────────────────────────────────────────────────────────────
# 1. Load data
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 5 — Grid Feasibility & Adaptive Sizing")
print("=" * 60)

candidates = gpd.read_file(os.path.join(DATA_DIR, "unified_candidates.gpkg"))
subs = gpd.read_file(GRID_SUBS_GPKG)

# Ensure same CRS
candidates = candidates.to_crs(CRS_METRIC)
subs = subs.to_crs(CRS_METRIC)

print(f"Candidates: {len(candidates)}")
print(f"Grid substations: {len(subs)}")

# ─────────────────────────────────────────────────────────────
# 2. Estimate capacity where missing
# ─────────────────────────────────────────────────────────────
print("\n--- Estimating capacity from voltage where missing ---")

def estimate_capacity(row):
    """Estimate capacity_mw from voltage_kv when capacity is 0 or missing."""
    cap = row.get('capacity_mw', 0)
    if pd.notna(cap) and cap > 0:
        return cap
    voltage = row.get('voltage_kv', 0)
    if pd.isna(voltage) or voltage <= 0:
        return 1.0  # minimum fallback: 1 MW
    # Find closest voltage in map
    best_v = min(VOLTAGE_CAPACITY_MAP.keys(), key=lambda v: abs(v - voltage))
    return VOLTAGE_CAPACITY_MAP[best_v]

subs['capacity_mw_est'] = subs.apply(estimate_capacity, axis=1)

print(f"Substations with original capacity: {(subs['capacity_mw'] > 0).sum()}")
print(f"Substations with estimated capacity: {(subs['capacity_mw_est'] > 0).sum()}")
print(f"Capacity range: {subs['capacity_mw_est'].min():.1f} - {subs['capacity_mw_est'].max():.1f} MW")

# ─────────────────────────────────────────────────────────────
# 3. Match candidates to nearest substation
# ─────────────────────────────────────────────────────────────
print("\n--- Matching candidates to nearest substations ---")

sub_tree = STRtree(subs.geometry.values)

candidates['nearest_sub_idx'] = -1
candidates['nearest_sub_dist_km'] = np.nan
candidates['distributor_network'] = ''
candidates['sub_capacity_mw'] = 0.0
candidates['sub_voltage_kv'] = 0.0
candidates['substation_name'] = ''

for idx, cand in candidates.iterrows():
    nearest_idx = sub_tree.nearest(cand.geometry)
    nearest_sub = subs.iloc[nearest_idx]
    dist_m = cand.geometry.distance(nearest_sub.geometry)

    candidates.at[idx, 'nearest_sub_idx'] = nearest_idx
    candidates.at[idx, 'nearest_sub_dist_km'] = dist_m / 1000
    candidates.at[idx, 'distributor_network'] = nearest_sub['distributor_network']
    candidates.at[idx, 'sub_capacity_mw'] = nearest_sub['capacity_mw_est']
    candidates.at[idx, 'sub_voltage_kv'] = nearest_sub['voltage_kv']
    candidates.at[idx, 'substation_name'] = nearest_sub.get('substation_name', '')

print(f"Avg distance to nearest substation: {candidates['nearest_sub_dist_km'].mean():.1f} km")
print(f"\nDistributor distribution:")
print(candidates['distributor_network'].value_counts().to_string())

# ─────────────────────────────────────────────────────────────
# 4. Grid load ratio + classification
# ─────────────────────────────────────────────────────────────
print("\n--- Computing grid load ratio ---")

# proposed_demand_kw is in kW, capacity is in MW → convert
candidates['available_capacity_kw'] = candidates['sub_capacity_mw'] * 1000

candidates['grid_load_ratio'] = (
    candidates['proposed_demand_kw'] / candidates['available_capacity_kw']
).replace([np.inf, -np.inf], 1.0).fillna(1.0)

def classify_grid(ratio):
    if ratio <= GRID_RATIO_SUFFICIENT:
        return 'Sufficient'
    elif ratio <= GRID_RATIO_MODERATE:
        return 'Moderate'
    else:
        return 'Congested'

candidates['grid_status_initial'] = candidates['grid_load_ratio'].apply(classify_grid)

print(f"Initial grid status:")
print(candidates['grid_status_initial'].value_counts().to_string())

# ─────────────────────────────────────────────────────────────
# 5. ADAPTIVE SIZING LOOP (Critical Section 10)
# ─────────────────────────────────────────────────────────────
print("\n--- Adaptive Sizing Loop ---")

candidates['n_chargers_adjusted'] = candidates['n_chargers_initial'].copy()
candidates['sizing_action'] = 'kept'

for idx, cand in candidates.iterrows():
    status = cand['grid_status_initial']
    n_initial = int(cand['n_chargers_initial'])
    cap_kw = cand['available_capacity_kw']

    if status == 'Sufficient':
        # Case 1: keep as-is
        candidates.at[idx, 'n_chargers_adjusted'] = n_initial
        candidates.at[idx, 'sizing_action'] = 'kept'

    elif status == 'Moderate':
        # Case 2: try reducing by 2 chargers to improve ratio
        n_try = max(CHARGER_MIN, n_initial - 2)
        new_ratio = (n_try * CHARGER_KW) / cap_kw if cap_kw > 0 else 1.0
        if new_ratio <= GRID_RATIO_SUFFICIENT:
            candidates.at[idx, 'n_chargers_adjusted'] = n_try
            candidates.at[idx, 'sizing_action'] = 'reduced_to_sufficient'
        else:
            # Keep original but flag as constrained
            candidates.at[idx, 'n_chargers_adjusted'] = n_initial
            candidates.at[idx, 'sizing_action'] = 'kept_moderate'

    elif status == 'Congested':
        # Case 3: try reducing until Moderate or Sufficient
        best_n = n_initial
        best_action = 'friction_point'

        for n_try in range(n_initial, CHARGER_MIN - 1, -1):
            ratio = (n_try * CHARGER_KW) / cap_kw if cap_kw > 0 else 1.0
            if ratio <= GRID_RATIO_MODERATE:
                best_n = n_try
                best_action = 'reduced_to_moderate'
                break
            elif ratio <= GRID_RATIO_SUFFICIENT:
                best_n = n_try
                best_action = 'reduced_to_sufficient'
                break

        candidates.at[idx, 'n_chargers_adjusted'] = best_n
        candidates.at[idx, 'sizing_action'] = best_action

# Recompute demand and grid status after adjustment
candidates['proposed_demand_kw_adj'] = candidates['n_chargers_adjusted'] * CHARGER_KW
candidates['grid_load_ratio_adj'] = (
    candidates['proposed_demand_kw_adj'] / candidates['available_capacity_kw']
).replace([np.inf, -np.inf], 1.0).fillna(1.0)
candidates['grid_status'] = candidates['grid_load_ratio_adj'].apply(classify_grid)

print(f"\nSizing actions:")
print(candidates['sizing_action'].value_counts().to_string())
print(f"\nFinal grid status (after adjustment):")
print(candidates['grid_status'].value_counts().to_string())
print(f"\nCharger change: {candidates['n_chargers_initial'].sum()} → {candidates['n_chargers_adjusted'].sum()}")

# ─────────────────────────────────────────────────────────────
# 6. Identify friction points (Section 11)
# ─────────────────────────────────────────────────────────────
print("\n--- Identifying Friction Points ---")

friction = candidates[candidates['grid_status'].isin(['Moderate', 'Congested'])].copy()
friction['bottleneck_id'] = [f"FRIC_{i+1:04d}" for i in range(len(friction))]

print(f"Friction points: {len(friction)}")
if len(friction) > 0:
    print(f"\nFriction by distributor:")
    print(friction['distributor_network'].value_counts().to_string())
    print(f"\nFriction by status:")
    print(friction['grid_status'].value_counts().to_string())

# Save friction points
if len(friction) > 0:
    friction.to_file(os.path.join(DATA_DIR, "friction_points.gpkg"), driver="GPKG")

# ─────────────────────────────────────────────────────────────
# 7. Set final columns + save
# ─────────────────────────────────────────────────────────────
candidates['n_chargers_proposed'] = candidates['n_chargers_adjusted'].astype(int)
candidates['estimated_demand_kw'] = candidates['n_chargers_proposed'] * CHARGER_KW
candidates['coverage_candidate_flag'] = candidates['candidate_type'].str.contains('coverage', na=False).astype(int)
candidates['demand_candidate_flag'] = candidates['candidate_type'].str.contains('demand', na=False).astype(int)

# Update lat/lon to WGS84
cands_wgs = candidates.to_crs(CRS_WGS84)
candidates['latitude'] = cands_wgs.geometry.y
candidates['longitude'] = cands_wgs.geometry.x

candidates.to_file(os.path.join(DATA_DIR, "final_candidates.gpkg"), driver="GPKG")
print(f"\nSaved {len(candidates)} final candidates → {DATA_DIR}/final_candidates.gpkg")

print(f"\n{'='*60}")
print("GRID FEASIBILITY SUMMARY")
print(f"{'='*60}")
print(f"Total candidates:       {len(candidates)}")
print(f"Sufficient:             {(candidates['grid_status'] == 'Sufficient').sum()}")
print(f"Moderate:               {(candidates['grid_status'] == 'Moderate').sum()}")
print(f"Congested:              {(candidates['grid_status'] == 'Congested').sum()}")
print(f"Friction points:        {len(friction)}")
print(f"Total chargers:         {candidates['n_chargers_proposed'].sum()}")
print(f"Total capacity:         {candidates['estimated_demand_kw'].sum():,.0f} kW")
