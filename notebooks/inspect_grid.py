import pandas as pd
import numpy as np

df = pd.read_csv("data/processed/grid_substations.csv", encoding='utf-8')

with open("data/processed/grid_inspect.txt", "w", encoding="utf-8") as out:
    out.write(f"Total rows: {len(df)}\n")
    out.write(f"Columns: {df.columns.tolist()}\n\n")
    out.write(f"=== SAMPLE (5 rows per distributor) ===\n")
    for dist in df['distributor_network'].unique():
        out.write(f"\n--- {dist} ---\n")
        out.write(df[df['distributor_network']==dist].head(5).to_string() + "\n")

    out.write(f"\n=== CAPACITY (MW) DISTRIBUTION ===\n")
    out.write(df['capacity_mw'].describe().round(2).to_string() + "\n")
    out.write(f"\n=== VOLTAGE LEVELS ===\n")
    out.write(df['voltage_kv'].value_counts().head(15).to_string() + "\n")
    out.write(f"\n=== HOW MANY ROWS PER PHYSICAL SUBSTATION? ===\n")
    # Each substation appears multiple times (one row per voltage level)
    if 'substation_name' in df.columns:
        sub_counts = df.groupby(['distributor_network','substation_name']).size().describe()
        out.write(sub_counts.to_string() + "\n")
        unique_subs = df.groupby(['distributor_network','latitude','longitude']).size().reset_index()
        out.write(f"\nUnique lat/lon points: {len(unique_subs)}\n")
        out.write(f"Total rows: {len(df)}\n")
        out.write(f"Avg rows per location: {len(df)/len(unique_subs):.1f}\n")
    out.write(f"\n=== CAPACITY = 0 BREAKDOWN ===\n")
    out.write(f"Rows with 0 MW: {(df['capacity_mw']==0).sum()} ({(df['capacity_mw']==0).mean()*100:.1f}%)\n")
    out.write(f"Rows with >0 MW: {(df['capacity_mw']>0).sum()} ({(df['capacity_mw']>0).mean()*100:.1f}%)\n")
    out.write(f"Rows with >5 MW: {(df['capacity_mw']>5).sum()}\n")
    out.write(f"Rows with >20 MW: {(df['capacity_mw']>20).sum()}\n")

print("Done")
