"""
Download EV Charging Points — NAP DGT (National Access Point)
=============================================================
Source: https://nap.dgt.es/en/dataset/puntos-de-recarga-electrica-para-vehiculos
Format: DATEX2v3 XML (official Spanish NAP)
Output: data/raw/ev_charging_raw.xml + data/processed/ev_charging_baseline.csv
"""

import requests
import xml.etree.ElementTree as ET
import pandas as pd
import os

os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

URL = "https://infocar.dgt.es/datex2/v3/miterd/EnergyInfrastructureTablePublication/electrolineras.xml"
RAW_FILE = "data/raw/ev_charging_raw.xml"
OUT_CSV  = "data/processed/ev_charging_baseline.csv"

# ─────────────────────────────────────────────────────────────────────────────
# 1. DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────
print("Downloading EV charging data from NAP DGT...")
headers = {"User-Agent": "Mozilla/5.0 (compatible; DatathonProject/1.0)"}
resp = requests.get(URL, headers=headers, timeout=120)
resp.raise_for_status()
with open(RAW_FILE, "wb") as f:
    f.write(resp.content)
print(f"  Saved {len(resp.content)/1024:.0f} KB to {RAW_FILE}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. PARSE XML
# ─────────────────────────────────────────────────────────────────────────────
print("Parsing DATEX2 XML...")
tree = ET.parse(RAW_FILE)
root = tree.getroot()

# DATEX2v3 namespaces
ns = {
    'd2': 'http://datex2.eu/schema/3/d2Payload',
    'loc': 'http://datex2.eu/schema/3/locationExtension',
    'ei': 'http://datex2.eu/schema/3/energyInfrastructure',
    'com': 'http://datex2.eu/schema/3/common',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
}

records = []

# Try to find all energy infrastructure sites
# DATEX2v3 structure varies — walk the tree to find stations
def find_all_tags(root, tag_fragment):
    """Find all elements whose tag contains the given fragment."""
    return [el for el in root.iter() if tag_fragment.lower() in el.tag.lower()]

# Find location elements (latitude/longitude)
all_elements = list(root.iter())
print(f"  Total XML elements: {len(all_elements)}")

# Print sample tags to understand structure
sample_tags = list({el.tag.split('}')[-1] for el in all_elements[:500]})
print(f"  Sample element types: {sorted(sample_tags)[:30]}")

# Try to extract station records from common DATEX2 patterns
stations = find_all_tags(root, 'EnergyInfrastructureSite')
if not stations:
    stations = find_all_tags(root, 'energyInfrastructureSite')
if not stations:
    stations = find_all_tags(root, 'Site')

print(f"  Found {len(stations)} station elements")

for station in stations:
    record = {}

    # Try to get all child text values
    for child in station.iter():
        tag = child.tag.split('}')[-1]
        if child.text and child.text.strip():
            record[tag] = child.text.strip()

    if record:
        records.append(record)

if records:
    df = pd.DataFrame(records)
    print(f"\n  Parsed {len(df)} records")
    print(f"  Columns: {df.columns.tolist()[:20]}")
    df.to_csv(OUT_CSV, index=False, encoding='utf-8')
    print(f"  Saved to {OUT_CSV}")
else:
    # Fallback: save the raw tag structure for manual inspection
    with open("data/raw/ev_charging_xml_structure.txt", "w", encoding="utf-8") as f:
        for el in all_elements[:200]:
            tag = el.tag.split('}')[-1]
            text = (el.text or "").strip()[:80]
            attribs = str(el.attrib)[:80]
            f.write(f"{tag}: text='{text}' attribs={attribs}\n")
    print("\n  Could not auto-parse — saved XML structure to data/raw/ev_charging_xml_structure.txt")
    print("  Review the structure file and adjust parser accordingly.")
