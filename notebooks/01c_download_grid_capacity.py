"""
Download Grid Capacity Data — i-DE (Iberdrola) and Endesa
==========================================================
Sources:
  - i-DE (Iberdrola): https://www.i-de.es/conexion-red-electrica/suministro-electrico/mapa-capacidad-consumo
  - Endesa e-distribución: https://www.edistribucion.com/es/red-electrica/Nodos_capacidad_acceso.html
Output:
  data/raw/grid_ide_capacity.csv
  data/raw/grid_endesa_capacity.csv
  data/processed/grid_substations.gpkg  — merged, geocoded, classified
"""

import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import os
import io

os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DatathonProject/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. i-DE (Iberdrola) — Consumption capacity map
# ─────────────────────────────────────────────────────────────────────────────
print("=== i-DE (Iberdrola) Consumption Capacity ===")

IDE_CSV_URL = "https://www.i-de.es/documents/d/guest/2026_04_01_r1-001_demanda-2-"
IDE_OUT = "data/raw/grid_ide_capacity.csv"

try:
    print(f"Downloading from: {IDE_CSV_URL}")
    resp = requests.get(IDE_CSV_URL, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    with open(IDE_OUT, "wb") as f:
        f.write(resp.content)
    print(f"  Saved {len(resp.content)/1024:.0f} KB to {IDE_OUT}")

    # Try to parse
    try:
        df_ide = pd.read_csv(IDE_OUT, sep=';', encoding='latin-1')
    except:
        df_ide = pd.read_csv(IDE_OUT, sep=',', encoding='latin-1')

    print(f"  Rows: {len(df_ide)}, Columns: {df_ide.columns.tolist()}")
    print(f"  Sample:\n{df_ide.head(3).to_string()}")

except Exception as e:
    print(f"  ERROR: {e}")
    df_ide = pd.DataFrame()

# ─────────────────────────────────────────────────────────────────────────────
# 2. Endesa e-distribución — Network capacity nodes (demand side)
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Endesa e-distribución Capacity Nodes ===")

# Endesa demand capacity (consumo) - different from generation
ENDESA_DEMAND_URL = "https://www.edistribucion.es/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/202604/2026_04_01_R1299_demanda.csv"
ENDESA_GEN_URL    = "https://www.edistribucion.es/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/generacion/202604/2026_04_01_R1299_generaci%C3%B3n.csv"
ENDESA_OUT = "data/raw/grid_endesa_capacity.csv"

df_endesa = pd.DataFrame()
for url, label in [(ENDESA_DEMAND_URL, "demand"), (ENDESA_GEN_URL, "generation")]:
    try:
        print(f"  Trying {label}: {url[:80]}...")
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        with open(ENDESA_OUT, "wb") as f:
            f.write(resp.content)
        print(f"  Saved {len(resp.content)/1024:.0f} KB to {ENDESA_OUT}")

        try:
            df_endesa = pd.read_csv(ENDESA_OUT, sep=';', encoding='latin-1')
        except:
            df_endesa = pd.read_csv(ENDESA_OUT, sep=',', encoding='latin-1')

        print(f"  Rows: {len(df_endesa)}, Columns: {df_endesa.columns.tolist()}")
        print(f"  Sample:\n{df_endesa.head(3).to_string()}")
        break

    except Exception as e:
        print(f"  ERROR ({label}): {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. MERGE & GEOCODE — build unified substation GeoDataFrame
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Building unified substation dataset ===")

all_substations = []

# Process i-DE data
if not df_ide.empty:
    print(f"\ni-DE columns: {df_ide.columns.tolist()}")
    # Detect lat/lon columns
    lat_col = next((c for c in df_ide.columns if 'lat' in c.lower() or 'y_' in c.lower()), None)
    lon_col = next((c for c in df_ide.columns if 'lon' in c.lower() or 'lng' in c.lower() or 'x_' in c.lower()), None)
    cap_col = next((c for c in df_ide.columns if 'capac' in c.lower() or 'mw' in c.lower() or 'potenci' in c.lower()), None)

    print(f"  Detected: lat={lat_col}, lon={lon_col}, capacity={cap_col}")

    if lat_col and lon_col:
        df_ide_sub = df_ide[[lat_col, lon_col] + ([cap_col] if cap_col else [])].copy()
        df_ide_sub.columns = ['latitude', 'longitude'] + (['capacity_mw'] if cap_col else [])
        df_ide_sub['distributor'] = 'i-DE'
        df_ide_sub = df_ide_sub.dropna(subset=['latitude', 'longitude'])
        all_substations.append(df_ide_sub)
        print(f"  i-DE substations: {len(df_ide_sub)}")
    else:
        print("  Could not detect lat/lon columns — inspect the CSV manually")
        print(f"  Full column list: {df_ide.columns.tolist()}")

# Process Endesa data
if not df_endesa.empty:
    print(f"\nEndesa columns: {df_endesa.columns.tolist()}")
    lat_col = next((c for c in df_endesa.columns if 'lat' in c.lower() or 'y_' in c.lower()), None)
    lon_col = next((c for c in df_endesa.columns if 'lon' in c.lower() or 'lng' in c.lower() or 'x_' in c.lower()), None)
    cap_col = next((c for c in df_endesa.columns if 'capac' in c.lower() or 'mw' in c.lower() or 'potenci' in c.lower()), None)

    print(f"  Detected: lat={lat_col}, lon={lon_col}, capacity={cap_col}")

    if lat_col and lon_col:
        df_end_sub = df_endesa[[lat_col, lon_col] + ([cap_col] if cap_col else [])].copy()
        df_end_sub.columns = ['latitude', 'longitude'] + (['capacity_mw'] if cap_col else [])
        df_end_sub['distributor'] = 'Endesa'
        df_end_sub = df_end_sub.dropna(subset=['latitude', 'longitude'])
        all_substations.append(df_end_sub)
        print(f"  Endesa substations: {len(df_end_sub)}")
    else:
        print("  Could not detect lat/lon columns — inspect the CSV manually")

# Build GeoDataFrame
if all_substations:
    df_all = pd.concat(all_substations, ignore_index=True)
    gdf = gpd.GeoDataFrame(
        df_all,
        geometry=[Point(lon, lat) for lon, lat in zip(df_all['longitude'], df_all['latitude'])],
        crs="EPSG:4326"
    )
    # Filter to Spain bounding box
    gdf = gdf[
        gdf['latitude'].between(27, 44) &
        gdf['longitude'].between(-10, 5)
    ]
    gdf.to_file("data/processed/grid_substations.gpkg", driver="GPKG")
    print(f"\nSaved {len(gdf)} substations to data/processed/grid_substations.gpkg")
    print(f"Distributor breakdown:\n{gdf['distributor'].value_counts().to_string()}")
else:
    print("\nNo substations to merge — both downloads may have failed.")
    print("ACTION NEEDED: Download manually from the portals in DATA_SOURCES.md")
    print("  - i-DE: https://www.i-de.es/conexion-red-electrica/suministro-electrico/mapa-capacidad-consumo")
    print("  - Endesa: https://www.edistribucion.com/es/red-electrica/Nodos_capacidad_acceso.html")

print("\nNote: Viesgo data requires manual export from their interactive map.")
print("  URL: https://www.viesgo.com/distribucion/mapa-interactivo/")
