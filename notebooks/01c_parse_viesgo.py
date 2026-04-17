"""
Parse Viesgo grid capacity files (demand + generation)
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import pyproj
import os
import re

os.makedirs("data/processed", exist_ok=True)

transformer = pyproj.Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

def to_float_es(series):
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    return (series.astype(str).str.strip()
            .str.replace(r'\.(?=\d{3})', '', regex=True)
            .str.replace(',', '.', regex=False)
            .pipe(pd.to_numeric, errors='coerce'))

def inspect_file(path, label):
    print(f"\n=== {label} ===")
    for enc in ['utf-8-sig', 'latin-1', 'utf-8']:
        try:
            df = pd.read_csv(path, sep=';', encoding=enc, dtype=str)
            if len(df.columns) > 2:
                print(f"  Encoding: {enc}, Rows: {len(df)}, Cols: {len(df.columns)}")
                print(f"  Columns: {df.columns.tolist()}")
                print(f"  Sample:\n{df.head(3).to_string()}")
                return df, enc
        except: pass
    return pd.DataFrame(), None

df_dem, enc_dem = inspect_file("data/raw/viesgo/2026_04_01_R1005_demanda.csv", "Demanda")
df_gen, enc_gen = inspect_file("data/raw/viesgo/2026_04_01_R1005_generacion.csv", "Generacion")

# Use demand file as primary (EV charging = demand connection)
df = df_dem if not df_dem.empty else df_gen
print(f"\nUsing: {'demanda' if not df_dem.empty else 'generacion'}")

# Clean columns
df.columns = [c.strip() for c in df.columns]
print(f"\nAll columns:\n{df.dtypes.to_string()}")

# Keyword-based column detection
def find_col(keywords, df):
    for col in df.columns:
        col_norm = col.lower()
        if all(k.lower() in col_norm for k in keywords):
            return col
    return None

utm_x_col = find_col(['utm', 'x'], df) or find_col(['coordenada', 'x'], df)
utm_y_col = find_col(['utm', 'y'], df) or find_col(['coordenada', 'y'], df)
cap_col   = find_col(['capacidad firme disponible'], df)
volt_col  = find_col(['tensi'], df)
prov_col  = find_col(['provincia'], df)
muni_col  = find_col(['municipio'], df)
sub_col   = find_col(['subestaci'], df) or find_col(['nombre'], df)

print(f"\nDetected: utm_x={utm_x_col}, utm_y={utm_y_col}, cap={cap_col}")

# Convert
for col, name in [(utm_x_col, 'utm_x'), (utm_y_col, 'utm_y'),
                  (cap_col, 'capacity_mw'), (volt_col, 'voltage_kv')]:
    if col:
        df[name] = to_float_es(df[col])

# UTM filter
valid = df[df['utm_x'].between(100_000, 950_000) & df['utm_y'].between(3_800_000, 5_000_000)].copy()
print(f"\nValid UTM rows: {len(valid)}")

if len(valid) == 0:
    # Try swapped X/Y
    print("Trying swapped X/Y...")
    df['utm_x_t'] = to_float_es(df[utm_y_col]) if utm_y_col else pd.NA
    df['utm_y_t'] = to_float_es(df[utm_x_col]) if utm_x_col else pd.NA
    valid = df[df['utm_x_t'].between(100_000, 950_000) & df['utm_y_t'].between(3_800_000, 5_000_000)].copy()
    if len(valid) > 0:
        valid['utm_x'] = valid['utm_x_t']
        valid['utm_y'] = valid['utm_y_t']
        print(f"  Found {len(valid)} valid rows with swapped columns")

if len(valid) > 0:
    lons, lats = transformer.transform(valid['utm_x'].values, valid['utm_y'].values)
    valid['longitude'] = lons
    valid['latitude']  = lats
    valid['distributor_network'] = 'Viesgo'

    valid = valid[valid['latitude'].between(27, 44) & valid['longitude'].between(-10, 5)]
    print(f"After Spain bbox: {len(valid)} substations")
    print(f"Lat: {valid['latitude'].min():.2f}–{valid['latitude'].max():.2f}")
    print(f"Lon: {valid['longitude'].min():.2f}–{valid['longitude'].max():.2f}")
    if 'capacity_mw' in valid.columns:
        print(f"Capacity (MW): {valid['capacity_mw'].min():.1f}–{valid['capacity_mw'].max():.1f}, mean={valid['capacity_mw'].mean():.1f}")

    # Save
    valid.to_csv("data/processed/grid_viesgo_substations.csv", index=False, encoding='utf-8')
    print("\nSaved to data/processed/grid_viesgo_substations.csv")

    # Merge with existing substations
    existing = pd.read_csv("data/processed/grid_substations.csv", encoding='utf-8')
    keep = ['distributor_network', 'latitude', 'longitude', 'voltage_kv', 'capacity_mw',
            'substation_name', 'province_name', 'municipality_name']

    # Map Viesgo columns to standard names
    rename_v = {}
    if sub_col: rename_v[sub_col] = 'substation_name'
    if prov_col: rename_v[prov_col] = 'province_name'
    if muni_col: rename_v[muni_col] = 'municipality_name'
    valid_renamed = valid.rename(columns=rename_v)

    viesgo_cols = [c for c in keep if c in valid_renamed.columns]
    viesgo_df = valid_renamed[viesgo_cols].copy()

    merged = pd.concat([existing, viesgo_df], ignore_index=True)

    gdf_merged = gpd.GeoDataFrame(
        merged,
        geometry=[Point(lon, lat) for lon, lat in zip(merged['longitude'], merged['latitude'])],
        crs="EPSG:4326"
    )
    gdf_merged.to_file("data/processed/grid_substations.gpkg", driver="GPKG")
    merged.to_csv("data/processed/grid_substations.csv", index=False, encoding='utf-8')

    print(f"\nUpdated grid_substations: {len(merged)} total substations")
    print(merged['distributor_network'].value_counts().to_string())
else:
    print("\nCould not parse coordinates — printing raw column values for inspection:")
    if utm_x_col: print(f"  {utm_x_col}: {df[utm_x_col].head(5).tolist()}")
    if utm_y_col: print(f"  {utm_y_col}: {df[utm_y_col].head(5).tolist()}")
