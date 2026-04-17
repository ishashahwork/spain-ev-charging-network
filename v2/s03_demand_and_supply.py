"""
STEP 3 — Demand Model + Existing Supply + Gap Analysis
=======================================================
Compute per-segment demand index, existing supply index, and gap.
Generate demand-reinforcement candidates from high-gap clusters.

Input:  v2/intermediate/road_segments.gpkg
        v2/intermediate/existing_on_corridors.csv
        data/processed/ev_charging_baseline.csv
Output: v2/intermediate/segments_with_gap.gpkg
        v2/intermediate/demand_candidates.gpkg
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree
import warnings, os, sys
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from config import *

# ─────────────────────────────────────────────────────────────
# 1. Load data
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 3 — Demand, Supply, and Gap Analysis")
print("=" * 60)

segments = gpd.read_file(os.path.join(DATA_DIR, "road_segments.gpkg"))
print(f"Loaded {len(segments):,} segments")

# Load ALL baseline stations for supply model (not just fast chargers)
baseline_all = pd.read_csv(EV_BASELINE_CSV)
baseline_all_gdf = gpd.GeoDataFrame(
    baseline_all,
    geometry=gpd.points_from_xy(baseline_all['longitude'], baseline_all['latitude']),
    crs=CRS_WGS84,
).to_crs(CRS_METRIC)
print(f"Loaded {len(baseline_all):,} total baseline stations for supply model")

# ─────────────────────────────────────────────────────────────
# 2. DEMAND MODEL (Section 4)
# ─────────────────────────────────────────────────────────────
print("\n--- Computing Demand Index per segment ---")

segments['corridor_multiplier'] = segments['corridor_class'].map(CORRIDOR_MULTIPLIERS).fillna(1.0)
segments['traffic'] = segments['avg_traffic'].fillna(0)

segments['demand_index'] = (
    segments['traffic']
    * EV_SHARE_2027
    * CHARGING_NEED_FACTOR
    * segments['corridor_multiplier']
)

print(f"EV_share_2027:        {EV_SHARE_2027:.4f} ({EV_SHARE_2027*100:.2f}%)")
print(f"Charging_need_factor: {CHARGING_NEED_FACTOR}")
print(f"Demand index range:   {segments['demand_index'].min():.2f} - {segments['demand_index'].max():.2f}")
print(f"Demand index mean:    {segments['demand_index'].mean():.2f}")

# ─────────────────────────────────────────────────────────────
# 3. EXISTING SUPPLY MODEL (Section 5)
# ─────────────────────────────────────────────────────────────
print("\n--- Computing Existing Supply per segment ---")

# Map every baseline station to its nearest road segment (within 5 km)
SUPPLY_SNAP_M = SNAP_TO_ROAD_MAX_KM * 1000
seg_tree = STRtree(segments.geometry.values)

station_to_seg = []
for idx, station in baseline_all_gdf.iterrows():
    nearest_idx = seg_tree.nearest(station.geometry)
    dist = segments.iloc[nearest_idx].geometry.distance(station.geometry)
    if dist <= SUPPLY_SNAP_M:
        pw = station.get('total_power_kw', 0)
        if pd.isna(pw) or pw <= 0:
            pw = DEFAULT_SUPPLY_PER_STATION_KW
        station_to_seg.append({
            'segment_id': segments.iloc[nearest_idx]['segment_id'],
            'supply_kw': pw,
        })

station_seg_df = pd.DataFrame(station_to_seg)
print(f"Mapped {len(station_seg_df):,} stations to segments")

# Aggregate supply per segment
if len(station_seg_df) > 0:
    supply_agg = station_seg_df.groupby('segment_id').agg(
        existing_supply_kw=('supply_kw', 'sum'),
        existing_station_count=('supply_kw', 'count'),
    ).reset_index()
    segments = segments.merge(supply_agg, on='segment_id', how='left')
    segments['existing_supply_kw'] = segments['existing_supply_kw'].fillna(0)
    segments['existing_station_count'] = segments['existing_station_count'].fillna(0).astype(int)
else:
    segments['existing_supply_kw'] = 0.0
    segments['existing_station_count'] = 0

print(f"Segments with existing supply: {(segments['existing_supply_kw'] > 0).sum()}")
print(f"Total existing supply on corridors: {segments['existing_supply_kw'].sum():,.0f} kW")

# ─────────────────────────────────────────────────────────────
# 4. GAP ANALYSIS
# ─────────────────────────────────────────────────────────────
print("\n--- Computing Demand Gap per segment ---")

# Convert demand_index (daily EVs needing charge) to kW-equivalent
# Each 150 kW charger serves ~48 sessions/day (15-min avg, 12 peak hours)
SESSIONS_PER_CHARGER_DAY = 48
segments['demand_kw_equiv'] = (segments['demand_index'] / SESSIONS_PER_CHARGER_DAY) * CHARGER_KW

# Gap = demand - existing supply
segments['gap_kw'] = segments['demand_kw_equiv'] - segments['existing_supply_kw']

print(f"Gap kW range: {segments['gap_kw'].min():.0f} to {segments['gap_kw'].max():.0f}")
print(f"Segments with positive gap: {(segments['gap_kw'] > 0).sum()} / {len(segments)}")

# Save
segments.to_file(os.path.join(DATA_DIR, "segments_with_gap.gpkg"), driver="GPKG")

# ─────────────────────────────────────────────────────────────
# 5. DEMAND-REINFORCEMENT CANDIDATES (Section 6)
# ─────────────────────────────────────────────────────────────
print("\n--- Generating Demand-Reinforcement Candidates ---")

# Identify high-gap segments (top 25% of positive-gap segments)
positive_gap = segments[segments['gap_kw'] > 0].copy()
if len(positive_gap) > 0:
    gap_threshold = positive_gap['gap_kw'].quantile(0.75)
    high_gap = positive_gap[positive_gap['gap_kw'] >= gap_threshold].copy()
else:
    high_gap = gpd.GeoDataFrame(columns=segments.columns, crs=CRS_METRIC)

print(f"Positive-gap segments: {len(positive_gap)}")
print(f"High-gap segments (top 25%): {len(high_gap)}")
print(f"Gap threshold: {gap_threshold:.1f} kW" if len(positive_gap) > 0 else "")

# Cluster adjacent high-gap segments on the same route
demand_candidates = []
dcand_id = 0

if len(high_gap) > 0:
    for route, group in high_gap.groupby('route_segment'):
        group = group.sort_values('start_km')
        rows = [group.iloc[i] for i in range(len(group))]

        # Cluster consecutive segments (gap < 2× segment length)
        clusters = []
        current_cluster = [rows[0]]

        for i in range(1, len(rows)):
            prev_end = current_cluster[-1]['end_km']
            curr_start = rows[i]['start_km']

            if curr_start - prev_end <= SEGMENT_LENGTH_KM * 2:
                current_cluster.append(rows[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [rows[i]]
        clusters.append(current_cluster)

        # Generate one candidate per cluster
        for cluster in clusters:
            total_gap = sum(r['gap_kw'] for r in cluster)
            avg_traffic = np.mean([r['avg_traffic'] for r in cluster])

            # Use the middle segment's geometry for placement
            mid_seg = cluster[len(cluster) // 2]
            try:
                centroid = mid_seg.geometry.interpolate(0.5, normalized=True)
            except:
                centroid = mid_seg.geometry.centroid
            centroid_wgs = gpd.GeoSeries([centroid], crs=CRS_METRIC).to_crs(CRS_WGS84).iloc[0]

            mid_km = (cluster[0]['start_km'] + cluster[-1]['end_km']) / 2

            dcand_id += 1
            demand_candidates.append({
                'candidate_id': f"DEM_{dcand_id:04d}",
                'route_segment': route,
                'along_road_km': mid_km,
                'cluster_gap_kw': total_gap,
                'cluster_avg_traffic': avg_traffic,
                'cluster_n_segments': len(cluster),
                'candidate_type': 'demand',
                'latitude': centroid_wgs.y,
                'longitude': centroid_wgs.x,
                'corridor_class': cluster[0]['corridor_class'],
                'geometry': centroid,
            })

dem_gdf = gpd.GeoDataFrame(demand_candidates, crs=CRS_METRIC) if demand_candidates else \
    gpd.GeoDataFrame(columns=['candidate_id', 'route_segment', 'geometry'],
                     geometry='geometry', crs=CRS_METRIC)

print(f"Demand-reinforcement candidates: {len(dem_gdf):,}")

# Save
out_path = os.path.join(DATA_DIR, "demand_candidates.gpkg")
if len(dem_gdf) > 0:
    dem_gdf.to_file(out_path, driver="GPKG")
    print(f"\nTop 10 demand candidates:")
    print(dem_gdf.nlargest(10, 'cluster_gap_kw')[
        ['candidate_id', 'route_segment', 'cluster_gap_kw', 'cluster_avg_traffic']
    ].to_string())

print(f"\nSaved → {out_path}")

# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("DEMAND & SUPPLY SUMMARY")
print(f"{'='*60}")
print(f"Total segments:           {len(segments):,}")
print(f"Segments with supply:     {(segments['existing_supply_kw'] > 0).sum()}")
print(f"Segments with gap > 0:    {(segments['gap_kw'] > 0).sum()}")
print(f"High-gap segments:        {len(high_gap)}")
print(f"Demand candidates:        {len(dem_gdf):,}")
