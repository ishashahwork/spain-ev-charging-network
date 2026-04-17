"""
Improved EV Charging Parser — extracts lat/lon + power per station
"""
import xml.etree.ElementTree as ET
import pandas as pd
import os

RAW_FILE  = "data/raw/ev_charging_raw.xml"
OUT_CSV   = "data/processed/ev_charging_baseline.csv"

print("Parsing DATEX2 XML (improved)...")
tree = ET.parse(RAW_FILE)
root = tree.getroot()

def tag(el):
    return el.tag.split('}')[-1]

def find(el, name):
    for child in el.iter():
        if tag(child) == name and child.text:
            return child.text.strip()
    return None

stations = [el for el in root.iter() if tag(el) == 'energyInfrastructureSite']
print(f"  Stations found: {len(stations)}")

records = []
for site in stations:
    lat  = find(site, 'latitude')
    lon  = find(site, 'longitude')
    if lat is None or lon is None:
        continue

    # Count connectors and get max power
    connectors = [el for el in site.iter() if tag(el) == 'connector']
    n_connectors = len(connectors)

    powers = []
    for c in connectors:
        p = find(c, 'maxPowerAtSocket')
        if p:
            try: powers.append(float(p))
            except: pass

    max_power_kw = max(powers)/1000 if powers else None
    total_power_kw = sum(powers)/1000 if powers else None

    # Connector types
    ctypes = list({find(c, 'connectorType') for c in connectors if find(c, 'connectorType')})

    # Site identifiers
    nat_id   = find(site, 'nationalIdentifier')
    site_id  = site.get('id', '')
    name_val = find(site, 'label') or find(site, 'name')
    postcode = find(site, 'postcode')
    country  = find(site, 'country')
    operator = find(site, 'operator')
    type_site = find(site, 'typeOfSite')

    records.append({
        'site_id':         site_id,
        'national_id':     nat_id,
        'name':            name_val,
        'latitude':        float(lat),
        'longitude':       float(lon),
        'postcode':        postcode,
        'country':         country,
        'operator':        operator,
        'type_of_site':    type_site,
        'n_connectors':    n_connectors,
        'max_power_kw':    max_power_kw,
        'total_power_kw':  total_power_kw,
        'connector_types': str(ctypes),
    })

df = pd.DataFrame(records)
print(f"\nParsed {len(df)} stations with coordinates")
print(f"\nColumns:\n{df.dtypes.to_string()}")
print(f"\nSample:\n{df.head(5).to_string()}")
print(f"\nPower distribution (kW):\n{df['max_power_kw'].describe().round(1).to_string()}")
print(f"\nType of site:\n{df['type_of_site'].value_counts().to_string()}")

# Spain bounding box filter
df = df[(df['latitude'].between(27, 44)) & (df['longitude'].between(-10, 5))]
print(f"\nAfter Spain bbox filter: {len(df)} stations")

df.to_csv(OUT_CSV, index=False, encoding='utf-8')
print(f"\nSaved to {OUT_CSV}")
