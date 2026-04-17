"""
Notebook 1 — Data Ingestion & EDA
===================================
IE × Iberdrola Datathon — Day 2
Inputs:
  data/processed/interurban_roads.gpkg
  data/processed/ev_charging_baseline.csv
  data/processed/grid_substations.gpkg
  data/processed/ev_monthly_forecast_2026_2027.csv

Outputs:
  data/processed/roads_interurban_filtered.gpkg   — roads filtered to AP/A/N only
  data/processed/charging_interurban_baseline.csv — existing chargers on interurban roads
  data/processed/eda_summary.json                 — key counts for File 1
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import json
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

os.makedirs("data/processed", exist_ok=True)
os.makedirs("outputs/figures", exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# 1. LOAD ROAD NETWORK
# ─────────────────────────────────────────────────────────────────────────────
print("Loading road network...")
roads = gpd.read_file("data/processed/interurban_roads.gpkg")
print(f"  Total segments: {len(roads):,}")
print(f"  CRS: {roads.crs}")
print(f"\nHighway types:")
print(roads['highway'].value_counts().to_string())
print(f"\nRoad categories:")
print(roads['road_category'].value_counts().to_string())

# ─────────────────────────────────────────────────────────────────────────────
# 2. FILTER TO OFFICIAL INTERURBAN CATEGORIES
#    Autopistas (AP-*), Autovías (A-*), Carreteras Nacionales (N-*)
#    Exclude: links, urban sections (already filtered by highway type)
# ─────────────────────────────────────────────────────────────────────────────
print("\nFiltering to interurban roads...")

INTERURBAN_HW = ['motorway', 'trunk', 'primary']
roads_inter = roads[roads['highway'].str.split('_').str[0].isin(INTERURBAN_HW)].copy()

print(f"  Interurban segments: {len(roads_inter):,}")

# Compute total network length
roads_proj = roads_inter.to_crs("EPSG:3857")
total_length_km = roads_proj.geometry.length.sum() / 1000
print(f"  Total interurban network length: {total_length_km:,.0f} km")

# Major corridors
corridors = roads_inter['route_segment'].value_counts()
print(f"\nTop 20 route segments by segment count:")
print(corridors.head(20).to_string())

roads_inter.to_file("data/processed/roads_interurban_filtered.gpkg", driver="GPKG")
print(f"\nSaved filtered roads to data/processed/roads_interurban_filtered.gpkg")

# ─────────────────────────────────────────────────────────────────────────────
# 3. EXISTING EV CHARGING BASELINE — filter to interurban roads
# ─────────────────────────────────────────────────────────────────────────────
print("\nLoading EV charging baseline...")
chargers = pd.read_csv("data/processed/ev_charging_baseline.csv")
chargers = chargers.dropna(subset=['latitude', 'longitude'])
gdf_chargers = gpd.GeoDataFrame(
    chargers,
    geometry=gpd.points_from_xy(chargers['longitude'], chargers['latitude']),
    crs="EPSG:4326"
)
print(f"  Total stations loaded: {len(gdf_chargers):,}")

# Buffer roads by 500m to catch nearby chargers
print("  Spatially joining chargers to interurban roads (500m buffer)...")
roads_buf = roads_inter.to_crs("EPSG:3857").copy()
roads_buf['geometry'] = roads_buf.buffer(500)
roads_buf = roads_buf.to_crs("EPSG:4326")

chargers_proj = gdf_chargers.to_crs("EPSG:4326")
interurban_chargers = gpd.sjoin(chargers_proj, roads_buf[['geometry', 'route_segment', 'road_category']],
                                how='inner', predicate='within')
interurban_chargers = interurban_chargers.drop_duplicates(subset=['site_id'])

total_existing_baseline = len(interurban_chargers)
print(f"  Chargers on interurban roads: {total_existing_baseline:,}  ← File 1 KPI")

# Power distribution
print(f"\n  Power distribution (kW):")
print(interurban_chargers['max_power_kw'].describe().round(1).to_string())
print(f"\n  Fast chargers (>=50kW): {(interurban_chargers['max_power_kw'] >= 50).sum():,}")
print(f"  Ultra-fast (>=150kW):  {(interurban_chargers['max_power_kw'] >= 150).sum():,}")

interurban_chargers.drop(columns='geometry').to_csv(
    "data/processed/charging_interurban_baseline.csv", index=False, encoding='utf-8'
)

# ─────────────────────────────────────────────────────────────────────────────
# 4. GRID SUBSTATIONS EDA
# ─────────────────────────────────────────────────────────────────────────────
print("\nLoading grid substations...")
substations = gpd.read_file("data/processed/grid_substations.gpkg")
print(f"  Total substations: {len(substations):,}")
print(f"  By distributor:\n{substations['distributor_network'].value_counts().to_string()}")

cap = substations['capacity_mw'].dropna()
print(f"\n  Capacity (MW) distribution:")
print(cap.describe().round(2).to_string())
print(f"\n  Substations with >0 MW available: {(cap > 0).sum():,} ({(cap > 0).mean()*100:.1f}%)")
print(f"  Substations with >5 MW available:  {(cap > 5).sum():,}")
print(f"  Substations with >20 MW available: {(cap > 20).sum():,}")

# Proposed thresholds for grid_status (to be justified in report)
# A 150kW charger bank of 4 units = 0.6 MW minimum needed
# Sufficient: > 5 MW available  (can host 8+ fast chargers)
# Moderate:   1–5 MW            (can host 1–7 fast chargers, may need upgrade)
# Congested:  < 1 MW            (insufficient for even 1 fast charger)
substations['grid_status'] = pd.cut(
    substations['capacity_mw'],
    bins=[-np.inf, 1.0, 5.0, np.inf],
    labels=['Congested', 'Moderate', 'Sufficient']
)
print(f"\n  Grid status (proposed thresholds: <1MW=Congested, 1-5MW=Moderate, >5MW=Sufficient):")
print(substations['grid_status'].value_counts().to_string())

substations.to_file("data/processed/grid_substations.gpkg", driver="GPKG")

# ─────────────────────────────────────────────────────────────────────────────
# 5. EV FORECAST SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print("\nLoading EV forecast...")
with open("data/processed/ev_projection_results.json") as f:
    ev_proj = json.load(f)

fc = pd.read_csv("data/processed/ev_monthly_forecast_2026_2027.csv")
print(f"  total_ev_projected_2027: {ev_proj['total_ev_projected_2027']:,}")
print(f"  2027 monthly avg new EVs: {fc[fc['year']==2027]['ev_new_registrations_forecast'].mean():.0f}")

# ─────────────────────────────────────────────────────────────────────────────
# 6. COVERAGE GAP ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
print("\nCoverage gap analysis...")

# Segments with no existing charger within 150km are coverage gaps
# Quick proxy: count segments per route with existing chargers
covered_routes = set(interurban_chargers['route_segment'].dropna().unique())
all_routes = set(roads_inter['route_segment'].dropna().unique())
uncovered_routes = all_routes - covered_routes
print(f"  Route segments with existing chargers: {len(covered_routes):,}")
print(f"  Route segments with NO charger:        {len(uncovered_routes):,}")
print(f"  Coverage rate: {len(covered_routes)/len(all_routes)*100:.1f}%")
print(f"\n  Sample uncovered routes: {sorted(list(uncovered_routes))[:15]}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. SAVE EDA SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
summary = {
    "total_interurban_road_segments": len(roads_inter),
    "total_interurban_network_km": round(total_length_km, 1),
    "total_existing_stations_baseline": total_existing_baseline,
    "total_ev_projected_2027": ev_proj["total_ev_projected_2027"],
    "total_substations_geocoded": len(substations),
    "substations_sufficient": int((substations['grid_status'] == 'Sufficient').sum()),
    "substations_moderate": int((substations['grid_status'] == 'Moderate').sum()),
    "substations_congested": int((substations['grid_status'] == 'Congested').sum()),
    "grid_status_thresholds": {
        "Sufficient_MW": ">5",
        "Moderate_MW": "1–5",
        "Congested_MW": "<1"
    }
}

with open("data/processed/eda_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print("\n" + "="*50)
print("EDA SUMMARY")
print("="*50)
for k, v in summary.items():
    if not isinstance(v, dict):
        print(f"  {k}: {v:,}" if isinstance(v, (int, float)) else f"  {k}: {v}")
print("="*50)
print("\nSaved to data/processed/eda_summary.json")
