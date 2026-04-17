"""
Parse i-DE Grid Capacity CSV and convert UTM to WGS84
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import pyproj
import os

RAW_FILE = "data/raw/grid_ide_capacity.csv"
OUT_FILE = "data/processed/grid_ide_substations.gpkg"
OUT_CSV  = "data/processed/grid_ide_substations.csv"

# Read with proper encoding (UTF-8 BOM) and Spanish decimal separator
df = pd.read_csv(RAW_FILE, encoding='utf-8-sig', sep=';', decimal=',')
print(f"Rows: {len(df)}")
print(f"Columns:\n{df.columns.tolist()}")
print(f"\nSample:\n{df.head(3).to_string()}")

# Clean column names
df.columns = [c.strip() for c in df.columns]

# Rename for clarity
rename = {
    'Gestor de red': 'distributor',
    'Provincia': 'province',
    'Municipio': 'municipality',
    'Coordenada UTM X': 'utm_x',
    'Coordenada UTM Y': 'utm_y',
    'Subestación': 'substation_name',
    'Nivel de Tensión (kV)': 'voltage_kv',
    'Capacidad firme disponible (MW)': 'capacity_mw',
    'Capacidad de acceso firme de demanda ocupada (MW)': 'capacity_occupied_mw',
    'Denominación del Punto de Conexión': 'connection_point_name',
    'Identificador del Punto de Conexión': 'connection_point_id',
}
# Only rename columns that exist
rename = {k: v for k, v in rename.items() if k in df.columns}
df = df.rename(columns=rename)

print(f"\nRenamed columns: {df.columns.tolist()}")

# Fix decimal separators and convert to numeric
for col in ['utm_x', 'utm_y', 'capacity_mw']:
    if col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col] = pd.to_numeric(df[col], errors='coerce')

print(f"\nUTM X range: {df['utm_x'].min():.0f} – {df['utm_x'].max():.0f}")
print(f"UTM Y range: {df['utm_y'].min():.0f} – {df['utm_y'].max():.0f}")
print(f"Capacity (MW) range: {df['capacity_mw'].min():.1f} – {df['capacity_mw'].max():.1f}")

# Convert UTM Zone 30N (EPSG:25830) → WGS84 (EPSG:4326)
# i-DE operates primarily in northern/central Spain (UTM zone 30)
transformer = pyproj.Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

valid = df.dropna(subset=['utm_x', 'utm_y'])
lons, lats = transformer.transform(valid['utm_x'].values, valid['utm_y'].values)

df.loc[valid.index, 'longitude'] = lons
df.loc[valid.index, 'latitude'] = lats

# Filter to Spain bbox
df = df[df['latitude'].between(27, 44) & df['longitude'].between(-10, 5)]
print(f"\nAfter geo-filter: {len(df)} substations")

# Add distributor label
df['distributor_network'] = 'i-DE'

# Build GeoDataFrame
gdf = gpd.GeoDataFrame(
    df,
    geometry=[Point(lon, lat) for lon, lat in zip(df['longitude'], df['latitude'])],
    crs="EPSG:4326"
)

gdf.to_file(OUT_FILE, driver="GPKG")
print(f"Saved to {OUT_FILE}")

# Save CSV without geometry
save_cols = ['distributor_network', 'province', 'municipality', 'substation_name',
             'voltage_kv', 'capacity_mw', 'capacity_occupied_mw',
             'connection_point_name', 'latitude', 'longitude']
save_cols = [c for c in save_cols if c in df.columns]
df[save_cols].to_csv(OUT_CSV, index=False, encoding='utf-8')
print(f"Saved CSV to {OUT_CSV}")

print(f"\nCapacity distribution (MW):")
print(df['capacity_mw'].describe().round(2).to_string())
print(f"\nProvince breakdown (top 10):")
if 'province' in df.columns:
    print(df['province'].value_counts().head(10).to_string())
