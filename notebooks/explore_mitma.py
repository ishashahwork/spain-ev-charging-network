import geopandas as gpd
import pandas as pd
import gzip

BASE = "C:/Users/LEGION/Desktop/MASTERS/Datathon/data/raw/mitma_rutas"

# ── 1. Shapefile ──────────────────────────────────────────────────────────────
print("=" * 60)
print("GEOMETRY SHAPEFILE")
print("=" * 60)
gdf = gpd.read_file(f"{BASE}/geometria/Geometria_tramos.shp")
print(f"Rows:    {len(gdf):,}")
print(f"CRS:     {gdf.crs}")
print(f"Columns: {list(gdf.columns)}")
print(f"\nDtypes:\n{gdf.dtypes}")
print(f"\nSample (3 rows):\n{gdf.head(3).to_string()}")
print(f"\nNulls:\n{gdf.isnull().sum()}")
print(f"\nGeometry types: {gdf.geom_type.value_counts().to_string()}")
print(f"Bounds: {gdf.total_bounds}")

# ── 2. rt_tramo_val.csv ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("RT_TRAMO_VAL.CSV (road segment validation/attributes)")
print("=" * 60)
val = pd.read_csv(f"{BASE}/geometria/rt_tramo_val.csv", sep=None, engine="python", nrows=5)
print(f"Columns: {list(val.columns)}")
print(val.to_string())
val_full = pd.read_csv(f"{BASE}/geometria/rt_tramo_val.csv", sep=None, engine="python")
print(f"\nTotal rows: {len(val_full):,}")
print(f"\nValue counts for road-type-like columns:")
for col in val_full.columns:
    if val_full[col].dtype == object and val_full[col].nunique() < 50:
        print(f"\n  {col}:\n{val_full[col].value_counts().head(15).to_string()}")

# ── 3. One informacion_tramo file ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("INFORMACION_TRAMO (traffic per segment, sample day)")
print("=" * 60)
info_file = f"{BASE}/informacion_tramo/20230829_Tramos_info_odmatrix.csv.gz"
df = pd.read_csv(info_file, sep=None, engine="python", compression="gzip", nrows=5)
print(f"Columns: {list(df.columns)}")
print(df.to_string())
df_full = pd.read_csv(info_file, sep=None, engine="python", compression="gzip")
print(f"\nTotal rows: {len(df_full):,}")
print(f"\nDtypes:\n{df_full.dtypes}")
print(f"\nDescriptive stats:\n{df_full.describe().to_string()}")
print(f"\nNulls:\n{df_full.isnull().sum()}")
