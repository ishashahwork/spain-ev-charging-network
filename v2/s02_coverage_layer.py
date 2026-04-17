"""
STEP 2 — Coverage Layer
========================
1. Map existing fast-charging stations onto road segments
2. Identify uncovered intervals exceeding MAX_GAP_ALLOWED_KM along each route
3. Generate coverage candidates to fill gaps

Uses segment sequential ordering (start_km/end_km) instead of geometric
corridor reconstruction — avoids fragmentation issues.

Input:  v2/intermediate/road_segments.gpkg
        data/processed/ev_charging_baseline.csv
Output: v2/intermediate/coverage_candidates.gpkg
        v2/intermediate/existing_on_corridors.csv
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
print("STEP 2 — Coverage Layer")
print("=" * 60)

segments = gpd.read_file(os.path.join(DATA_DIR, "road_segments.gpkg"))
print(f"Loaded {len(segments):,} road segments")

baseline = pd.read_csv(EV_BASELINE_CSV)
print(f"Loaded {len(baseline):,} existing charging stations")

# For COVERAGE analysis, only consider fast chargers (>= 50 kW)
FAST_CHARGE_THRESHOLD_KW = 50
baseline_fast = baseline[baseline['max_power_kw'] >= FAST_CHARGE_THRESHOLD_KW].copy()
print(f"Fast chargers (>= {FAST_CHARGE_THRESHOLD_KW} kW): {len(baseline_fast):,}")

# Convert to GeoDataFrame
baseline_gdf = gpd.GeoDataFrame(
    baseline_fast,
    geometry=gpd.points_from_xy(baseline_fast['longitude'], baseline_fast['latitude']),
    crs=CRS_WGS84,
).to_crs(CRS_METRIC)

# ─────────────────────────────────────────────────────────────
# 2. Map existing stations to nearest segment
# ─────────────────────────────────────────────────────────────
print("\nMapping existing fast chargers to nearest road segment...")

SNAP_DIST_M = SNAP_TO_ROAD_MAX_KM * 1000

# Build spatial index on segment centroids
seg_centroids = segments.geometry.centroid
seg_tree = STRtree(segments.geometry.values)

# Buffer segments for containment check
seg_buffers = segments.geometry.buffer(SNAP_DIST_M)

snapped_records = []

for idx, station in baseline_gdf.iterrows():
    pt = station.geometry
    # Find nearest segment
    nearest_idx = seg_tree.nearest(pt)
    nearest_seg = segments.iloc[nearest_idx]
    dist = nearest_seg.geometry.distance(pt)

    if dist <= SNAP_DIST_M:
        # Compute approximate position along route
        # Use the midpoint of the segment's km range
        seg_mid_km = (nearest_seg['start_km'] + nearest_seg['end_km']) / 2

        snapped_records.append({
            'site_id': station.get('site_id', f'EX_{idx}'),
            'route_segment': nearest_seg['route_segment'],
            'segment_id': nearest_seg['segment_id'],
            'along_road_km': seg_mid_km,
            'snap_distance_m': dist,
            'max_power_kw': station.get('max_power_kw', 50),
            'total_power_kw': station.get('total_power_kw', 100),
            'n_connectors': station.get('n_connectors', 2),
            'latitude': station['latitude'] if 'latitude' in station.index else pt.y,
            'longitude': station['longitude'] if 'longitude' in station.index else pt.x,
        })

snapped_df = pd.DataFrame(snapped_records)
print(f"Snapped {len(snapped_df):,} fast chargers to road segments "
      f"(out of {len(baseline_gdf):,} total)")

# Save for later use
snapped_df.to_csv(os.path.join(DATA_DIR, "existing_on_corridors.csv"), index=False)

# ─────────────────────────────────────────────────────────────
# 3. Identify coverage gaps per route
# ─────────────────────────────────────────────────────────────
print("\nIdentifying coverage gaps per route...")

# For each route, get all segments ordered by start_km
# Mark which segments have existing fast chargers
# Find gaps (consecutive km without a station) > MAX_GAP_ALLOWED_KM

routes = segments.groupby('route_segment')
coverage_candidates = []
cand_id = 0
gap_stats = []

for route_name, route_segs in routes:
    route_segs = route_segs.sort_values('start_km')
    route_total_km = route_segs['end_km'].max()

    if route_total_km < 30:  # skip short routes
        continue

    # Positions of existing fast chargers on this route
    route_stations = snapped_df[snapped_df['route_segment'] == route_name]
    station_positions = sorted(route_stations['along_road_km'].unique().tolist())

    # Add virtual boundary points
    all_positions = [0.0] + station_positions + [route_total_km]

    # Find gaps
    for i in range(len(all_positions) - 1):
        gap_start = all_positions[i]
        gap_end = all_positions[i + 1]
        gap_km = gap_end - gap_start

        gap_stats.append(gap_km)

        if gap_km > MAX_GAP_ALLOWED_KM:
            # Need to fill this gap
            n_new = max(1, int(np.ceil(gap_km / TARGET_SPACING_KM)) - 1)

            for j in range(1, n_new + 1):
                frac = j / (n_new + 1)
                insert_km = gap_start + frac * gap_km

                # Find the segment that contains this km position
                containing_seg = route_segs[
                    (route_segs['start_km'] <= insert_km) &
                    (route_segs['end_km'] > insert_km)
                ]
                if len(containing_seg) == 0:
                    containing_seg = route_segs.iloc[[-1]]  # last segment

                seg = containing_seg.iloc[0]
                # Get a point on the segment geometry
                seg_geom = seg.geometry
                # Fraction within this segment
                seg_frac = (insert_km - seg['start_km']) / max(seg['segment_length_km'], 0.1)
                seg_frac = np.clip(seg_frac, 0, 1)

                try:
                    pt = seg_geom.interpolate(seg_frac, normalized=True)
                except:
                    pt = seg_geom.centroid

                pt_wgs = gpd.GeoSeries([pt], crs=CRS_METRIC).to_crs(CRS_WGS84).iloc[0]

                cand_id += 1
                coverage_candidates.append({
                    'candidate_id': f"COV_{cand_id:04d}",
                    'route_segment': route_name,
                    'along_road_km': round(insert_km, 2),
                    'gap_km': round(gap_km, 1),
                    'candidate_type': 'coverage',
                    'corridor_class': seg['corridor_class'],
                    'latitude': pt_wgs.y,
                    'longitude': pt_wgs.x,
                    'geometry': pt,
                })

cov_gdf = gpd.GeoDataFrame(coverage_candidates, crs=CRS_METRIC) if coverage_candidates else \
    gpd.GeoDataFrame(columns=['candidate_id', 'route_segment', 'geometry'],
                     geometry='geometry', crs=CRS_METRIC)

# ─────────────────────────────────────────────────────────────
# 4. Summary
# ─────────────────────────────────────────────────────────────
gap_arr = np.array(gap_stats)
print(f"\n{'='*60}")
print("COVERAGE SUMMARY")
print(f"{'='*60}")
print(f"Existing fast chargers on corridors: {len(snapped_df):,}")
print(f"Routes analyzed (>30 km):  {sum(1 for _, g in routes if g['end_km'].max() >= 30)}")
print(f"\nGap statistics (km):")
print(f"  Total gaps:    {len(gap_arr)}")
print(f"  Mean gap:      {gap_arr.mean():.1f} km")
print(f"  Median gap:    {np.median(gap_arr):.1f} km")
print(f"  Max gap:       {gap_arr.max():.1f} km")
print(f"  Gaps > 60 km:  {(gap_arr > 60).sum()}")
print(f"  Gaps > 100 km: {(gap_arr > 100).sum()}")
print(f"  Gaps > 150 km: {(gap_arr > 150).sum()}")
print(f"\nCoverage candidates generated: {len(cov_gdf):,}")

if len(cov_gdf) > 0:
    print(f"\nCoverage candidates by route:")
    print(cov_gdf['route_segment'].value_counts().head(20).to_string())

# Save
out_path = os.path.join(DATA_DIR, "coverage_candidates.gpkg")
if len(cov_gdf) > 0:
    cov_gdf.to_file(out_path, driver="GPKG")
else:
    print("\nNOTE: No coverage gaps found — existing fast charger network covers all corridors")
    print("This is expected: Spain has dense fast-charging on major motorways")
    print("The demand-reinforcement layer (Step 3) will still generate candidates")
print(f"\nSaved → {out_path}")
