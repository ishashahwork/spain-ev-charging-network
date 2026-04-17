"""
STEP 1 — Road Segmentation
===========================
Aggregate MITMA micro-segments (~0.28 km avg) into ~20 km analytical segments.
Strategy: for each route, sort micro-segments spatially along the corridor,
then batch consecutive segments into groups that sum to ~20 km.

Input:  data/processed/interurban_roads_mitma.gpkg
Output: v2/intermediate/road_segments.gpkg
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import linemerge, unary_union
import warnings, os, sys
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from config import *

os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 1. Load MITMA roads
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1 — Road Segmentation (~20 km analytical units)")
print("=" * 60)

roads = gpd.read_file(ROADS_GPKG)
print(f"Loaded {len(roads):,} micro-segments across {roads['route_segment'].nunique()} routes")
print(f"Total network: {roads['length_km'].sum():,.0f} km")

# Project to metric CRS for distance calculations
roads_m = roads.to_crs(CRS_METRIC)

# ─────────────────────────────────────────────────────────────
# 2. Sort micro-segments along each corridor
# ─────────────────────────────────────────────────────────────
print("\nSorting micro-segments along corridors...")

# Compute centroid for sorting
roads_m['cx'] = roads_m.geometry.centroid.x
roads_m['cy'] = roads_m.geometry.centroid.y

TARGET_M = SEGMENT_LENGTH_KM * 1000  # 20,000 m

all_segments = []
seg_id_counter = 0

route_groups = roads_m.groupby('route_segment')
n_routes = len(route_groups)

for idx, (route_name, group) in enumerate(route_groups):
    if idx % 100 == 0:
        print(f"  Processing route {idx + 1}/{n_routes}: {route_name}")

    group = group.copy()
    total_km = group['length_km'].sum()

    if total_km < 0.5:  # skip very short routes
        continue

    # Sort spatially: project centroid onto principal axis of the route
    cx = group['cx'].values
    cy = group['cy'].values
    # Principal component direction
    dx = cx - cx.mean()
    dy = cy - cy.mean()
    # Use the direction of maximum spread
    if np.std(dx) >= np.std(dy):
        sort_vals = cx
    else:
        sort_vals = cy
    group['sort_key'] = sort_vals
    group = group.sort_values('sort_key').reset_index(drop=True)

    # Determine corridor class
    base_route = route_name
    road_cat = group['road_category'].mode().iloc[0] if len(group) > 0 else "Carretera Nacional"
    if base_route in PRIMARY_CORRIDORS:
        corridor_class = "primary"
    elif road_cat in ("Autopista", "Autovía"):
        corridor_class = "standard"
    else:
        corridor_class = "secondary"

    # Batch consecutive micro-segments into ~20 km groups
    batch_geoms = []
    batch_lengths = []
    batch_traffic = []
    batch_demand = []
    cumulative_km = 0.0
    batch_start_km = 0.0

    for _, micro in group.iterrows():
        batch_geoms.append(micro.geometry)
        batch_lengths.append(micro['length_km'])
        batch_traffic.append(micro['avg_total'] if pd.notna(micro['avg_total']) else 0)
        batch_demand.append(micro['demand_score'] if pd.notna(micro['demand_score']) else 0)
        cumulative_km += micro['length_km']

        # Flush batch when we reach target length
        if cumulative_km - batch_start_km >= SEGMENT_LENGTH_KM:
            seg_len = cumulative_km - batch_start_km
            # Only create segment if it's above minimum
            if seg_len >= SEGMENT_MIN_KM or batch_start_km + seg_len >= total_km:
                seg_id_counter += 1
                # Merge geometries
                merged_geom = unary_union(batch_geoms)
                if isinstance(merged_geom, (LineString, MultiLineString)):
                    pass  # keep as is
                elif hasattr(merged_geom, 'geoms'):
                    lines = [g for g in merged_geom.geoms if isinstance(g, LineString)]
                    if lines:
                        merged_geom = MultiLineString(lines) if len(lines) > 1 else lines[0]
                    else:
                        batch_geoms = []
                        batch_lengths = []
                        batch_traffic = []
                        batch_demand = []
                        batch_start_km = cumulative_km
                        continue

                # Length-weighted traffic average
                w = np.array(batch_lengths)
                w_sum = w.sum()
                avg_traffic = np.average(batch_traffic, weights=w) if w_sum > 0 else 0
                avg_demand = np.average(batch_demand, weights=w) if w_sum > 0 else 0

                # Centroid
                try:
                    centroid = merged_geom.centroid
                except:
                    centroid = Point(np.mean([g.centroid.x for g in batch_geoms]),
                                     np.mean([g.centroid.y for g in batch_geoms]))

                all_segments.append({
                    'segment_id': f"SEG_{seg_id_counter:05d}",
                    'route_segment': route_name,
                    'road_category': road_cat,
                    'corridor_class': corridor_class,
                    'start_km': round(batch_start_km, 2),
                    'end_km': round(cumulative_km, 2),
                    'segment_length_km': round(seg_len, 2),
                    'avg_traffic': round(avg_traffic, 1),
                    'demand_score': round(avg_demand, 2),
                    'geometry': merged_geom,
                })

                batch_geoms = []
                batch_lengths = []
                batch_traffic = []
                batch_demand = []
                batch_start_km = cumulative_km

    # Handle remaining micro-segments in last batch
    if batch_geoms:
        seg_len = cumulative_km - batch_start_km
        if seg_len > 0.5:  # at least 0.5 km
            # If very short, try to merge with previous segment
            if seg_len < SEGMENT_MIN_KM and len(all_segments) > 0 and all_segments[-1]['route_segment'] == route_name:
                # Merge into previous segment
                prev = all_segments[-1]
                prev_geom = prev['geometry']
                new_geom = unary_union([prev_geom] + batch_geoms)
                if isinstance(new_geom, (LineString, MultiLineString)):
                    prev['geometry'] = new_geom
                elif hasattr(new_geom, 'geoms'):
                    lines = [g for g in new_geom.geoms if isinstance(g, LineString)]
                    if lines:
                        prev['geometry'] = MultiLineString(lines) if len(lines) > 1 else lines[0]
                prev['end_km'] = round(cumulative_km, 2)
                prev['segment_length_km'] = round(prev['end_km'] - prev['start_km'], 2)
            else:
                seg_id_counter += 1
                merged_geom = unary_union(batch_geoms)
                if not isinstance(merged_geom, (LineString, MultiLineString)):
                    if hasattr(merged_geom, 'geoms'):
                        lines = [g for g in merged_geom.geoms if isinstance(g, LineString)]
                        if lines:
                            merged_geom = MultiLineString(lines) if len(lines) > 1 else lines[0]
                        else:
                            continue
                    else:
                        continue

                w = np.array(batch_lengths)
                w_sum = w.sum()
                avg_traffic = np.average(batch_traffic, weights=w) if w_sum > 0 else 0
                avg_demand = np.average(batch_demand, weights=w) if w_sum > 0 else 0

                all_segments.append({
                    'segment_id': f"SEG_{seg_id_counter:05d}",
                    'route_segment': route_name,
                    'road_category': road_cat,
                    'corridor_class': corridor_class,
                    'start_km': round(batch_start_km, 2),
                    'end_km': round(cumulative_km, 2),
                    'segment_length_km': round(seg_len, 2),
                    'avg_traffic': round(avg_traffic, 1),
                    'demand_score': round(avg_demand, 2),
                    'geometry': merged_geom,
                })

# ─────────────────────────────────────────────────────────────
# 3. Build GeoDataFrame
# ─────────────────────────────────────────────────────────────
print(f"\nBuilt {len(all_segments):,} analytical segments")

segments_gdf = gpd.GeoDataFrame(all_segments, crs=CRS_METRIC)

# Compute centroid lat/lon in WGS84
centroid_gs = gpd.GeoSeries(segments_gdf.geometry.centroid.values, crs=CRS_METRIC)
centroid_wgs = centroid_gs.to_crs(CRS_WGS84)
segments_gdf['centroid_lat'] = centroid_wgs.y.values
segments_gdf['centroid_lon'] = centroid_wgs.x.values

# ─────────────────────────────────────────────────────────────
# 4. Summary stats
# ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("SEGMENTATION SUMMARY")
print(f"{'='*60}")
print(f"Total segments:    {len(segments_gdf):,}")
print(f"Total length:      {segments_gdf['segment_length_km'].sum():,.0f} km")
print(f"Avg segment:       {segments_gdf['segment_length_km'].mean():.1f} km")
print(f"Min segment:       {segments_gdf['segment_length_km'].min():.1f} km")
print(f"Max segment:       {segments_gdf['segment_length_km'].max():.1f} km")
print(f"Median segment:    {segments_gdf['segment_length_km'].median():.1f} km")
print(f"\nBy corridor class:")
print(segments_gdf.groupby('corridor_class')['segment_length_km'].agg(['count', 'sum']).round(0).to_string())
print(f"\nBy road category:")
print(segments_gdf.groupby('road_category')['segment_length_km'].agg(['count', 'sum']).round(0).to_string())

# ─────────────────────────────────────────────────────────────
# 5. Save
# ─────────────────────────────────────────────────────────────
out_path = os.path.join(DATA_DIR, "road_segments.gpkg")
segments_gdf.to_file(out_path, driver="GPKG")
print(f"\nSaved → {out_path}")

# Also save a WGS84 version
segments_wgs = segments_gdf.to_crs(CRS_WGS84)
segments_wgs.to_file(os.path.join(DATA_DIR, "road_segments_wgs84.gpkg"), driver="GPKG")
print(f"Saved → {DATA_DIR}/road_segments_wgs84.gpkg")
