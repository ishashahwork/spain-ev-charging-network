"""
Charging Network Optimization — Greedy Corridor Coverage
=========================================================
Algorithm: place the minimum number of stations on each interurban corridor
such that no gap between consecutive stations exceeds MAX_GAP_KM (150 km).

Charger count per station is demand-weighted using two data sources:
  1. MITMA real traffic data (demand_score per segment):
       demand_score = 0.5*avg_largo + 0.3*avg_inter_prov + 0.2*avg_inter_ccaa
  2. Province EV density (from DGT registrations 2023-2024):
       ev_penetration_factor = province_ev_share / national_median_share
  Combined: final_score = demand_score × ev_penetration_factor
  Road-category multiplier: Autopista=1.5×, Autovía=1.2×, Carretera Nacional=1.0×
  Mapped to [CHARGER_MIN, CHARGER_MAX] using percentile-based scaling

Assumptions (documented):
  - EV average range: 350 km (conservative 2027 midpoint, EU fleet average)
  - Max inter-station gap: 150 km  (350 km × 43% safety buffer)
  - Min inter-station gap: 30 km   (avoid over-clustering near cities)
  - Standard charger power: 150 kW (fixed by competition rules)
  - Chargers per station: 2–12
  - Province EV penetration factor clamped to [0.5, 2.0] to avoid extreme outliers

Inputs:
  data/processed/interurban_roads_mitma.gpkg    ← from 01e_process_mitma_roads.py
  data/processed/ev_projection_results.json     ← from 02_ev_projection.py
  data/processed/ev_share_by_province.csv       ← from 01f_dgt_ev_by_province.py

Outputs:
  outputs/File 2.csv                            ← proposed charging locations
  data/processed/proposed_stations.gpkg         ← spatial version for grid join

Colab note:
  Mount Drive or upload data/ folder before running.
  All paths are relative to the Datathon/ working directory.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import json
import os
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import linemerge, unary_union
import warnings
warnings.filterwarnings("ignore")

os.makedirs("outputs", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETERS (all documented assumptions)
# ─────────────────────────────────────────────────────────────────────────────
MAX_GAP_KM  = 150   # max allowed distance between consecutive stations
MIN_GAP_KM  = 30    # minimum distance between stations (avoid clustering)
EV_RANGE_KM = 350   # assumed average EV range in 2027
CHARGER_MIN = 2     # minimum chargers per station
CHARGER_MAX = 12    # maximum chargers per station
CHARGER_KW  = 150   # fixed by competition rules (non-negotiable)
CRS_METRIC  = "EPSG:3857"
CRS_WGS84   = "EPSG:4326"

# Road-category traffic multiplier for charger demand
CATEGORY_MULTIPLIER = {
    "Autopista":           1.5,   # toll motorways — highest speed/volume
    "Autovía":             1.2,   # free motorways — high volume
    "Carretera Nacional":  1.0,   # national roads — baseline
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load road network
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1 — Load MITMA interurban road network")
print("=" * 60)

ROADS_FILE = "data/processed/interurban_roads_mitma.gpkg"
if not os.path.exists(ROADS_FILE):
    raise FileNotFoundError(
        f"{ROADS_FILE} not found. Run 01e_process_mitma_roads.py first."
    )

roads = gpd.read_file(ROADS_FILE)
print(f"  Loaded {len(roads):,} road segments")
print(f"  CRS: {roads.crs}")
print(f"  Columns: {list(roads.columns)}")
print(f"\n  Road category breakdown:")
print(roads["road_category"].value_counts().to_string())
print(f"\n  Demand score stats:")
print(roads["demand_score"].describe().round(1).to_string())

roads_m = roads.to_crs(CRS_METRIC)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Load EV fleet projection + province EV density
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2 — Load EV projection & province EV density")
print("=" * 60)

with open("data/processed/ev_projection_results.json") as f:
    ev_proj = json.load(f)

total_ev_2027 = ev_proj["total_ev_projected_2027"]
print(f"  Total EV fleet 2027: {total_ev_2027:,}")
print(f"  Source: datos.gob.es GitHub fork SARIMA model (mandatory)")

# Province EV density: normalised penetration factor
# ev_penetration_factor = province_share / median_share
# Clamped to [0.5, 2.0] to avoid extreme outliers skewing charger counts
ev_prov = pd.read_csv("data/processed/ev_share_by_province.csv", dtype={"CPRO": str})
ev_prov["CPRO"] = ev_prov["CPRO"].str.zfill(2)
median_share = ev_prov["ev_share"].median()
ev_prov["ev_penetration_factor"] = np.clip(
    ev_prov["ev_share"] / median_share, 0.5, 2.0
)
province_factor = dict(zip(ev_prov["CPRO"], ev_prov["ev_penetration_factor"]))
print(f"\n  Province EV penetration factors loaded ({len(ev_prov)} provinces)")
print(f"  Median share: {median_share:.4f} | Factor range: "
      f"{ev_prov['ev_penetration_factor'].min():.2f}–{ev_prov['ev_penetration_factor'].max():.2f}")
print(f"\n  Top 5 provinces by EV penetration:")
print(ev_prov[["CPRO","province_name","ev_share","ev_penetration_factor"]]
      .head(5).to_string(index=False))

# Province bbox lookup (lat/lon bounding boxes → CPRO)
# Used to assign province to each proposed station coordinate
PROVINCE_BBOX = {
    "28": (39.9, 41.2, -4.6, -3.0),   "08": (41.0, 42.5, 0.8, 2.3),
    "46": (38.5, 39.9, -1.5, 0.5),    "03": (37.8, 38.9, -1.2, 0.5),
    "07": (38.6, 40.1, 1.2, 4.3),     "41": (36.8, 38.2, -7.5, -5.0),
    "30": (37.3, 38.7, -2.3, -0.7),   "29": (36.3, 37.3, -5.5, -3.8),
    "43": (40.5, 41.5, 0.2, 1.5),     "48": (43.0, 43.5, -3.5, -2.1),
    "17": (41.6, 42.9, 1.7, 3.3),     "33": (42.8, 43.7, -7.2, -4.5),
    "11": (35.9, 37.2, -6.4, -5.0),   "18": (36.9, 38.2, -4.2, -2.5),
    "31": (42.0, 43.5, -2.5, -0.7),   "50": (41.0, 42.2, -2.2, -0.3),
    "20": (42.9, 43.5, -2.7, -1.6),   "15": (42.7, 43.8, -9.3, -7.7),
    "36": (41.8, 42.5, -9.0, -7.7),   "47": (41.0, 42.2, -5.5, -4.0),
    "26": (41.9, 42.6, -3.2, -1.7),   "39": (43.0, 43.5, -4.5, -3.3),
    "24": (41.8, 43.0, -7.2, -5.0),   "09": (41.6, 43.0, -4.5, -2.7),
    "49": (41.0, 42.2, -6.8, -5.5),   "37": (40.1, 41.4, -7.0, -5.3),
    "10": (39.0, 40.7, -7.6, -5.5),   "06": (38.0, 39.5, -7.6, -5.3),
    "23": (37.4, 38.7, -4.4, -2.2),   "04": (36.7, 37.7, -3.2, -1.5),
    "21": (37.1, 38.2, -7.6, -6.5),   "02": (38.1, 39.6, -3.0, -0.9),
    "13": (38.2, 39.6, -5.2, -2.7),   "16": (39.4, 41.2, -3.3, -1.5),
    "19": (40.2, 41.5, -3.3, -1.5),   "45": (39.3, 40.4, -5.8, -2.9),
    "05": (40.0, 41.3, -5.8, -4.3),   "34": (41.7, 42.9, -5.2, -3.8),
    "40": (40.6, 41.7, -4.8, -3.5),   "42": (41.2, 42.2, -3.5, -1.8),
    "44": (39.7, 41.2, -1.8,  0.0),   "22": (41.8, 43.0, -1.1, 0.8),
    "01": (42.5, 43.2, -3.2, -2.2),   "32": (41.7, 42.7, -8.1, -6.7),
    "27": (42.5, 43.8, -7.8, -6.6),   "25": (41.3, 42.9, 0.2, 1.8),
    "14": (37.3, 38.5, -5.5, -4.0),   "12": (39.7, 40.8, -0.6, 0.5),
    "35": (27.7, 29.2, -15.8, -13.4), "38": (27.6, 29.5, -18.2, -13.3),
}

def get_province_factor(lat: float, lon: float) -> float:
    """Return EV penetration factor for the province containing (lat, lon)."""
    for cpro, (la_min, la_max, lo_min, lo_max) in PROVINCE_BBOX.items():
        if la_min <= lat <= la_max and lo_min <= lon <= lo_max:
            return province_factor.get(cpro, 1.0)
    return 1.0  # national median fallback

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Build demand-weighted charger count function
# Combined: MITMA traffic demand × province EV penetration factor
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3 — Calibrate demand → charger count mapping")
print("=" * 60)

demand_series = roads_m[roads_m["demand_score"] > 0]["demand_score"]
p10 = demand_series.quantile(0.10)
p90 = demand_series.quantile(0.90)
print(f"  Traffic demand_score p10: {p10:.1f}  p90: {p90:.1f}")
print(f"  Province EV factor applied after traffic normalisation")
print(f"  Mapping: combined_score(p10) → {CHARGER_MIN} | combined_score(p90) → {CHARGER_MAX}")

def compute_n_chargers(demand_score: float, road_category: str,
                       lat: float, lon: float) -> int:
    """
    Map segment demand + province EV density to charger count.

    1. Normalise MITMA demand_score to [0,1] using p10-p90 range
    2. Scale by province EV penetration factor (clamped to [0.5, 2.0])
    3. Apply road-category multiplier
    4. Map to [CHARGER_MIN, CHARGER_MAX]

    Rationale: high-traffic corridors through high-EV provinces need more
    chargers than the same road in a low-adoption region.
    """
    if demand_score <= 0:
        return CHARGER_MIN

    # Normalise traffic demand
    norm = float(np.clip((demand_score - p10) / (p90 - p10), 0.0, 1.0))

    # Province EV penetration factor
    prov_factor = get_province_factor(lat, lon)

    # Road-category multiplier
    road_mult = CATEGORY_MULTIPLIER.get(str(road_category), 1.0)

    # Combined score
    base = CHARGER_MIN + norm * (CHARGER_MAX - CHARGER_MIN)
    result = base * prov_factor * road_mult

    return int(np.clip(round(result), CHARGER_MIN, CHARGER_MAX))

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Greedy coverage algorithm per corridor
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 4 — Greedy corridor coverage")
print("=" * 60)

def place_stations_on_line(line_m, route_segment, road_category, demand_score):
    """
    Place stations along a LineString (metric CRS) every MAX_GAP_KM.
    Returns list of station dicts.
    """
    total_km = line_m.length / 1000

    if total_km < MIN_GAP_KM:
        # Short segment — one station at midpoint
        pt = line_m.interpolate(0.5, normalized=True)
        return [{
            "x_m": pt.x, "y_m": pt.y,
            "km_position": round(total_km / 2, 1),
            "route_segment": route_segment,
            "road_category": road_category,
            "demand_score": demand_score,
            "corridor_length_km": round(total_km, 1),
        }]

    stations = []
    current_km = 0.0

    while current_km <= total_km:
        frac = min(current_km / total_km, 1.0)
        pt = line_m.interpolate(frac, normalized=True)
        stations.append({
            "x_m": pt.x, "y_m": pt.y,
            "km_position": round(current_km, 1),
            "route_segment": route_segment,
            "road_category": road_category,
            "demand_score": demand_score,
            "corridor_length_km": round(total_km, 1),
        })
        current_km += MAX_GAP_KM

    # Add end-of-corridor station if remaining gap > MIN_GAP_KM
    last_km = stations[-1]["km_position"]
    if (total_km - last_km) > MIN_GAP_KM:
        pt = line_m.interpolate(1.0, normalized=True)
        stations.append({
            "x_m": pt.x, "y_m": pt.y,
            "km_position": round(total_km, 1),
            "route_segment": route_segment,
            "road_category": road_category,
            "demand_score": demand_score,
            "corridor_length_km": round(total_km, 1),
        })

    return stations


# Group by route_segment, merge geometries, run algorithm
all_stations = []
roads_with_route = roads_m[roads_m["route_segment"].notna()].copy()
unique_routes = roads_with_route["route_segment"].nunique()
print(f"  Processing {unique_routes:,} unique route segments...")

for route_seg, group in roads_with_route.groupby("route_segment"):
    # Merge all segment geometries for this route into one line
    geoms = group.geometry.tolist()
    union = unary_union(geoms)
    # linemerge only accepts MultiLineString or GeometryCollection, not bare LineString
    merged = linemerge(union) if union.geom_type != "LineString" else union

    # Representative demand score for route = 75th percentile of segments
    # (weighted toward high-traffic segments)
    route_demand = float(group["demand_score"].quantile(0.75)) if "demand_score" in group.columns else 0
    road_cat = group["road_category"].mode()[0] if "road_category" in group.columns else "Carretera Nacional"

    lines_to_process = (
        [merged] if merged.geom_type == "LineString"
        else list(merged.geoms) if merged.geom_type == "MultiLineString"
        else []
    )

    for line in lines_to_process:
        if line.length < 1000:   # skip fragments < 1 km
            continue
        stations = place_stations_on_line(line, route_seg, road_cat, route_demand)
        all_stations.extend(stations)

print(f"  Raw station placements: {len(all_stations):,}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Convert to GeoDataFrame, reproject, assign charger counts
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 5 — Assign coordinates and charger counts")
print("=" * 60)

stations_df = pd.DataFrame(all_stations)
stations_gdf = gpd.GeoDataFrame(
    stations_df,
    geometry=gpd.points_from_xy(stations_df["x_m"], stations_df["y_m"]),
    crs=CRS_METRIC,
).to_crs(CRS_WGS84)

stations_gdf["latitude"]  = stations_gdf.geometry.y.round(6)
stations_gdf["longitude"] = stations_gdf.geometry.x.round(6)

stations_gdf["n_chargers_proposed"] = stations_gdf.apply(
    lambda r: compute_n_chargers(
        r["demand_score"], r["road_category"], r["latitude"], r["longitude"]
    ), axis=1
)

# grid_status placeholder — filled by 04_grid_analysis.py
stations_gdf["grid_status"] = "Sufficient"

print(f"  Stations before dedup: {len(stations_gdf):,}")
print(f"\n  Charger count distribution:")
print(stations_gdf["n_chargers_proposed"].value_counts().sort_index().to_string())

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Deduplicate stations within MIN_GAP_KM using spatial index
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 6 — Deduplicate stations closer than MIN_GAP_KM")
print("=" * 60)

stations_m = stations_gdf.to_crs(CRS_METRIC).copy()
MIN_GAP_M = MIN_GAP_KM * 1000
keep = np.ones(len(stations_m), dtype=bool)

# Use sindex for fast spatial lookup instead of O(n²) loop
sindex = stations_m.sindex

for i in range(len(stations_m)):
    if not keep[i]:
        continue
    pt = stations_m.geometry.iloc[i]
    # Find candidates within MIN_GAP_M radius
    candidates = list(sindex.query(pt.buffer(MIN_GAP_M), predicate="intersects"))
    for j in candidates:
        if j <= i or not keep[j]:
            continue
        if pt.distance(stations_m.geometry.iloc[j]) < MIN_GAP_M:
            # Keep the one with higher demand_score
            if stations_m["demand_score"].iloc[j] > stations_m["demand_score"].iloc[i]:
                keep[i] = False
                break
            else:
                keep[j] = False

stations_gdf = stations_gdf[keep].reset_index(drop=True)
print(f"  Stations after dedup: {len(stations_gdf):,}")

# Renumber IDs after dedup
stations_gdf["location_id"] = [f"IBE_{i+1:03d}" for i in range(len(stations_gdf))]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Save outputs
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 7 — Save outputs")
print("=" * 60)

# File 2 — exact required schema
file2 = stations_gdf[[
    "location_id", "latitude", "longitude",
    "route_segment", "n_chargers_proposed", "grid_status"
]].copy()

file2.to_csv("outputs/File 2.csv", index=False, encoding="utf-8")
print(f"  Saved outputs/File 2.csv  ({len(file2):,} rows)")
print(f"  Columns: {list(file2.columns)}")
print(f"\n  Preview:\n{file2.head(5).to_string(index=False)}")

# Spatial file for grid join in step 04
stations_gdf.to_file("data/processed/proposed_stations.gpkg", driver="GPKG")
print(f"\n  Saved data/processed/proposed_stations.gpkg")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("OPTIMIZATION SUMMARY")
print("=" * 60)
print(f"  Total proposed stations:       {len(stations_gdf):,}")
print(f"  Unique corridors covered:      {stations_gdf['route_segment'].nunique():,}")
print(f"  Total chargers proposed:       {stations_gdf['n_chargers_proposed'].sum():,}")
print(f"  Total installed capacity:      {stations_gdf['n_chargers_proposed'].sum() * CHARGER_KW:,} kW")
print(f"  Max inter-station gap:         {MAX_GAP_KM} km")
print(f"  Assumed EV range 2027:         {EV_RANGE_KM} km")
print(f"  EV fleet 2027 (datos.gob.es):  {total_ev_2027:,}")
print(f"\n  Road category breakdown:")
print(stations_gdf["road_category"].value_counts().to_string())
print(f"\n  Top 10 routes by station count:")
print(stations_gdf["route_segment"].value_counts().head(10).to_string())
