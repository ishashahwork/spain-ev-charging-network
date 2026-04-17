"""
Download Spain Interurban Road Network — OSMnx by region
=========================================================
Splits Spain into 4 bounding boxes to avoid Overpass timeout.
Queries motorway + trunk + primary per region and merges.

Output:
  data/processed/interurban_roads.gpkg
  data/processed/interurban_roads.csv
"""

import osmnx as ox
import geopandas as gpd
import pandas as pd
import os
import re
import time

os.makedirs("data/processed", exist_ok=True)

GPKG_OUT = "data/processed/interurban_roads.gpkg"
CSV_OUT  = "data/processed/interurban_roads.csv"

ox.settings.log_console = False
ox.settings.use_cache   = True
ox.settings.cache_folder = "data/raw/osmnx_cache"
ox.settings.max_query_area_size = 25_000_000_000  # 25,000 km² — no auto-splitting

# Spain split into 4 regions (north, lat>40 | south, lat<40) x (west, lon<-2 | east, lon>-2)
# Format: (north, south, east, west)  — as required by osmnx
REGIONS = {
    "NW": (43.85, 40.0, -2.0, -9.5),
    "NE": (43.85, 40.0,  4.5, -2.0),
    "SW": (40.0,  27.5, -2.0, -9.5),
    "SE": (40.0,  27.5,  4.5, -2.0),
}

# Filter: motorway + trunk covers autopistas + autovías
# Add primary for carreteras nacionales
FILTER = '["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link)$"]'

all_edges = []

for region_name, (north, south, east, west) in REGIONS.items():
    cache_file = f"data/raw/osmnx_cache/edges_{region_name}.gpkg"
    if os.path.exists(cache_file):
        print(f"[{region_name}] Loading from cache...")
        gdf = gpd.read_file(cache_file)
        all_edges.append(gdf)
        print(f"  {len(gdf):,} edges")
        continue

    print(f"[{region_name}] Downloading bbox ({north},{south},{east},{west})...")
    for attempt in range(3):
        try:
            # OSMnx >= 2.x uses bbox as a single tuple (west, south, east, north)
            try:
                G = ox.graph_from_bbox(
                    bbox=(west, south, east, north),
                    custom_filter=FILTER,
                    retain_all=False,
                    simplify=True,
                )
            except TypeError:
                # OSMnx < 2.x: positional (north, south, east, west)
                G = ox.graph_from_bbox(
                    north, south, east, west,
                    custom_filter=FILTER,
                    retain_all=False,
                    simplify=True,
                )
            nodes, edges = ox.graph_to_gdfs(G)
            edges = edges.reset_index()
            edges.to_file(cache_file, driver="GPKG")
            all_edges.append(edges)
            print(f"  {len(edges):,} edges downloaded and cached")
            break
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            if attempt < 2:
                print("  Waiting 20s...")
                time.sleep(20)
    else:
        print(f"  [{region_name}] All attempts failed — skipping")

# ─────────────────────────────────────────────────────────────────────────────
# MERGE ALL REGIONS
# ─────────────────────────────────────────────────────────────────────────────
print("\nMerging regions...")
gdf = pd.concat(all_edges, ignore_index=True)
gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")
gdf = gdf.drop_duplicates(subset=["osmid"] if "osmid" in gdf.columns else None)
print(f"Total edges: {len(gdf):,}")

# Flatten list columns
for col in ["name", "ref", "highway", "maxspeed", "lanes"]:
    if col in gdf.columns:
        gdf[col] = gdf[col].apply(lambda x: x[0] if isinstance(x, list) else x)

# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFY
# ─────────────────────────────────────────────────────────────────────────────
def classify_road(hw, ref):
    hw = str(hw).lower() if hw else ""
    ref = str(ref).upper() if ref and str(ref) != "nan" else ""
    if "motorway" in hw:
        return "Autopista" if re.match(r"AP-?\d+", ref) else "Autovía"
    elif "trunk" in hw:
        return "Autovía"
    elif "primary" in hw:
        return "Carretera Nacional"
    return "Otra"

def extract_route(ref):
    if not ref or str(ref) in ("", "nan", "None"):
        return None
    for part in str(ref).split(";"):
        part = part.strip().upper()
        m = re.match(r"(AP|A|N|C|R|M|RM|SE|B|GR|V|CA|MA|CO|H|J|AL|MU|CS|T|L|E)-?\d+", part)
        if m:
            return part.split(",")[0].strip()
    return str(ref).split(";")[0].strip()[:20]

gdf["road_category"] = gdf.apply(
    lambda r: classify_road(r.get("highway"), r.get("ref")), axis=1
)
gdf["route_segment"] = gdf["ref"].apply(extract_route)

# Compute length in km
gdf_proj = gdf.to_crs("EPSG:3857")
gdf["length_km"] = gdf_proj.geometry.length / 1000

print(f"\nRoad category breakdown:")
print(gdf["road_category"].value_counts().to_string())
print(f"\nTop 20 route codes:")
print(gdf["route_segment"].value_counts().head(20).to_string())
print(f"\nTotal length: {gdf['length_km'].sum():,.0f} km")

# ─────────────────────────────────────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────────────────────────────────────
keep = ["geometry", "osmid", "name", "ref", "route_segment",
        "highway", "road_category", "maxspeed", "length_km"]
keep = [c for c in keep if c in gdf.columns]

gdf[keep].to_file(GPKG_OUT, driver="GPKG")
print(f"\nSaved to {GPKG_OUT}")

gdf[[c for c in keep if c != "geometry"]].to_csv(CSV_OUT, index=False, encoding="utf-8")
print(f"Saved CSV to {CSV_OUT}")
