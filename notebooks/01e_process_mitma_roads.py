"""
Process MITMA Road Segments — Official Ministry Road Network
============================================================
Input:
  data/raw/mitma_rutas/geometria/Geometria_tramos.shp   (452,478 segments, EPSG:3042)
  data/raw/mitma_rutas/geometria/rt_tramo_val.csv        (id_tramo → road name lookup)
  data/raw/mitma_rutas/informacion_tramo/*.csv.gz         (traffic volumes per segment)

Processing steps:
  1. Load geometry, reproject EPSG:3042 → WGS84 (EPSG:4326)
  2. Join road codes from rt_tramo_val — pick primary interurban code per segment
  3. Filter to interurban roads only (AP-, A-, N- prefixes)
  4. Average traffic across 4 sample days, compute demand proxy
  5. Compute segment length in km
  6. Save to data/processed/interurban_roads_mitma.gpkg + .csv

Output columns:
  id_tramo, route_segment, road_category, length_km,
  avg_total, avg_largo, avg_inter_provincial, avg_inter_ccaa,
  demand_score, geometry (WGS84)
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import re
from pathlib import Path

BASE_RAW  = Path("C:/Users/LEGION/Desktop/MASTERS/Datathon/data/raw/mitma_rutas")
BASE_OUT  = Path("C:/Users/LEGION/Desktop/MASTERS/Datathon/data/processed")
LOG_FILE  = BASE_OUT / "mitma_roads_process_log.txt"

BASE_OUT.mkdir(parents=True, exist_ok=True)

def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

log("=" * 60)
log("MITMA Road Network Processor")
log("=" * 60)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load geometry and reproject to WGS84
# ─────────────────────────────────────────────────────────────────────────────
log("\n[1/5] Loading geometry shapefile...")
gdf = gpd.read_file(BASE_RAW / "geometria" / "Geometria_tramos.shp")
log(f"  Loaded {len(gdf):,} segments | CRS: {gdf.crs}")

log("  Reprojecting EPSG:3042 → WGS84 (EPSG:4326)...")
gdf = gdf.to_crs("EPSG:4326")
log(f"  Done | Bounds: {gdf.total_bounds.round(4)}")

# Compute segment length in km (reproject to metric CRS for accurate distance)
gdf_metric = gdf.to_crs("EPSG:3857")
gdf["length_km"] = gdf_metric.geometry.length / 1000
log(f"  Total network length: {gdf['length_km'].sum():,.0f} km")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Join road codes from rt_tramo_val.csv
# ─────────────────────────────────────────────────────────────────────────────
log("\n[2/5] Loading road name lookup (rt_tramo_val.csv)...")
val = pd.read_csv(
    BASE_RAW / "geometria" / "rt_tramo_val.csv",
    encoding="utf-8-sig",   # handles BOM character
    dtype=str,
)
val.columns = [c.strip().lstrip("\ufeff") for c in val.columns]
val = val.rename(columns={"id_tramo": "id_tramo", "nombre": "road_name"})
val["road_name"] = val["road_name"].str.strip().str.upper()
log(f"  Loaded {len(val):,} rows | {val['id_tramo'].nunique():,} unique segments")

# Road category classifier
def classify_road(name: str):
    if not name or str(name) == "nan":
        return None, None
    name = str(name).strip().upper()
    if re.match(r"^AP-?\d+", name):
        return name, "Autopista"
    if re.match(r"^A-?\d+", name):
        return name, "Autovía"
    if re.match(r"^N-?\d+", name):
        return name, "Carretera Nacional"
    return None, None

# Priority: Autopista > Autovía > Carretera Nacional > other
PRIORITY = {"Autopista": 0, "Autovía": 1, "Carretera Nacional": 2}

def pick_primary(group):
    """From all road names for one segment, pick the highest-priority interurban one."""
    best_name, best_cat, best_pri = None, None, 99
    for name in group["road_name"]:
        n, cat = classify_road(name)
        if cat and PRIORITY.get(cat, 99) < best_pri:
            best_name, best_cat, best_pri = n, cat, PRIORITY[cat]
    return pd.Series({"route_segment": best_name, "road_category": best_cat})

log("  Classifying and selecting primary road code per segment...")
road_codes = (
    val.groupby("id_tramo")
    .apply(pick_primary, include_groups=False)
    .reset_index()
)
interurban_codes = road_codes[road_codes["road_category"].notna()]
log(f"  Interurban segments found: {len(interurban_codes):,}")
log(f"  Category breakdown:\n{interurban_codes['road_category'].value_counts().to_string()}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Filter geometry to interurban segments only
# ─────────────────────────────────────────────────────────────────────────────
log("\n[3/5] Filtering geometry to interurban roads...")
gdf_interurban = gdf.merge(interurban_codes, on="id_tramo", how="inner")
log(f"  Kept {len(gdf_interurban):,} interurban segments")
log(f"  Total interurban length: {gdf_interurban['length_km'].sum():,.0f} km")

top_routes = gdf_interurban["route_segment"].value_counts().head(20)
log(f"\n  Top 20 routes by segment count:\n{top_routes.to_string()}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Average traffic across sample days
# ─────────────────────────────────────────────────────────────────────────────
log("\n[4/5] Loading and averaging traffic data (4 sample days)...")

INFO_DIR = BASE_RAW / "informacion_tramo"
traffic_files = sorted(INFO_DIR.glob("*.csv.gz"))
log(f"  Found {len(traffic_files)} files: {[f.name for f in traffic_files]}")

TRAFFIC_COLS = ["tramo", "total", "largo", "inter_provincial", "inter_ccaa", "extranjero"]

dfs = []
for f in traffic_files:
    df = pd.read_csv(f, compression="gzip", sep=None, engine="python",
                     usecols=TRAFFIC_COLS, dtype={"tramo": str})
    df["tramo"] = df["tramo"].astype(str)
    dfs.append(df)
    log(f"    {f.name}: {len(df):,} rows")

combined = pd.concat(dfs, ignore_index=True)
traffic_avg = (
    combined.groupby("tramo")[["total", "largo", "inter_provincial", "inter_ccaa", "extranjero"]]
    .mean()
    .reset_index()
    .rename(columns={
        "tramo":            "id_tramo",
        "total":            "avg_total",
        "largo":            "avg_largo",
        "inter_provincial": "avg_inter_prov",
        "inter_ccaa":       "avg_inter_ccaa",
        "extranjero":       "avg_extranjero",
    })
)
log(f"  Averaged traffic for {len(traffic_avg):,} unique segments")

# Demand score: weighted sum of long-distance and inter-regional traffic
# largo = long trips (EV range-critical), inter_provincial/ccaa = interurban corridor usage
traffic_avg["demand_score"] = (
    0.5 * traffic_avg["avg_largo"] +
    0.3 * traffic_avg["avg_inter_prov"] +
    0.2 * traffic_avg["avg_inter_ccaa"]
)
log(f"  demand_score stats:\n{traffic_avg['demand_score'].describe().round(1).to_string()}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Final merge and save
# ─────────────────────────────────────────────────────────────────────────────
log("\n[5/5] Merging and saving outputs...")

gdf_final = gdf_interurban.merge(traffic_avg, on="id_tramo", how="left")

# Segments with no traffic data get demand_score = 0
gdf_final["demand_score"] = gdf_final["demand_score"].fillna(0)
gdf_final["avg_total"]    = gdf_final["avg_total"].fillna(0)
gdf_final["avg_largo"]    = gdf_final["avg_largo"].fillna(0)

matched = gdf_final["avg_total"].gt(0).sum()
log(f"  Segments with traffic data: {matched:,} / {len(gdf_final):,}")

# Keep clean column order
cols = ["id_tramo", "route_segment", "road_category", "length_km",
        "avg_total", "avg_largo", "avg_inter_prov", "avg_inter_ccaa",
        "avg_extranjero", "demand_score", "geometry"]
gdf_final = gdf_final[[c for c in cols if c in gdf_final.columns]]

GPKG_OUT = BASE_OUT / "interurban_roads_mitma.gpkg"
CSV_OUT  = BASE_OUT / "interurban_roads_mitma.csv"

gdf_final.to_file(GPKG_OUT, driver="GPKG")
gdf_final.drop(columns="geometry").to_csv(CSV_OUT, index=False, encoding="utf-8")

log(f"\n  Saved GPKG → {GPKG_OUT}")
log(f"  Saved CSV  → {CSV_OUT}")
log(f"\n  Final dataset: {len(gdf_final):,} interurban segments")
log(f"  Columns: {list(gdf_final.columns)}")

log("\n" + "=" * 60)
log("Done. Next: run 03_optimization.py using interurban_roads_mitma.gpkg")
log("=" * 60)
