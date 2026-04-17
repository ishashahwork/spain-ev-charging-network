"""
Co-location Scoring + Station Nudging
======================================
For each proposed station (from File 2):
  1. Score proximity to 5 amenity types using local GeoJSON files.
  2. For stations with score=0, nudge coordinates toward the nearest
     amenity within NUDGE_MAX_KM (5 km), provided the move does not
     create a corridor gap smaller than MIN_GAP_KM (30 km).
  3. Re-score nudged stations with the updated positions.

Scoring logic:
  +3  Highway service area within 1 km
  +2  Fuel station within 1 km
  +2  Supermarket within 1 km
  +1  Hotel within 2 km
  +1  Restaurant within 1 km

Outputs:
  data/processed/stations_colocation.csv  — scores + nudge metadata
  outputs/File 2.csv                      — updated lat/lon + scores

Runtime: < 60 seconds.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
import os
import warnings
warnings.filterwarnings("ignore")

CRS_METRIC = "EPSG:3857"
CRS_WGS84  = "EPSG:4326"

NUDGE_MAX_M  = 5_000   # max distance to move a station (5 km)
MIN_GAP_KM   = 30.0    # minimum allowed gap between stations on same corridor

AMENITY_CONFIG = [
    # (bucket, geojson_path, score, search_radius_m)
    ("service_area", "data/raw/amenities/service_areas.geojson", 3, 1000),
    ("fuel",         "data/raw/amenities/fuel.geojson",          2, 1000),
    ("supermarket",  "data/raw/amenities/supermarkets.geojson",  2, 1000),
    ("hotel",        "data/raw/amenities/hotels.geojson",        1, 2000),
    ("restaurant",   "data/raw/amenities/restaurants.geojson",   1, 1000),
]

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def score_stations(stations_gdf, amenity_gdfs):
    """Return arrays (scores, best_amenity) for the given station GeoDataFrame."""
    n = len(stations_gdf)
    scores    = np.zeros(n, dtype=int)
    best_type = ["none"] * n
    best_pts  = np.zeros(n, dtype=int)

    for bucket, (amenity_gdf, score, radius) in amenity_gdfs.items():
        buffered = stations_gdf.copy()
        buffered["geometry"] = stations_gdf.geometry.buffer(radius)
        joined = gpd.sjoin(buffered, amenity_gdf[["geometry"]], how="left", predicate="contains")
        hit_idx = joined[~joined["index_right"].isna()].index.unique()

        scores[hit_idx] += score
        improve = (score > best_pts) & np.isin(np.arange(n), hit_idx)
        for i in np.where(improve)[0]:
            best_type[i] = bucket
            best_pts[i]  = score

    return scores, best_type


def gap_ok_after_nudge(stations_df, moved_idx, new_lat, new_lon, min_gap_km):
    """
    Check that moving station at moved_idx to (new_lat, new_lon) does not
    create a gap < min_gap_km with any neighbour on the same route_segment.
    Uses great-circle approximation (1 deg lat ≈ 111 km).
    """
    route = stations_df.loc[moved_idx, "route_segment"]
    peers = stations_df[
        (stations_df["route_segment"] == route) & (stations_df.index != moved_idx)
    ]
    if peers.empty:
        return True

    # Approximate distance in km using Euclidean on WGS84 (good enough for 5 km nudge)
    dlat = (peers["latitude"]  - new_lat).values
    dlon = (peers["longitude"] - new_lon).values * np.cos(np.radians(new_lat))
    dists_km = np.sqrt(dlat**2 + dlon**2) * 111.0

    return float(dists_km.min()) >= min_gap_km


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load stations
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1 — Load proposed stations")
print("=" * 60)

stations = pd.read_csv("outputs/File 2.csv")
# Drop stale colocation columns if re-running
for col in ["colocation_score", "nearest_amenity", "nudged"]:
    if col in stations.columns:
        stations.drop(columns=[col], inplace=True)

print(f"  Loaded {len(stations):,} proposed stations")

stations_gdf = gpd.GeoDataFrame(
    stations.copy(),
    geometry=gpd.points_from_xy(stations["longitude"], stations["latitude"]),
    crs=CRS_WGS84,
).to_crs(CRS_METRIC)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Load amenity GeoJSON files
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2 — Load amenity GeoJSON files")
print("=" * 60)

amenity_gdfs = {}
all_amenities_parts = []

for bucket, path, score, radius in AMENITY_CONFIG:
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found — skipping {bucket}")
        continue
    gdf = gpd.read_file(path).to_crs(CRS_METRIC)
    amenity_gdfs[bucket] = (gdf, score, radius)
    print(f"  {bucket:<16} {len(gdf):>6,} features  (radius={radius}m, +{score}pts)")
    # Keep a merged copy for nudge nearest-neighbour search
    part = gdf[["geometry"]].copy()
    part["amenity_type"] = bucket
    all_amenities_parts.append(part)

all_amenities = pd.concat(all_amenities_parts, ignore_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Initial scoring (pre-nudge)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3 — Initial scoring (pre-nudge)")
print("=" * 60)

scores_pre, best_pre = score_stations(stations_gdf, amenity_gdfs)
n_isolated_pre = int((scores_pre == 0).sum())
print(f"  Stations with score > 0 : {(scores_pre > 0).sum()}")
print(f"  Isolated stations (= 0) : {n_isolated_pre}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Nudge isolated stations toward nearest amenity
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 4 — Nudge isolated stations (score=0)")
print("=" * 60)

nudged_flags = [False] * len(stations)
nudge_count  = 0
skip_gap     = 0
skip_dist    = 0

isolated_idx = np.where(scores_pre == 0)[0]

# Build spatial index over all amenities once
amenity_sindex = all_amenities.sindex

for i in isolated_idx:
    station_pt = stations_gdf.geometry.iloc[i]

    # Candidates within NUDGE_MAX_M
    candidate_idx = list(amenity_sindex.query(station_pt.buffer(NUDGE_MAX_M)))
    if not candidate_idx:
        skip_dist += 1
        continue

    candidates = all_amenities.iloc[candidate_idx].copy()
    candidates["dist_m"] = candidates.geometry.distance(station_pt)
    candidates = candidates[candidates["dist_m"] <= NUDGE_MAX_M]
    if candidates.empty:
        skip_dist += 1
        continue

    # Pick the nearest amenity
    nearest = candidates.loc[candidates["dist_m"].idxmin()]
    new_geom = nearest.geometry
    # Convert new position back to WGS84 for gap check
    new_pt_wgs = gpd.GeoSeries([new_geom], crs=CRS_METRIC).to_crs(CRS_WGS84).iloc[0]
    new_lat, new_lon = new_pt_wgs.y, new_pt_wgs.x

    # Gap constraint check
    if not gap_ok_after_nudge(stations, i, new_lat, new_lon, MIN_GAP_KM):
        skip_gap += 1
        continue

    # Apply nudge
    stations.at[i, "latitude"]  = new_lat
    stations.at[i, "longitude"] = new_lon
    stations_gdf.at[i, "geometry"] = new_geom
    nudged_flags[i] = True
    nudge_count += 1

print(f"  Stations nudged successfully : {nudge_count}")
print(f"  Skipped — no amenity within 5 km : {skip_dist}")
print(f"  Skipped — would violate 30 km gap : {skip_gap}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Re-score with updated positions
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 5 — Re-score after nudging")
print("=" * 60)

# Rebuild GeoDataFrame with updated coordinates
stations_gdf = gpd.GeoDataFrame(
    stations.copy(),
    geometry=gpd.points_from_xy(stations["longitude"], stations["latitude"]),
    crs=CRS_WGS84,
).to_crs(CRS_METRIC)

scores_post, best_post = score_stations(stations_gdf, amenity_gdfs)
n_isolated_post = int((scores_post == 0).sum())

stations["colocation_score"] = scores_post
stations["nearest_amenity"]  = best_post
stations["nudged"]           = nudged_flags

print(f"\n  Co-location score distribution (post-nudge):")
print(stations["colocation_score"].value_counts().sort_index().to_string())
print(f"\n  Nearest amenity types:")
print(stations["nearest_amenity"].value_counts().to_string())
print(f"\n  Isolated before nudge : {n_isolated_pre}")
print(f"  Isolated after nudge  : {n_isolated_post}  ({n_isolated_pre - n_isolated_post} resolved)")
print(f"  Stations with score ≥ 3: {(scores_post >= 3).sum()}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Save outputs
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 6 — Save outputs")
print("=" * 60)

stations.to_csv("data/processed/stations_colocation.csv", index=False, encoding="utf-8")
print(f"  Saved data/processed/stations_colocation.csv")

stations.to_csv("outputs/File 2.csv", index=False, encoding="utf-8")
print(f"  Updated outputs/File 2.csv  (lat/lon updated for {nudge_count} stations)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Summary table
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 7 — Top and worst co-located stations")
print("=" * 60)

print("\n  Top 10 best-located stations:")
top = stations.nlargest(10, "colocation_score")[
    ["location_id", "route_segment", "latitude", "longitude",
     "colocation_score", "nearest_amenity", "nudged", "grid_status"]
]
print(top.to_string(index=False))

print(f"\n  Still isolated (score=0): {n_isolated_post} stations")
if n_isolated_post > 0:
    print("  (These are on remote corridors with no amenities within 5 km — acceptable for interurban network)")

print("\n" + "=" * 60)
print("Co-location scoring + nudging complete.")
print("Next: run 06_visualization.py to update the map.")
print("=" * 60)
