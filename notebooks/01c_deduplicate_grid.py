"""
Deduplicate grid substations to one row per physical location.
Keeps original file intact, saves deduplicated version separately.
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

df = pd.read_csv("data/processed/grid_substations.csv", encoding='utf-8')
print(f"Original rows: {len(df)}")
print(f"Unique lat/lon points: {df.groupby(['latitude','longitude']).ngroups}")

# For each unique location: keep max capacity, best voltage, first values for metadata
dedup = (df.groupby(['latitude', 'longitude'], as_index=False)
           .agg(
               distributor_network = ('distributor_network', 'first'),
               capacity_mw         = ('capacity_mw', 'max'),
               voltage_kv          = ('voltage_kv', 'max'),   # highest voltage available
               substation_name     = ('substation_name', 'first'),
               province_name       = ('province_name', 'first'),
               municipality_name   = ('municipality_name', 'first'),
               region              = ('region', 'first'),
               n_voltage_levels    = ('voltage_kv', 'count'),  # how many voltage levels exist
           ))

print(f"\nDeduplicated rows: {len(dedup)}")
print(f"\nCapacity (MW) after dedup:")
print(dedup['capacity_mw'].describe().round(2).to_string())
print(f"\nWith >0 MW: {(dedup['capacity_mw']>0).sum()} ({(dedup['capacity_mw']>0).mean()*100:.1f}%)")
print(f"With >5 MW: {(dedup['capacity_mw']>5).sum()}")
print(f"With >20 MW: {(dedup['capacity_mw']>20).sum()}")
print(f"\nBy distributor:\n{dedup['distributor_network'].value_counts().to_string()}")

# Save deduplicated CSV and GPKG
dedup.to_csv("data/processed/grid_substations_dedup.csv", index=False, encoding='utf-8')

gdf = gpd.GeoDataFrame(
    dedup,
    geometry=[Point(lon, lat) for lon, lat in zip(dedup['longitude'], dedup['latitude'])],
    crs="EPSG:4326"
)
gdf.to_file("data/processed/grid_substations_dedup.gpkg", driver="GPKG")

print(f"\nSaved:")
print(f"  data/processed/grid_substations.csv        <- original (4,926 rows, untouched)")
print(f"  data/processed/grid_substations.gpkg       <- original (untouched)")
print(f"  data/processed/grid_substations_dedup.csv  <- deduplicated ({len(dedup)} rows)")
print(f"  data/processed/grid_substations_dedup.gpkg <- deduplicated ({len(dedup)} rows)")
