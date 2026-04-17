"""
STEP 4 — Merge Candidates, Snap to Amenities, Size Stations
=============================================================
1. Merge coverage + demand candidates (coverage-aware deduplication)
2. Snap to nearby amenities / service areas
3. Size stations based on demand gap + corridor importance

Input:  v2/intermediate/coverage_candidates.gpkg
        v2/intermediate/demand_candidates.gpkg
        v2/intermediate/segments_with_gap.gpkg
        data/raw/amenities/*.geojson
Output: v2/intermediate/unified_candidates.gpkg
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
import warnings, os, sys, glob
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from config import *

# ─────────────────────────────────────────────────────────────
# 1. Load candidates
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 4 — Merge Candidates, Snap & Size")
print("=" * 60)

cov_path = os.path.join(DATA_DIR, "coverage_candidates.gpkg")
dem_path = os.path.join(DATA_DIR, "demand_candidates.gpkg")

cov_gdf = gpd.read_file(cov_path) if os.path.exists(cov_path) else \
    gpd.GeoDataFrame(columns=['candidate_id', 'route_segment', 'candidate_type', 'geometry'],
                     geometry='geometry', crs=CRS_METRIC)
dem_gdf = gpd.read_file(dem_path) if os.path.exists(dem_path) else \
    gpd.GeoDataFrame(columns=['candidate_id', 'route_segment', 'candidate_type', 'geometry'],
                     geometry='geometry', crs=CRS_METRIC)

segments = gpd.read_file(os.path.join(DATA_DIR, "segments_with_gap.gpkg"))

print(f"Coverage candidates:  {len(cov_gdf)}")
print(f"Demand candidates:    {len(dem_gdf)}")

# ─────────────────────────────────────────────────────────────
# 2. Merge candidates
# ─────────────────────────────────────────────────────────────
print("\n--- Merging candidate pools ---")

# Standardize columns
for col in ['along_road_km', 'gap_km', 'cluster_gap_kw', 'cluster_avg_traffic', 'corridor_class']:
    if col not in cov_gdf.columns:
        cov_gdf[col] = np.nan
    if col not in dem_gdf.columns:
        dem_gdf[col] = np.nan

common_cols = ['candidate_id', 'route_segment', 'candidate_type', 'latitude', 'longitude',
               'along_road_km', 'gap_km', 'cluster_gap_kw', 'cluster_avg_traffic',
               'corridor_class', 'geometry']

# Ensure both have all columns
for col in common_cols:
    if col not in cov_gdf.columns and col != 'geometry':
        cov_gdf[col] = np.nan
    if col not in dem_gdf.columns and col != 'geometry':
        dem_gdf[col] = np.nan

all_candidates = pd.concat([
    cov_gdf[common_cols],
    dem_gdf[common_cols],
], ignore_index=True)

all_candidates = gpd.GeoDataFrame(all_candidates, crs=CRS_METRIC)
print(f"Total before dedup: {len(all_candidates)}")

# ─────────────────────────────────────────────────────────────
# 3. Coverage-aware deduplication
# ─────────────────────────────────────────────────────────────
print("\n--- Coverage-aware deduplication ---")

DEDUP_DIST_M = 5000  # 5 km — consolidate candidates closer than this

# Mark coverage candidates as protected (cannot be removed)
all_candidates['is_coverage'] = all_candidates['candidate_type'] == 'coverage'
all_candidates['keep'] = True

# Sort: coverage first (protected), then demand by cluster_gap_kw descending
all_candidates = all_candidates.sort_values(
    ['is_coverage', 'cluster_gap_kw'],
    ascending=[False, False]
).reset_index(drop=True)

# Greedy deduplication
for i in range(len(all_candidates)):
    if not all_candidates.at[i, 'keep']:
        continue
    for j in range(i + 1, len(all_candidates)):
        if not all_candidates.at[j, 'keep']:
            continue
        dist = all_candidates.at[i, 'geometry'].distance(all_candidates.at[j, 'geometry'])
        if dist < DEDUP_DIST_M:
            # If j is coverage candidate, don't remove it
            if all_candidates.at[j, 'is_coverage']:
                # Instead, check if i is also coverage — if so, merge metadata
                if all_candidates.at[i, 'is_coverage']:
                    # Two coverage candidates very close — keep the one with larger gap
                    if (all_candidates.at[j, 'gap_km'] or 0) > (all_candidates.at[i, 'gap_km'] or 0):
                        all_candidates.at[i, 'keep'] = False
                    else:
                        all_candidates.at[j, 'keep'] = False
                # else: keep both (coverage + demand → mark as dual)
                else:
                    all_candidates.at[i, 'candidate_type'] = 'coverage+demand'
                    all_candidates.at[j, 'keep'] = False
            else:
                # j is demand, can be removed
                # Transfer demand info to i
                if all_candidates.at[i, 'candidate_type'] == 'coverage':
                    all_candidates.at[i, 'candidate_type'] = 'coverage+demand'
                all_candidates.at[j, 'keep'] = False

unified = all_candidates[all_candidates['keep']].drop(columns=['keep', 'is_coverage']).reset_index(drop=True)
print(f"After dedup: {len(unified)} candidates")

# ─────────────────────────────────────────────────────────────
# 4. Enrich candidates with segment-level demand data
# ─────────────────────────────────────────────────────────────
print("\n--- Enriching with segment demand data ---")

# For each candidate, find nearest segment and get its demand/traffic
from shapely.strtree import STRtree

seg_centroids = segments.geometry.apply(lambda g: g.interpolate(0.5, normalized=True))
seg_tree = STRtree(seg_centroids.values)

for idx, cand in unified.iterrows():
    nearest_idx = seg_tree.nearest(cand.geometry)
    nearest_seg = segments.iloc[nearest_idx]
    unified.at[idx, 'seg_demand_index'] = nearest_seg['demand_index']
    unified.at[idx, 'seg_avg_traffic'] = nearest_seg['avg_traffic']
    unified.at[idx, 'seg_gap_kw'] = nearest_seg['gap_kw']
    unified.at[idx, 'seg_existing_supply'] = nearest_seg['existing_supply_kw']
    if pd.isna(unified.at[idx, 'corridor_class']):
        unified.at[idx, 'corridor_class'] = nearest_seg['corridor_class']

# ─────────────────────────────────────────────────────────────
# 5. Load and score amenities
# ─────────────────────────────────────────────────────────────
print("\n--- Scoring amenities ---")

AMENITY_RADIUS_M = AMENITY_RADIUS_KM * 1000
AMENITY_SNAP_M = AMENITY_SNAP_MAX_KM * 1000

amenity_types = ['fuel', 'service_areas', 'restaurants', 'supermarkets', 'hotels']
amenity_gdfs = {}

for atype in amenity_types:
    fpath = os.path.join(AMENITIES_DIR, f"{atype}.geojson")
    if os.path.exists(fpath):
        a = gpd.read_file(fpath).to_crs(CRS_METRIC)
        amenity_gdfs[atype] = a
        print(f"  {atype}: {len(a):,} features")

# Score each candidate: count amenities within radius
unified['amenity_score'] = 0.0
unified['nearest_amenity_dist_m'] = np.nan
unified['snapped_to_amenity'] = False

# Weights for different amenity types
amenity_weights = {
    'service_areas': 3.0,  # highest — purpose-built for road users
    'fuel': 2.0,           # existing infrastructure, easy to co-locate
    'restaurants': 1.0,
    'supermarkets': 0.5,
    'hotels': 0.5,
}

for idx, cand in unified.iterrows():
    score = 0
    nearest_dist = float('inf')
    nearest_pt = None

    for atype, agdf in amenity_gdfs.items():
        w = amenity_weights.get(atype, 1.0)
        dists = agdf.geometry.distance(cand.geometry)
        nearby = dists[dists <= AMENITY_RADIUS_M]
        score += len(nearby) * w

        # Track closest amenity for potential snapping
        if len(dists) > 0:
            min_dist = dists.min()
            if min_dist < nearest_dist:
                nearest_dist = min_dist
                nearest_pt = agdf.geometry.iloc[dists.idxmin()]

    unified.at[idx, 'amenity_score'] = score
    unified.at[idx, 'nearest_amenity_dist_m'] = nearest_dist

    # Snap to nearest amenity if within snap distance and score is low
    if score == 0 and nearest_dist <= AMENITY_SNAP_M and nearest_pt is not None:
        unified.at[idx, 'geometry'] = nearest_pt
        pt_wgs = gpd.GeoSeries([nearest_pt], crs=CRS_METRIC).to_crs(CRS_WGS84).iloc[0]
        unified.at[idx, 'latitude'] = pt_wgs.y
        unified.at[idx, 'longitude'] = pt_wgs.x
        unified.at[idx, 'snapped_to_amenity'] = True

snapped_count = unified['snapped_to_amenity'].sum()
print(f"Snapped {snapped_count} candidates to nearby amenities")

# ─────────────────────────────────────────────────────────────
# 6. Station sizing (Section 9)
# ─────────────────────────────────────────────────────────────
print("\n--- Sizing stations ---")

def size_station(row):
    """Determine initial n_chargers based on demand gap + corridor class."""
    gap = row.get('seg_gap_kw', 0)
    if pd.isna(gap):
        gap = 0
    traffic = row.get('seg_avg_traffic', 0)
    if pd.isna(traffic):
        traffic = 0
    corridor = row.get('corridor_class', 'standard')
    ctype = row.get('candidate_type', 'coverage')

    # Coverage-only with modest demand
    if 'coverage' in str(ctype) and 'demand' not in str(ctype) and gap <= 0:
        return CHARGER_MIN  # 4

    # Normalize gap and traffic for sizing
    # Use rough percentile-based mapping
    if gap <= 50:
        gap_tier = 0
    elif gap <= 200:
        gap_tier = 1
    elif gap <= 500:
        gap_tier = 2
    else:
        gap_tier = 3

    if traffic <= 5000:
        traffic_tier = 0
    elif traffic <= 15000:
        traffic_tier = 1
    else:
        traffic_tier = 2

    # Combined tier → charger count
    combined = gap_tier + traffic_tier
    if combined <= 1:
        n = CHARGER_MIN       # 4
    elif combined <= 2:
        n = 6
    elif combined <= 3:
        n = 8
    elif combined <= 4:
        n = 10
    else:
        n = CHARGER_HIGH      # 12

    # Corridor boost
    if corridor == 'primary' and n < CHARGER_HIGH:
        n = min(n + 2, CHARGER_HIGH)

    # Strategic junction / coverage+demand dual candidates
    if 'coverage+demand' in str(ctype) and n < 10:
        n = max(n, 8)

    return int(np.clip(n, CHARGER_MIN, CHARGER_MAX))

unified['n_chargers_initial'] = unified.apply(size_station, axis=1)
unified['proposed_demand_kw'] = unified['n_chargers_initial'] * CHARGER_KW

print(f"Charger distribution:")
print(unified['n_chargers_initial'].value_counts().sort_index().to_string())
print(f"Total chargers: {unified['n_chargers_initial'].sum()}")
print(f"Total proposed capacity: {unified['proposed_demand_kw'].sum():,.0f} kW")

# ─────────────────────────────────────────────────────────────
# 7. Save
# ─────────────────────────────────────────────────────────────
out_path = os.path.join(DATA_DIR, "unified_candidates.gpkg")
unified.to_file(out_path, driver="GPKG")
print(f"\nSaved {len(unified)} unified candidates → {out_path}")

print(f"\n{'='*60}")
print("MERGE & SIZING SUMMARY")
print(f"{'='*60}")
print(f"Coverage candidates:      {len(cov_gdf)}")
print(f"Demand candidates:        {len(dem_gdf)}")
print(f"After merge + dedup:      {len(unified)}")
print(f"  - coverage only:        {(unified['candidate_type'] == 'coverage').sum()}")
print(f"  - demand only:          {(unified['candidate_type'] == 'demand').sum()}")
print(f"  - coverage+demand:      {(unified['candidate_type'] == 'coverage+demand').sum()}")
print(f"Snapped to amenities:     {snapped_count}")
print(f"Avg chargers per station: {unified['n_chargers_initial'].mean():.1f}")
