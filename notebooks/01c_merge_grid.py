"""
Parse and merge i-DE + Endesa grid capacity data
Both use UTM Zone 30N (EPSG:25830) — convert to WGS84 EPSG:4326
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import pyproj
import os

os.makedirs("data/processed", exist_ok=True)

transformer = pyproj.Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

def to_float_es(series):
    """Convert Spanish-format number strings to float.
    Spanish format: period=thousands separator, comma=decimal separator.
    E.g. '499.100,028' → 499100.028
    """
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    return (series.astype(str)
            .str.strip()
            .str.replace(r'\.(?=\d{3})', '', regex=True)  # remove thousands dots
            .str.replace(',', '.', regex=False)
            .pipe(pd.to_numeric, errors='coerce'))

def parse_utm_file(csv_path, distributor_name):
    """Read a grid capacity CSV and return a clean GeoDataFrame."""
    # Read as string to preserve original values, handle encoding
    for enc in ['utf-8-sig', 'latin-1', 'utf-8']:
        try:
            df = pd.read_csv(csv_path, sep=';', encoding=enc, dtype=str)
            if len(df.columns) > 3:
                break
        except: pass

    # Clean column names (strip whitespace + normalize encoding artifacts)
    df.columns = [c.strip() for c in df.columns]

    # Keyword-based column detection (encoding-agnostic)
    def find_col(keywords, df):
        for col in df.columns:
            col_norm = col.lower()
            if all(k in col_norm for k in keywords):
                return col
        return None

    utm_x_col  = find_col(['utm', 'x'], df) or find_col(['coordenada', 'x'], df)
    utm_y_col  = find_col(['utm', 'y'], df) or find_col(['coordenada', 'y'], df)
    cap_col    = find_col(['capacidad firme disponible'], df)
    occ_col    = find_col(['demanda ocupada'], df)
    volt_col   = find_col(['tensi'], df)
    prov_col   = find_col(['provincia.1'], df) or find_col(['provincia'], df)
    muni_col   = find_col(['municipio.1'], df) or find_col(['municipio'], df)
    sub_col    = find_col(['nombre subestaci'], df) or find_col(['subestaci'], df)
    reg_col    = find_col(['comunidad'], df)

    print(f"  Detected cols: utm_x={utm_x_col}, utm_y={utm_y_col}, cap={cap_col}")

    rename = {}
    for new, old in [('utm_x', utm_x_col), ('utm_y', utm_y_col),
                     ('capacity_mw', cap_col), ('capacity_occupied_mw', occ_col),
                     ('voltage_kv', volt_col), ('province_name', prov_col),
                     ('municipality_name', muni_col), ('substation_name', sub_col),
                     ('region', reg_col)]:
        if old:
            rename[old] = new
    df = df.rename(columns=rename)

    # Convert numeric columns
    for col in ['utm_x', 'utm_y', 'capacity_mw', 'capacity_occupied_mw', 'voltage_kv']:
        if col in df.columns:
            df[col] = to_float_es(df[col])

    # Filter valid UTM coordinates
    df = df.dropna(subset=['utm_x', 'utm_y'])
    # UTM X for Spain should be 100k–900k, Y should be 3.8M–5M
    df = df[(df['utm_x'].between(100_000, 950_000)) &
            (df['utm_y'].between(3_800_000, 5_000_000))]

    print(f"  Valid rows after UTM filter: {len(df)}")
    print(f"  UTM X: {df['utm_x'].min():.0f}–{df['utm_x'].max():.0f}")
    print(f"  UTM Y: {df['utm_y'].min():.0f}–{df['utm_y'].max():.0f}")

    # Transform to WGS84
    lons, lats = transformer.transform(df['utm_x'].values, df['utm_y'].values)
    df['longitude'] = lons
    df['latitude']  = lats
    df['distributor_network'] = distributor_name

    # Spain bbox sanity check
    df = df[(df['latitude'].between(27, 44)) & (df['longitude'].between(-10, 5))]
    print(f"  After WGS84 bbox filter: {len(df)} substations")
    print(f"  Lat: {df['latitude'].min():.2f}–{df['latitude'].max():.2f}")
    print(f"  Lon: {df['longitude'].min():.2f}–{df['longitude'].max():.2f}")
    if 'capacity_mw' in df.columns:
        print(f"  Capacity (MW): {df['capacity_mw'].min():.1f}–{df['capacity_mw'].max():.1f}, mean={df['capacity_mw'].mean():.1f}")

    return df

# ─── Parse both datasets ──────────────────────────────────────────────────────
print("=== i-DE ===")
df_ide = parse_utm_file("data/raw/grid_ide_capacity.csv", "i-DE")

print("\n=== Endesa ===")
df_end = parse_utm_file("data/raw/grid_endesa_demand.csv", "Endesa")

# ─── Merge ───────────────────────────────────────────────────────────────────
keep = ['distributor_network', 'latitude', 'longitude', 'voltage_kv', 'capacity_mw',
        'substation_name', 'province_name', 'municipality_name', 'region']

frames = []
for df, name in [(df_ide, 'i-DE'), (df_end, 'Endesa')]:
    cols = [c for c in keep if c in df.columns]
    frames.append(df[cols])

df_all = pd.concat(frames, ignore_index=True)
print(f"\nTotal merged substations: {len(df_all)}")
print(f"By distributor:\n{df_all['distributor_network'].value_counts().to_string()}")

# Build GeoDataFrame
gdf = gpd.GeoDataFrame(
    df_all,
    geometry=[Point(lon, lat) for lon, lat in zip(df_all['longitude'], df_all['latitude'])],
    crs="EPSG:4326"
)

gdf.to_file("data/processed/grid_substations.gpkg", driver="GPKG")
gdf.drop(columns='geometry').to_csv("data/processed/grid_substations.csv", index=False, encoding='utf-8')

print(f"\nSaved to data/processed/grid_substations.gpkg")
print(f"Saved to data/processed/grid_substations.csv")
print(f"\nCapacity summary (MW):")
print(df_all['capacity_mw'].describe().round(2).to_string())

# Note about Viesgo
print("""
=== Viesgo ===
Viesgo covers: Cantabria, Asturias, parts of Murcia.
Their interactive map requires manual data export.
Fallback: use CNMC territorial data + i-DE/Endesa coverage as proxy.
URL: https://www.viesgo.com/distribucion/mapa-interactivo/
""")
