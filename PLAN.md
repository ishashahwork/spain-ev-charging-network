# Datathon Action Plan — IE × Iberdrola

## Target: 2027 EV charging network for Spain's interurban roads

---

## Phase 0 — Setup & Data Acquisition (Day 1)

### 0.1 Fork the mandatory GitHub repo
- Fork the datos.gob.es electrification repo
- Run Exercise 3 to get the 2027 EV fleet projection
- Record `total_ev_projected_2027` → this is your File 1 anchor

### 0.2 Download all datasets
Follow `DATA_SOURCES.md`. Save everything to `data/raw/`. Never modify raw files.

Priority order:
1. Ministry of Transport road network (shapefile)
2. National Access Point EV charging baseline (CSV)
3. i-DE capacity dataset
4. Endesa capacity CSV/XLSX
5. Viesgo data
6. DGT vehicle registrations

### 0.3 Create folder structure
```
data/raw/     ← all downloaded files
data/processed/
notebooks/
outputs/
visualizations/
report/
```

---

## Phase 1 — Data Ingestion & EDA (Day 1–2)

**Notebook:** `01_data_ingestion_eda.ipynb`

### 1.1 Road network
- Load Ministry of Transport shapefile
- Filter to: autopistas (AP-*), autovías (A-*), carreteras nacionales (N-*)
- Exclude urban sections
- Compute corridor statistics: length, ADT (average daily traffic)

### 1.2 Existing charging baseline
- Load National Access Point dataset
- Spatial join against interurban roads (buffer ~500m)
- Count `total_existing_stations_baseline` (File 1)
- Map coverage gaps per corridor

### 1.3 Grid capacity datasets
- Load i-DE, Endesa, Viesgo substation coordinates + available MW
- Merge into a single `substations.gpkg` with distributor label
- Define and document classification thresholds:
  - **Sufficient:** available capacity > X MW
  - **Moderate:** Y < available capacity ≤ X MW
  - **Congested:** available capacity ≤ Y MW
  - Justify thresholds using industry standards (e.g., a 150 kW fast charger with 10 outlets = 1.5 MW minimum)

### 1.4 DGT registrations
- Load provincial EV registration time series
- Compute EV penetration rate by province
- Use as geographic demand weight

---

## Phase 2 — EV Demand Projection (Day 2)

**Notebook:** `02_ev_demand_projection.ipynb`

### 2.1 Use datos.gob.es Exercise 3 output
- Import 2027 national EV fleet projection (`total_ev_projected_2027`)
- Disaggregate nationally projected growth to provinces using DGT registration weights
- Compute province-level EV fleet in 2027

### 2.2 Translate to charging demand
- Assume average EV range: ~350 km (document assumption + source, e.g., ACEA 2024)
- Assume charging frequency on long trips: 1 stop per ~300 km
- Estimate daily charging events per route segment using traffic data × EV share
- Output: demand score per road segment (km-basis)

---

## Phase 3 — Charging Network Optimization (Day 2–3)

**Notebook:** `03_network_optimization.ipynb`

### 3.1 Station spacing logic
- Max inter-station distance = EV range × safety factor (e.g., 350 km × 0.7 = 245 km)
- Aim for stations every ~100–150 km on high-traffic corridors (justify with range anxiety studies)
- Use a greedy set-cover or p-median approach to minimize station count

### 3.2 Candidate site generation
- Sample candidate points along each road at regular intervals (e.g., every 10 km)
- Score each candidate by: traffic demand, proximity to existing services (rest areas), distance to nearest substation

### 3.3 Grid viability assignment
- For each proposed station, find nearest substation (spatial join within reasonable buffer)
- Assign `grid_status` based on documented thresholds
- Calculate `estimated_demand_kw = n_chargers_proposed × 150`

### 3.4 Assign number of chargers per station
- Proportional to local daily demand estimate
- Minimum: 2 chargers; document reasoning
- Scale up on major corridors (AP-7, A-1, A-4, etc.)

### 3.5 Output: File 2
Generate `File 2.csv` with all required fields, sequential `IBE_XXX` IDs.

---

## Phase 4 — Grid Friction Analysis (Day 3)

**Notebook:** `04_grid_friction_analysis.ipynb`

### 4.1 Identify friction points
- Filter File 2 to rows where `grid_status` IN (`Moderate`, `Congested`)
- These become File 3

### 4.2 Generate File 3
- Map `distributor_network` from the substation data (i-DE / Endesa / Viesgo)
- Compute `estimated_demand_kw = n_chargers_proposed × 150`
- Assign sequential `FRIC_XXX` IDs

### 4.3 Spatial analysis of bottlenecks
- Visualize friction zones on Spain map
- Identify patterns: are they concentrated in specific regions? Specific distributors?
- This directly feeds the strategic narrative

---

## Phase 5 — Output Generation (Day 3)

**Notebook:** `05_output_generation.ipynb`

### 5.1 File 1 — KPIs Scorecard
```python
{
  "total_proposed_stations": len(file2),
  "total_existing_stations_baseline": <from Phase 1.2>,
  "total_friction_points": len(file3),
  "total_ev_projected_2027": <from Exercise 3>
}
```

### 5.2 Validation checks (run before export)
- [ ] File 2: no missing fields, all lat/lon in Spain bounds, valid grid_status values
- [ ] File 3: no `Sufficient` rows, all IDs unique, demand = chargers × 150
- [ ] File 1: all four KPIs populated
- [ ] Print `.dtypes`, `.shape`, and `.head()` for each file in the notebook

---

## Phase 6 — BI Visualization (Day 3–4)

**Notebook:** `06_visualization.ipynb`  
**Output:** `visualizations/charging_network_map.html`

### Requirements (minimum)
- Self-contained HTML file (use `folium` with `embed_links=True` or `plotly` with `include_plotlyjs='cdn'` — **wait**, must work offline → use `include_plotlyjs=True`)
- Color-coded by `grid_status`: Green=Sufficient, Yellow=Moderate, Red=Congested
- Popup on click: `location_id`, `route_segment`, `n_chargers_proposed`, `grid_status`

### Enhancements (differentiators)
- Layer toggle: proposed stations / existing baseline / friction points
- Heatmap overlay of projected EV demand by corridor
- Substation capacity layer
- Sidebar KPI panel (File 1 stats)

---

## Phase 7 — Analytical Report (Day 4)

**File:** `report/Analytical_Report.pdf` (3–5 pages)

### Structure
1. **Executive Summary** — problem, approach, key findings (1 paragraph)
2. **Methodology** — road filtering, EV demand model, optimization algorithm, grid viability matching
3. **Assumptions & Justifications** — table format: assumption / value / source / reasoning
4. **Key Results** — File 1 KPIs, map highlights, friction zones
5. **Strategic Roadmap for Iberdrola** — phased deployment 2025→2027, priority corridors, grid reinforcement recommendations
6. **Limitations & Future Work**
7. **References** — all data sources with URLs and access dates

---

## Phase 8 — Final Presentation (Day 4–5)

**File:** `report/Final_Presentation.pdf` (max 5 min)

### Slide structure (suggested 8–10 slides)
1. Problem framing — range anxiety, why interurban matters
2. Our approach — data sources + methodology in one visual
3. 2027 EV forecast — datos.gob.es output, geographic breakdown
4. Proposed network — map, key stats from File 1
5. Grid friction analysis — friction points map, top bottlenecks
6. Strategic roadmap — phased rollout, priority corridors
7. Business case for Iberdrola — investment vs. demand coverage
8. Conclusion + call to action

---

## Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Viesgo data hard to download (web map) | Use CNMC territorial maps as proxy; document assumption |
| Road network shapefile too large | Filter to primary roads only (A-*, AP-*, N-*) early |
| Substation spatial matching too sparse | Expand search radius progressively (5 km → 20 km → 50 km) |
| datos.gob.es repo output format unclear | Run all 3 exercises; use exercise 3 projection table |
| Colab outputs not visible | Run `display(df.head())` + `print(df.dtypes)` after every output file |

---

## Scoring Optimization Tips

- **T1 (Assumptions):** Every assumption needs: value + industry source + justification. Put in a table.
- **T4 (Output compliance):** Run a validation script at the end that asserts field names, dtypes, and File 3 has no `Sufficient` rows.
- **B4 (BI Viz):** Use `folium` with all data embedded → single `.html` file, works offline.
- **B1 (Integration):** The report must explicitly link each technical output to a strategic recommendation.
- **Differentiator:** Add EU AFIR regulation spacing requirements as a constraint (mandatory chargers every 60 km on TEN-T core network by 2025, every 100 km by 2030 — cite regulation EU 2023/1804).
