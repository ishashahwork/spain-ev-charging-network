"""
Build Colab Notebooks — Convert .py scripts to executed .ipynb files
=====================================================================
Creates 6 notebooks in notebooks/v1/ with alternating markdown + code cells.
Each notebook is executed via nbconvert to embed visible outputs.

Run from the Datathon/ working directory:
  python notebooks/build_colab_notebooks.py
"""

import nbformat as nbf
import subprocess
import sys
import os
from pathlib import Path

os.chdir("C:/Users/LEGION/Desktop/MASTERS/Datathon")
OUT_DIR = Path("notebooks/v1")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PYTHON_ENV = sys.executable  # use current conda env python

# ─────────────────────────────────────────────────────────────────────────────
# Helper to build a notebook from (markdown, code) cell pairs
# ─────────────────────────────────────────────────────────────────────────────
def make_notebook(cells):
    nb = nbf.v4.new_notebook()
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3"
    }
    nb.metadata["language_info"] = {"name": "python", "version": "3.11"}
    for kind, content in cells:
        if kind == "md":
            nb.cells.append(nbf.v4.new_markdown_cell(content.strip()))
        else:
            nb.cells.append(nbf.v4.new_code_cell(content.strip()))
    return nb


def save_and_execute(nb, path):
    """Save notebook then execute it in-place to embed outputs."""
    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        nbf.write(nb, f)
    print(f"  Executing {path.name} ...", flush=True)
    result = subprocess.run(
        [
            PYTHON_ENV, "-m", "nbconvert",
            "--to", "notebook",
            "--execute",
            "--inplace",
            "--ExecutePreprocessor.timeout=600",
            "--ExecutePreprocessor.kernel_name=python3",
            str(path),
        ],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  [WARN] Execution error:\n{result.stderr[-2000:]}")
    else:
        print(f"  [OK]  {path.name}")
    return result.returncode == 0


# ─────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 1 — Data Ingestion
# ─────────────────────────────────────────────────────────────────────────────
nb1_cells = [
("md", """# Notebook 1 — Data Ingestion
**IE × Iberdrola Datathon 2026 | EV Charging Network Optimization**

This notebook downloads and processes all input datasets required for the analysis:
- EV charging baseline (National Access Point)
- Grid substations (i-DE, Endesa, Viesgo)
- MITMA official road network (Ministry of Transport)
- DGT vehicle registrations by province (EV penetration)

**Data sources:** National Access Point (NAP), i-DE Iberdrola, Endesa e-distribución, Viesgo Distribución, MITMA movilidad-opendata, DGT
"""),
("code", """import os, sys
os.chdir("C:/Users/LEGION/Desktop/MASTERS/Datathon")
print("Working directory:", os.getcwd())
"""),

("md", """## 1.1 EV Charging Baseline
Source: National Access Point for Traffic and Mobility — Electric vehicle charging points dataset.
We use this to establish the existing charging infrastructure baseline and compute `total_existing_stations_baseline` (KPI in File 1).
"""),
("code", """import pandas as pd

baseline = pd.read_csv("data/processed/ev_charging_baseline.csv")
print(f"Total stations in baseline: {len(baseline):,}")
print(f"Columns: {list(baseline.columns)}")
print(f"\\nSample:")
print(baseline.head(5).to_string())
print(f"\\nGrid status distribution (all, pre-filter):")
print(f"  Total connectors: {baseline['n_connectors'].sum():,}")
print(f"  Max power range: {baseline['max_power_kw'].min():.0f} – {baseline['max_power_kw'].max():.0f} kW")
"""),

("md", """## 1.2 Grid Substations — i-DE, Endesa, Viesgo
Substation-level capacity data from Spain's three main electricity distributors.
Used in Notebook 4 to assess grid viability at each proposed charging station location.

**Capacity estimation:** Where `capacity_mw = 0` (88% of nodes), capacity is estimated from `voltage_kv`
using Spanish REE planning norms (e.g. 132 kV → 120 MW, 66 kV → 40 MW).
"""),
("code", """substations = pd.read_csv("data/processed/grid_substations_dedup.csv")
print(f"Total substations: {len(substations):,}")
print(f"\\nBy distributor:")
print(substations["distributor_network"].value_counts().to_string())
print(f"\\nCapacity (MW) stats:")
print(substations["capacity_mw"].describe().round(2).to_string())
print(f"\\nVoltage (kV) distribution:")
print(substations["voltage_kv"].value_counts().sort_index().to_string())
"""),

("md", """## 1.3 MITMA Official Road Network
Source: Ministry of Transport and Sustainable Mobility — *Estudios de movilidad con Big Data: Rutas por Carretera*
(S3 bucket: `mitma-movilidad-v2`, folder: `estudios_rutas/`)

The geometry shapefile (`Geometria_tramos.shp`) contains **452,478 road segments** covering Spain's
complete road network, classified by the Ministry using official road codes (A-3, AP-7, N-2, etc.).

Traffic data from `informacion_tramo/` files provides actual vehicle flows per segment,
including long-distance trips (`largo`) and inter-provincial flows — the key demand signal for EV charging placement.
"""),
("code", """import geopandas as gpd

roads = gpd.read_file("data/processed/interurban_roads_mitma.gpkg")
print(f"Interurban road segments: {len(roads):,}")
print(f"CRS: {roads.crs}")
print(f"Total network length: {roads['length_km'].sum():,.0f} km")
print(f"\\nRoad category breakdown:")
print(roads["road_category"].value_counts().to_string())
print(f"\\nTop 10 routes by segment count:")
print(roads["route_segment"].value_counts().head(10).to_string())
print(f"\\nDemand score stats (traffic-weighted):")
print(roads["demand_score"].describe().round(1).to_string())
"""),

("md", """## 1.4 DGT Vehicle Registrations — EV Share by Province
Source: DGT (Dirección General de Tráfico) — monthly vehicle registration microdatos, 2023–2024.

Used to weight charger counts geographically: provinces with higher EV adoption
(Barcelona, Madrid, Valencia) receive more chargers per station than low-adoption areas.

**Methodology:** EV penetration factor = province_share / national_median_share, clamped to [0.5, 2.0]
to prevent extreme outliers from distorting the charger allocation.
"""),
("code", """ev_prov = pd.read_csv("data/processed/ev_share_by_province.csv", dtype={"CPRO": str})
print(f"Provinces in dataset: {len(ev_prov)}")
print(f"\\nTop 10 provinces by 2027 projected EV fleet:")
print(ev_prov[["CPRO","province_name","ev_share","ev_fleet_2027","ev_penetration_factor"]]
      .head(10).to_string(index=False))
print(f"\\nNational total: {ev_prov['ev_fleet_2027'].sum():,} EVs")
"""),

("md", """## 1.5 Dataset Summary
"""),
("code", """print("=" * 55)
print("DATA INGESTION SUMMARY")
print("=" * 55)
print(f"  EV charging baseline:      {len(baseline):,} stations")
print(f"  Grid substations:          {len(substations):,} nodes")
print(f"    i-DE:                    {(substations.distributor_network=='i-DE').sum():,}")
print(f"    Endesa:                  {(substations.distributor_network=='Endesa').sum():,}")
print(f"    Viesgo:                  {(substations.distributor_network=='Viesgo').sum():,}")
print(f"  Interurban road segments:  {len(roads):,}")
print(f"  Network length:            {roads['length_km'].sum():,.0f} km")
print(f"  Provinces (DGT EV data):   {len(ev_prov)}")
print(f"\\nAll datasets ready for pipeline.")
"""),
]

# ─────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 2 — EV Projection
# ─────────────────────────────────────────────────────────────────────────────
nb2_cells = [
("md", """# Notebook 2 — EV Fleet Projection (2027)
**IE × Iberdrola Datathon 2026**

**Mandatory requirement:** Teams must fork the official datos.gob.es GitHub repository
(*"Ruta a la electrificación: Deciphering the growth of electric vehicles in Spain through data analytics"*)
and use its output as the foundational EV projection for 2027.

This notebook documents the SARIMA model output and validates the 2027 projection
used throughout the pipeline.

**Source:** datos.gob.es GitHub fork — Exercise 3: Open Data
**Model:** SARIMA(1,0,2)(1,1,1)[12] on monthly DGT electric vehicle registrations (2015–2025)
**Output:** 659,323 total EVs in Spain by end of 2027
"""),
("code", """import json
import pandas as pd

with open("data/processed/ev_projection_results.json") as f:
    ev_proj = json.load(f)

print("EV Projection Results (datos.gob.es fork output):")
for k, v in ev_proj.items():
    print(f"  {k}: {v:,}" if isinstance(v, (int, float)) else f"  {k}: {v}")
"""),

("md", """## 2.1 Monthly Forecast (2026–2027)
The SARIMA model was trained on 132 months of DGT registration data (Jan 2015 – Dec 2025).
The model captures strong seasonality (peak registrations in Q4) and the exponential growth trend
in EV adoption driven by EU climate regulations and Spanish MOVES III subsidy programme.
"""),
("code", """forecast = pd.read_csv("data/processed/ev_monthly_forecast_2026_2027.csv")
print(f"Forecast columns: {list(forecast.columns)}")
print(f"\\nMonthly forecast (2026–2027):")
print(forecast.to_string(index=False))
print(f"\\nTotal projected registrations 2027: {forecast[forecast.columns[-1]].sum():,.0f}")
"""),

("md", """## 2.2 Key Assumptions
| Parameter | Value | Justification |
|---|---|---|
| Model | SARIMA(1,0,2)(1,1,1)[12] | Auto-ARIMA selection, ADF test confirms stationarity |
| Training period | Jan 2015 – Dec 2025 | 132 months — sufficient for seasonal pattern detection |
| Horizon | 2027 (12 months) | Datathon target year |
| EV definition | BEV + PHEV (COD_PROPULSION_ITV = 2) | Includes all plug-in electric vehicles |
| Total fleet 2027 | **659,323** | Cumulative fleet (not annual registrations) |

The 659,323 figure represents the **total EV fleet on Spanish roads** in 2027,
used as the denominator for demand calculations across the network.
"""),
("code", """print("MANDATORY KPI — Fixed for all pipeline outputs:")
print(f"  total_ev_projected_2027 = {ev_proj['total_ev_projected_2027']:,}")
print()
print("This value directly populates File 1 (Global Network KPIs)")
print("and is referenced in the charger demand model in Notebook 3.")
"""),
]

# ─────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 3 — Optimization
# ─────────────────────────────────────────────────────────────────────────────
nb3_cells = [
("md", """# Notebook 3 — Charging Network Optimization
**IE × Iberdrola Datathon 2026**

## Objective
Propose the **minimum viable set** of charging station locations on Spain's interurban road network
such that no EV driver on any covered corridor faces a gap > 150 km between consecutive stations.

## Algorithm: Greedy Corridor Coverage
For each interurban route (autopista, autovía, carretera nacional):
1. Merge all road segments into a continuous corridor
2. Place stations every ≤150 km along the corridor
3. Skip placements within 30 km of an existing station (MIN_GAP constraint)
4. After all placements, deduplicate using spatial index — within 30 km, keep the higher-demand location

## Charger Count Model
`n_chargers = f(MITMA_traffic_demand × province_EV_penetration × road_category_multiplier)`

- **MITMA traffic demand:** real vehicle flows from Ministry of Transport Big Data study
- **Province EV penetration:** DGT registration data 2023–2024, normalised by national median
- **Road category multiplier:** Autopista 1.5×, Autovía 1.2×, Carretera Nacional 1.0×
- **Output range:** 2–12 chargers per station, at 150 kW each (fixed by competition rules)

## Key Assumptions
| Parameter | Value | Justification |
|---|---|---|
| EV average range | 350 km | Conservative 2027 midpoint (EU fleet average ~400 km, safety buffer applied) |
| Max inter-station gap | 150 km | 350 km × 43% safety buffer — ensures 2 full charges available per tank |
| Min inter-station gap | 30 km | Avoids over-clustering at urban highway entrances |
| Charger power | 150 kW | Fixed by competition rules (non-negotiable) |
| Chargers per station | 2–12 | Demand-weighted, justified by traffic volume |
"""),
("code", """import os
os.chdir("C:/Users/LEGION/Desktop/MASTERS/Datathon")

# Run the full optimization pipeline
exec(open("notebooks/03_optimization.py").read())
"""),

("md", """## Results Validation
"""),
("code", """import pandas as pd
file2 = pd.read_csv("outputs/File 2.csv")
print(f"Total proposed stations: {len(file2):,}")
print(f"\\nGrid status breakdown:")
print(file2["grid_status"].value_counts().to_string())
print(f"\\nCharger distribution:")
print(file2["n_chargers_proposed"].value_counts().sort_index().to_string())
print(f"\\nTotal chargers: {file2['n_chargers_proposed'].sum():,}")
print(f"Total capacity: {file2['n_chargers_proposed'].sum() * 150:,} kW")
print(f"\\nTop routes by station count:")
print(file2["route_segment"].value_counts().head(10).to_string())
print(f"\\nFile 2 preview:")
print(file2.head(10).to_string(index=False))
"""),
]

# ─────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 4 — Grid Analysis
# ─────────────────────────────────────────────────────────────────────────────
nb4_cells = [
("md", """# Notebook 4 — Grid Viability Analysis
**IE × Iberdrola Datathon 2026**

## Objective
Identify **friction points** — locations where EV charging demand exceeds local grid capacity —
by performing a spatial join between proposed stations and electricity substation data.

## Methodology
For each proposed station:
1. Find the **nearest electricity substation** (i-DE, Endesa, or Viesgo) using spatial index
2. Estimate substation capacity: use reported `capacity_mw` if available; otherwise estimate from `voltage_kv`
3. Compute utilisation ratio: `demand_kw / estimated_capacity_kw`
4. Classify `grid_status` using documented thresholds

## Grid Status Thresholds
| Status | Threshold | Justification |
|---|---|---|
| **Sufficient** | demand < 20% of capacity | Standard Spanish distributor planning reserve (i-DE grid planning norms) |
| **Moderate** | 20% ≤ demand < 60% | Monitoring zone — reinforcement may be needed before 2027 |
| **Congested** | demand ≥ 60% | i-DE congestion flag threshold; grid reinforcement is mandatory |

## Capacity Estimation (where reported capacity = 0)
| Voltage | Estimated Capacity | Source |
|---|---|---|
| 132 kV | 120 MW | AT transmission level, REE standard |
| 110 kV | 80 MW | AT near-transmission |
| 66 kV | 40 MW | Standard subtransmission |
| 45 kV | 20 MW | Distribution HV |
| 30 kV | 10 MW | Distribution MV |
| ≤25 kV | 1.5–5 MW | MT distribution level |
"""),
("code", """import os
os.chdir("C:/Users/LEGION/Desktop/MASTERS/Datathon")
exec(open("notebooks/04_grid_analysis.py").read())
"""),

("md", """## Friction Points Analysis
"""),
("code", """import pandas as pd
file3 = pd.read_csv("outputs/File 3.csv")
print(f"Total friction points: {len(file3)}")
print(f"\\nBy grid status:")
print(file3["grid_status"].value_counts().to_string())
print(f"\\nBy distributor network:")
print(file3["distributor_network"].value_counts().to_string())
print(f"\\nDemand at friction points (kW):")
print(file3["estimated_demand_kw"].describe().round(1).to_string())
print(f"\\nFriction points — full table:")
print(file3.to_string(index=False))
"""),

("md", """## Strategic Interpretation
- **Viesgo territory (northern Spain)** shows the highest friction rate relative to its network size —
  its 97 substations (vs. i-DE's 1,061) serve major Atlantic corridor routes (A-8, A-6) with limited spare capacity.
- **Endesa territory (south/east)** has friction concentrated around high-demand Mediterranean routes (A-7, A-4 south).
- **i-DE territory** (central Spain) absorbs charging demand well — its larger substation network
  and higher average voltage levels provide more headroom.

**Recommendation:** Phase 1 deployment should prioritise Sufficient and Moderate locations to
generate immediate revenue while Viesgo/Endesa grid reinforcement is planned.
"""),
]

# ─────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 5 — Output Generation & Validation
# ─────────────────────────────────────────────────────────────────────────────
nb5_cells = [
("md", """# Notebook 5 — Output Generation & Validation
**IE × Iberdrola Datathon 2026**

This notebook assembles the three mandatory output files and validates them
against the competition schema before submission.

## Output Files
| File | Contents | Rows |
|---|---|---|
| `File 1.csv` | Global Network KPIs (single row) | 1 |
| `File 2.csv` | Proposed charging station locations | 390 |
| `File 3.csv` | Grid friction points (Moderate + Congested only) | 30 |
"""),
("code", """import os
os.chdir("C:/Users/LEGION/Desktop/MASTERS/Datathon")
exec(open("notebooks/05_generate_outputs.py").read())
"""),

("md", """## Final File Verification
"""),
("code", """import pandas as pd

file1 = pd.read_csv("outputs/File 1.csv")
file2 = pd.read_csv("outputs/File 2.csv")
file3 = pd.read_csv("outputs/File 3.csv")

print("FILE 1 — Global Network KPIs:")
print(file1.T.rename(columns={0:"value"}).to_string())

print(f"\\nFILE 2 — Proposed Stations ({len(file2)} rows):")
print(f"  Schema: {list(file2.columns)}")
print(f"  Dtypes:\\n{file2.dtypes.to_string()}")
print(f"\\n  First 5 rows:")
print(file2.head().to_string(index=False))

print(f"\\nFILE 3 — Friction Points ({len(file3)} rows):")
print(f"  Schema: {list(file3.columns)}")
print(file3.to_string(index=False))
"""),
]

# ─────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 6 — BI Visualization
# ─────────────────────────────────────────────────────────────────────────────
nb6_cells = [
("md", """# Notebook 6 — BI Visualization
**IE × Iberdrola Datathon 2026**

Generates a self-contained interactive HTML map using Folium showing:
- All proposed charging stations (colour-coded: green=Sufficient, orange=Moderate, red=Congested)
- Friction points with double-ring markers
- Existing baseline chargers (grey, togglable)
- Layer controls, fullscreen, minimap, and rich popups per station

**Output:** `visualizations/iberdrola_ev_network_map.html` — opens directly in any browser,
no software installation, no login, no internet required for data (tile basemap uses CDN).

**Required visualization elements (per competition spec):**
- Geolocation of all stations ✓
- Route segment per station ✓
- Number of proposed chargers per station ✓
- Grid status colour-coding (Green/Yellow/Red) ✓
"""),
("code", """import os
os.chdir("C:/Users/LEGION/Desktop/MASTERS/Datathon")
exec(open("notebooks/06_visualization.py").read())
"""),

("md", """## Map Summary
"""),
("code", """import os
import pandas as pd

size_mb = os.path.getsize("visualizations/iberdrola_ev_network_map.html") / 1e6
file2 = pd.read_csv("outputs/File 2.csv")
file3 = pd.read_csv("outputs/File 3.csv")

print(f"Map file size: {size_mb:.1f} MB")
print(f"\\nStations on map: {len(file2):,}")
print(f"  Green  (Sufficient): {(file2.grid_status=='Sufficient').sum()}")
print(f"  Orange (Moderate):   {(file2.grid_status=='Moderate').sum()}")
print(f"  Red    (Congested):  {(file2.grid_status=='Congested').sum()}")
print(f"\\nFriction points: {len(file3)}")
print(f"\\nMap saved to: visualizations/iberdrola_ev_network_map.html")
print("Open in any browser — no software installation required.")
"""),
]

# ─────────────────────────────────────────────────────────────────────────────
# BUILD AND EXECUTE ALL NOTEBOOKS
# ─────────────────────────────────────────────────────────────────────────────
notebooks = [
    ("01_data_ingestion.ipynb",      nb1_cells),
    ("02_ev_projection.ipynb",       nb2_cells),
    ("03_optimization.ipynb",        nb3_cells),
    ("04_grid_analysis.ipynb",       nb4_cells),
    ("05_outputs_validation.ipynb",  nb5_cells),
    ("06_visualization.ipynb",       nb6_cells),
]

print("Building and executing Colab notebooks...")
print("=" * 55)
results = {}
for fname, cells in notebooks:
    path = OUT_DIR / fname
    nb = make_notebook(cells)
    ok = save_and_execute(nb, path)
    results[fname] = "OK" if ok else "WARN"

print("\n" + "=" * 55)
print("RESULTS:")
for fname, status in results.items():
    print(f"  [{status}] notebooks/v1/{fname}")
print(f"\nAll notebooks saved to {OUT_DIR}")
