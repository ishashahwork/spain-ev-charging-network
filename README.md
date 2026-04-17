# IE x Iberdrola Datathon — Spain Interurban EV Charging Network (2027)

## What This Project Does

This project designs an **optimal public EV charging network** for Spain's interurban road system (autopistas, autovias, carreteras nacionales) targeting a **2027 operational scenario**. It produces three deliverable CSV files, an interactive map, and all supporting analysis.

**Final outputs (already generated):**
- `outputs/File 1.csv` — 390 proposed stations, 2,828 existing baseline, 30 friction points, 659,323 projected EVs
- `outputs/File 2.csv` — 390 proposed charging station locations with grid status
- `outputs/File 3.csv` — 30 friction points where grid reinforcement is needed
- `visualizations/iberdrola_ev_network_map.html` — self-contained interactive map

---

## How to Run

```bash
# 1. Create conda environment
conda env create -f environment.yml
conda activate datathon

# 2. Run the pipeline in order (see Pipeline section below)
conda run -n datathon python notebooks/01a_download_ev_charging.py
# ... etc.
```

**Important:** Raw data files are not in the repo (too large). The download scripts (`01a`, `01b`, `01c`, `01d`, `01f`) fetch everything automatically. The `data/raw/parquets_procesados/` folder must be populated from the datos.gob.es GitHub fork (mandatory per competition rules).

---

## Pipeline Overview

The project runs as a sequence of Python scripts. Each script reads specific inputs and produces specific outputs. Here is the full execution order:

```
01a_download_ev_charging.py ──> ev_charging_raw.xml
01a_parse_ev_charging.py ──> ev_charging_baseline.csv (11,567 stations)
01b_download_road_network.py ──> interurban_roads.gpkg (OSMnx backup)
01c_download_grid_capacity.py ──> grid_ide_capacity.csv, grid_endesa_demand.csv
01c_parse_grid_ide.py ──> grid_ide_substations.csv
01c_download_endesa.py ──> grid_endesa_demand.csv
01c_merge_grid.py ──> grid_substations.csv (i-DE + Endesa merged)
01c_parse_viesgo.py ──> updates grid_substations.csv (adds Viesgo)
01c_deduplicate_grid.py ──> grid_substations_dedup.csv (2,116 unique nodes)
01d_download_mitma_rutas.py ──> MITMA shapefiles + traffic CSVs
01e_process_mitma_roads.py ──> interurban_roads_mitma.gpkg (official road network)
01f_dgt_ev_by_province.py ──> ev_share_by_province.csv (EV density per province)
02_ev_projection.py ──> ev_projection_results.json (659,323 EVs by 2027)
03_optimization.py ──> File 2.csv + proposed_stations.gpkg
03c_extract_amenities_pbf.py ──> amenity GeoJSON files (from OSM PBF)
03b_colocation_score.py ──> updated File 2.csv (with colocation scores)
04_grid_analysis.py ──> updated File 2.csv + File 3.csv (grid status)
05_generate_outputs.py ──> File 1.csv (KPIs) + schema validation
06_visualization.py ──> iberdrola_ev_network_map.html
```

---

## Step-by-Step Calculation Explanation

### Step 1a — EV Charging Baseline (existing stations)

**What:** Downloads and parses Spain's official National Access Point (NAP) dataset of existing EV charging stations.

**How:**
1. Downloads DATEX2v3 XML from DGT (`infocar.dgt.es`).
2. Parses each `energyInfrastructureSite` element extracting: latitude, longitude, number of connectors, max power (kW), connector types, operator.
3. Filters to Spain bounding box (lat 27-44, lon -10 to 5).

**Result:** 11,567 existing charging stations across Spain. This is used later (in `05_generate_outputs.py`) to compute the `total_existing_stations_baseline` KPI by spatially filtering to stations within 500m of interurban roads.

---

### Step 1b — Road Network (OSMnx backup)

**What:** Downloads Spain's motorway/trunk/primary road network from OpenStreetMap via OSMnx.

**How:**
1. Splits Spain into 4 bounding box regions (NW, NE, SW, SE) to avoid Overpass API timeout.
2. Queries OSM for `highway` types: `motorway`, `trunk`, `primary` (and their `_link` variants).
3. Classifies each edge: `AP-*` prefix = Autopista, `A-*` = Autovia, `N-*` = Carretera Nacional.
4. Merges all 4 regions, deduplicates by `osmid`, computes segment length in km.

**Note:** This is a backup. The primary road network comes from MITMA (step 1e), which has official traffic data attached.

---

### Step 1c — Grid Substations (i-DE + Endesa + Viesgo)

**What:** Collects electricity distribution substation locations and capacities from all three major Spanish distributors.

**How the data is parsed:**
1. **i-DE** (`grid_ide_capacity.csv`): CSV with UTM Zone 30N coordinates (EPSG:25830). Parsed with Spanish number format (`.` = thousands, `,` = decimal). Converted to WGS84 using pyproj.
2. **Endesa** (`grid_endesa_demand.csv`): Same format/processing as i-DE.
3. **Viesgo** (`viesgo/2026_04_01_R1005_demanda.csv`): Same UTM format, auto-detects column names via keyword matching.

**Deduplication** (`01c_deduplicate_grid.py`):
- Groups by exact (latitude, longitude) coordinates.
- For each unique location: keeps the max capacity_mw, max voltage_kv, and counts how many voltage levels exist at that point (`n_voltage_levels`).

**Result:** 2,116 unique substation nodes (i-DE: 1,061 / Endesa: 958 / Viesgo: 97).

**Critical data quirk:** 1,887 of the 2,116 substations report `capacity_mw = 0`. This is handled in step 04 by estimating capacity from voltage level.

---

### Step 1d + 1e — MITMA Official Road Network + Traffic Data

**What:** Downloads and processes the official Ministry of Transport (MITMA) road network with real traffic volume data.

**How:**
1. Loads `Geometria_tramos.shp` (452,478 road segments in EPSG:3042). Reprojects to WGS84.
2. Joins road names from `rt_tramo_val.csv` — each segment can have multiple road names, so the script picks the highest-priority interurban one (Autopista > Autovia > Carretera Nacional).
3. Filters to only segments with `AP-*`, `A-*`, or `N-*` codes.
4. Loads 4 sample traffic days from `informacion_tramo/*.csv.gz` and averages across them.
5. Computes a **demand_score** per segment:
   ```
   demand_score = 0.5 * avg_largo + 0.3 * avg_inter_provincial + 0.2 * avg_inter_ccaa
   ```
   Where:
   - `avg_largo` = average long-distance trips (most relevant for EV range anxiety)
   - `avg_inter_provincial` = inter-province trips (interurban corridor usage)
   - `avg_inter_ccaa` = inter-autonomous-community trips (long-distance indicator)

**Result:** Interurban road segments with traffic-weighted demand scores, used in the optimization step.

---

### Step 1f — Province-Level EV Penetration

**What:** Downloads DGT monthly vehicle registration microdata (2023-2024) and computes EV market share by province.

**How:**
1. Downloads 24 monthly ZIP files from DGT (2023-01 through 2024-12).
2. Each ZIP contains a fixed-width or semicolon-delimited text file. Filters to:
   - `COD_TIPO = 40` (passenger cars)
   - `COD_PROPULSION_ITV = 2` (electric)
   - `CLAVE_TRAMITE = 1` (new registration, not transfer)
3. Groups by province code (`CPRO`) and computes:
   ```
   ev_share = province_ev_count / national_ev_total
   ev_fleet_2027 = ev_share * 659,323
   ```

**Result:** `ev_share_by_province.csv` — used in step 03 to weight charger counts geographically. Provinces with higher EV adoption (Madrid, Barcelona, Valencia) get more chargers per station.

---

### Step 02 — EV Fleet Projection (2027)

**What:** Projects the total Spanish EV fleet size in 2027 using time series forecasting on official DGT registration data.

**How:**
1. Loads parquet files from `datos.gob.es` GitHub fork (mandatory data source per competition rules).
2. Filters to: passenger cars (`COD_TIPO=40`), firm registrations (`CLAVE_TRAMITE` in 1, 5, B), years 2015-2025.
3. Extracts electric vehicles (`COD_PROPULSION_ITV = Electrico`) and builds a monthly time series of new EV registrations.
4. Fits a **SARIMA model** using `pmdarima.auto_arima`:
   - Works on `log(registrations)` to stabilize variance.
   - Auto-selects order with ADF test, seasonal period m=12.
   - Forecasts 24 months ahead (all of 2026 + all of 2027).
5. Computes total:
   ```
   total_ev_projected_2027 = historical_ev_fleet + new_EVs_2026 + new_EVs_2027
   ```

**Result:** **659,323 EVs** projected for end of 2027. This is a locked KPI used in File 1.

---

### Step 03 — Station Placement Optimization

**What:** Places the minimum number of charging stations on interurban corridors such that no gap between consecutive stations exceeds 150 km.

**Key assumptions (all documented):**
| Parameter | Value | Justification |
|---|---|---|
| EV average range | 350 km | Conservative 2027 EU fleet midpoint |
| Max inter-station gap | 150 km | 350 km x 43% safety buffer |
| Min inter-station gap | 30 km | Avoid over-clustering near cities |
| Charger power | 150 kW | Fixed by competition rules |
| Chargers per station | 2-12 | Demand-weighted |

**Algorithm — Greedy Corridor Coverage:**

1. **Group road segments by `route_segment`** (e.g., all segments of the A-3).
2. **Merge geometries** for each route into a single LineString using `shapely.linemerge`.
3. **Walk along each route** placing a station every `MAX_GAP_KM` (150 km):
   - Start at km 0, place a station.
   - Advance 150 km, place another station.
   - If the remaining gap after the last station is > 30 km, place one more at the route end.
   - If a route is shorter than 30 km total, place one station at the midpoint.
4. **Assign charger counts** using a demand-weighted formula:
   ```
   norm = clip((demand_score - p10) / (p90 - p10), 0, 1)
   base = CHARGER_MIN + norm * (CHARGER_MAX - CHARGER_MIN)
   result = base * province_ev_penetration_factor * road_category_multiplier
   ```
   Where:
   - `demand_score` comes from MITMA traffic data (step 1e)
   - `province_ev_penetration_factor` = province EV share / median national share, clamped to [0.5, 2.0]
   - `road_category_multiplier`: Autopista = 1.5x, Autovia = 1.2x, Nacional = 1.0x
   - p10/p90 = 10th/90th percentile of demand_score across all road segments
5. **Deduplicate**: Stations closer than 30 km are merged using a spatial index (`rtree`). When two stations are too close, the one with higher `demand_score` is kept.

**Result:** 390 proposed stations across Spain's interurban network.

---

### Step 03b — Co-location Scoring + Station Nudging

**What:** Scores each station's proximity to useful amenities (service areas, fuel, supermarkets, hotels, restaurants) and nudges isolated stations toward the nearest amenity if possible.

**Scoring:**
| Amenity | Radius | Points |
|---|---|---|
| Highway service area | 1 km | +3 |
| Fuel station | 1 km | +2 |
| Supermarket | 1 km | +2 |
| Hotel | 2 km | +1 |
| Restaurant | 1 km | +1 |

**Nudging logic:**
- For stations with score = 0, find the nearest amenity within 5 km.
- Move the station to that amenity's location, **but only if** the move does not create a corridor gap smaller than 30 km with neighboring stations on the same route.

**Result:** Updated File 2.csv with `colocation_score`, `nearest_amenity`, and `nudged` columns.

---

### Step 03c — Amenity Extraction from OSM

**What:** Extracts the 5 amenity types from a Spain `.osm.pbf` file (OpenStreetMap data dump) so that co-location scoring works offline.

**Amenity types extracted:** fuel stations, highway service areas, supermarkets, hotels, restaurants.

---

### Step 04 — Grid Viability Analysis

**What:** For each proposed station, finds the nearest electricity substation and classifies whether the local grid can absorb the added EV charging demand.

**How:**

1. **Compute demand per station:**
   ```
   estimated_demand_kw = n_chargers_proposed * 150
   ```

2. **Estimate substation capacity** (since 89% of substations report 0 MW):
   Uses a voltage-to-capacity lookup table based on Spanish REE/distributor norms:
   | Voltage (kV) | Estimated Capacity (MW) |
   |---|---|
   | 132 | 120 |
   | 110 | 80 |
   | 66 | 40 |
   | 45 | 20 |
   | 30 | 10 |
   | <=25 | 5 |

   For substations with multiple voltage levels, capacity is scaled up by 30% per additional level.

3. **Spatial join:** Uses `geopandas.sjoin_nearest` in EPSG:3857 (metric) to find the nearest substation for each proposed station.

4. **Classify grid_status:**
   ```
   ratio = estimated_demand_kw / capacity_kw_estimated
   if ratio < 0.20:  "Sufficient"     (grid can absorb easily)
   if ratio < 0.60:  "Moderate"       (reinforcement may be needed)
   if ratio >= 0.60: "Congested"      (must reinforce)
   ```
   **Threshold justification:**
   - 20% = standard Spanish distributor planning reserve
   - 60% = congestion flag used by i-DE in their capacity maps

5. **Build File 3** (friction points): All stations with `Moderate` or `Congested` status, including the distributor name from the nearest substation.

**Result:** Updated File 2.csv (390 rows with grid_status), File 3.csv (30 friction points).

---

### Step 05 — Output Generation + Validation

**What:** Assembles File 1 (KPIs) and validates all three output files against the required schema.

**How File 1 KPIs are computed:**
- `total_proposed_stations` = row count of File 2 = **390**
- `total_existing_stations_baseline` = existing stations within 500m buffer of interurban roads = **2,828**
- `total_friction_points` = row count of File 3 = **30**
- `total_ev_projected_2027` = SARIMA output = **659,323**

**Validation checks:**
- File 1: 4 integer KPI fields present and correctly typed
- File 2: 6 required columns, valid lat/lon within Spain bounds, grid_status in {Sufficient, Moderate, Congested}
- File 3: 7 required columns, grid_status in {Moderate, Congested} only, distributor in {i-DE, Endesa, Viesgo}, `estimated_demand_kw = n_chargers * 150`

---

### Step 06 — Interactive Map Visualization

**What:** Generates a self-contained HTML map using Folium.

**Layers:**
1. **Existing Baseline** (grey dots) — up to 3,000 sampled from 11,567 stations
2. **Proposed Stations** — color-coded circles by grid_status:
   - Green = Sufficient, Orange = Moderate, Red = Congested
   - Circle radius proportional to charger count
   - Popup shows: location_id, route, chargers, capacity, grid_status, colocation score
3. **Friction Points** — double-ring markers (orange/red) with demand and distributor info

**Controls:** Layer switcher, fullscreen button, mini-map, legend with KPI summary.

---

## Project Structure

```
Datathon/
├── README.md                  <- this file
├── CLAUDE.md                  <- AI assistant instructions
├── .gitignore
├── environment.yml            <- conda environment (Python 3.11)
├── notebooks/
│   ├── 01a_*.py               <- EV charging baseline download + parse
│   ├── 01b_*.py               <- Road network download (OSMnx)
│   ├── 01c_*.py               <- Grid substation download + parse + merge + dedup
│   ├── 01d_*.py               <- MITMA road data download
│   ├── 01e_*.py               <- MITMA road processing + traffic demand
│   ├── 01f_*.py               <- Province EV penetration from DGT
│   ├── 02_ev_projection.py    <- SARIMA forecast -> 659,323 EVs
│   ├── 03_optimization.py     <- Greedy corridor coverage -> 390 stations
│   ├── 03b_colocation_score.py <- Amenity proximity scoring + nudging
│   ├── 03c_extract_amenities_pbf.py <- OSM amenity extraction
│   ├── 04_grid_analysis.py    <- Grid viability + friction points
│   ├── 05_generate_outputs.py <- File 1 assembly + schema validation
│   └── 06_visualization.py    <- Folium interactive map
├── data/
│   ├── raw/                   <- downloaded source data (not in git)
│   └── processed/             <- cleaned/merged datasets
├── outputs/
│   ├── File 1.csv             <- Global KPIs
│   ├── File 2.csv             <- 390 proposed stations
│   └── File 3.csv             <- 30 friction points
├── visualizations/
│   └── iberdrola_ev_network_map.html  <- self-contained interactive map
├── Sources/
│   └── IE-Iberdrola Datathon Marzo 2026.pdf
└── report/                    <- analytical report + presentation
```

---

## Key Numbers to Know

| Metric | Value |
|---|---|
| Projected EV fleet 2027 | 659,323 |
| Proposed charging stations | 390 |
| Existing baseline (interurban) | 2,828 |
| Grid friction points | 30 |
| Total chargers proposed | ~2,200 |
| Charger power (fixed) | 150 kW |
| Max inter-station gap | 150 km |
| Grid substations used | 2,116 (i-DE: 1,061 / Endesa: 958 / Viesgo: 97) |
| Grid status thresholds | Sufficient <20%, Moderate 20-60%, Congested >=60% |

---

## Data Sources

| Source | What | How obtained |
|---|---|---|
| datos.gob.es GitHub fork | EV registration parquets (2015-2025) | **Mandatory** — forked repo |
| NAP DGT | Existing EV charging stations (DATEX2 XML) | `01a_download_ev_charging.py` |
| MITMA | Official road network + traffic volumes | `01d_download_mitma_rutas.py` |
| i-DE (Iberdrola) | Grid substation capacity map | `01c_download_grid_capacity.py` |
| Endesa / e-distribucion | Grid capacity nodes | `01c_download_endesa.py` |
| Viesgo | Grid capacity (northern Spain) | Manual download from interactive map |
| DGT microdata | Vehicle registrations by province (2023-2024) | `01f_dgt_ev_by_province.py` |
| OpenStreetMap (OSMnx) | Road network backup + amenity locations | `01b_download_road_network.py` / `03c_extract_amenities_pbf.py` |
