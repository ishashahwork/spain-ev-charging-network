"""
Download Endesa e-distribución demand capacity nodes
"""
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import os

os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DatathonProject/1.0)"}

# Try the demand capacity page to get current URLs
import re

# Known working URL pattern (October 2025 confirmed in search)
# Pattern: /content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/YYYYMM_DD_RXXXX_demanda.csv
# Try April 2026 first, then fall back to March/Feb 2026

urls_to_try = [
    # e-distribución demand (R1299)
    "https://www.edistribucion.com/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/202604/2026_04_01_R1299_demanda.csv",
    "https://www.edistribucion.com/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/202603/2026_03_05_R1299_demanda.csv",
    "https://www.edistribucion.com/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/202602/2026_02_04_R1299_demanda.csv",
    "https://www.edistribucion.com/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/202601/2026_01_07_R1299_demanda.csv",
    "https://www.edistribucion.com/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/202511/2025_11_05_R1299_demanda.csv",
    "https://www.edistribucion.com/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/202510/2025_10_03_R1299_demanda.csv",
    "https://www.edistribucion.com/content/dam/edistribucion/conexion-a-la-red/descargables/nodos/demanda/2025_10_03_R1026_demanda.csv",
]

df_endesa = pd.DataFrame()
used_url = None

for url in urls_to_try:
    try:
        print(f"Trying: {url.split('/')[-1]}...", end=" ")
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        with open("data/raw/grid_endesa_demand.csv", "wb") as f:
            f.write(resp.content)
        print(f"OK ({len(resp.content)//1024} KB)")
        used_url = url

        # Try parsing
        for sep in [';', ',', '\t']:
            for enc in ['utf-8-sig', 'latin-1', 'utf-8']:
                try:
                    df_endesa = pd.read_csv("data/raw/grid_endesa_demand.csv", sep=sep, encoding=enc)
                    if len(df_endesa.columns) > 3:
                        print(f"  Parsed OK: {len(df_endesa)} rows, sep='{sep}', enc={enc}")
                        break
                except: pass
            if not df_endesa.empty:
                break
        if not df_endesa.empty:
            break

    except Exception as e:
        print(f"FAIL ({str(e)[:50]})")

if df_endesa.empty:
    # Try fetching the page to find actual current links
    print("\nFetching demand capacity page to find current CSV links...")
    page = requests.get(
        "https://www.edistribucion.com/es/red-electrica/nodos-capacidad-red/capacidad-demanda.html",
        headers=HEADERS, timeout=30
    )
    csv_links = re.findall(r'href="([^"]*demanda[^"]*\.csv)"', page.text, re.IGNORECASE)
    print(f"  Found {len(csv_links)} CSV links: {csv_links[:5]}")

    for link in csv_links[:3]:
        url = f"https://www.edistribucion.com{link}" if link.startswith('/') else link
        try:
            print(f"  Trying {url.split('/')[-1]}...", end=" ")
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            with open("data/raw/grid_endesa_demand.csv", "wb") as f:
                f.write(resp.content)
            print(f"OK ({len(resp.content)//1024} KB)")
            df_endesa = pd.read_csv("data/raw/grid_endesa_demand.csv", sep=';', encoding='latin-1')
            break
        except Exception as e:
            print(f"FAIL: {e}")

print(f"\nEndesa data: {len(df_endesa)} rows")
print(f"Columns: {df_endesa.columns.tolist()}")
if not df_endesa.empty:
    print(f"Sample:\n{df_endesa.head(3).to_string()}")

    # Detect coordinate and capacity columns
    df_endesa.columns = [c.strip() for c in df_endesa.columns]
    print(f"\nAll columns:\n{df_endesa.dtypes.to_string()}")

    # Save processed version
    df_endesa.to_csv("data/processed/grid_endesa_substations.csv", index=False, encoding='utf-8')
    print(f"\nSaved to data/processed/grid_endesa_substations.csv")
