# IE Sustainability Datathon — Iberdrola | Claude Setup

> Historical challenge notes. See [README.md](README.md) for the current v2 entry point and verified publication status.

## Project Overview

**Challenge:** Design an optimal public EV charging network for Spain's interurban road network (autopistas, autovías, carreteras nacionales) for a **2027 operational scenario**.

**Organizer:** IE Business School × Iberdrola
**Working directory:** repository root (use `v2/run_pipeline.py` for the current pipeline)
**Conda environment:** `datathon` (Python 3.11)
**Run Python via:** `conda run -n datathon python <script.py>`
**Code must be delivered in:** Google Colab notebooks

---

## The Three Objectives

1. **Charging Network Optimization** — Propose minimum viable set of charging station locations along interurban routes. Minimize station count while guaranteeing coverage (no range anxiety).
2. **Grid Viability Analysis** — Cross mobility demand with distributor capacity maps (i-DE, Endesa, Viesgo) to find friction points where grid reinforcement is required.
3. **Strategy & Value Proposition** — Formulate a phased deployment roadmap for Iberdrola to act upon.

---

## Mandatory Rules (Disqualification Risk)

- All proposed stations must be on **interurban roads only** (autopistas, autovías, carreteras nacionales). Urban sections are excluded.
- **EV projections for 2027 must come from the forked datos.gob.es GitHub repo** (exercise 3). This is non-negotiable.
- **Standard charger power = 150 kW** (fixed for all teams). `estimated_demand_kw = n_chargers_proposed × 150`
- `grid_status` values: `Sufficient`, `Moderate`, `Congested` — thresholds must be justified in the report.
- **File 3** may only contain rows where `grid_status` is `Moderate` or `Congested`.
- All code cells must be executed with visible outputs in Colab.
- BI Visualization must be **self-contained** (no login, no software install, no internet required).

---

## Required Output Files

### File 1 — Global Network KPIs (`File 1.csv`)
| Field | Type | Source |
|---|---|---|
| `total_proposed_stations` | Integer | Row count of File 2 |
| `total_existing_stations_baseline` | Integer | National Access Point dataset, filtered to interurban |
| `total_friction_points` | Integer | Row count of File 3 |
| `total_ev_projected_2027` | Integer | datos.gob.es GitHub fork output |

### File 2 — Proposed Charging Locations (`File 2.csv`)
| Field | Type | Description |
|---|---|---|
| `location_id` | String | Sequential ID (e.g., IBE_001) |
| `latitude` | Float | WGS84 decimal degrees |
| `longitude` | Float | WGS84 decimal degrees |
| `route_segment` | String | Official road code (e.g., A-3, AP-7, N-2) |
| `n_chargers_proposed` | Integer | Justified by local projected demand |
| `grid_status` | Categorical | Sufficient / Moderate / Congested |

### File 3 — Friction Points (`File 3.csv`)
| Field | Type | Description |
|---|---|---|
| `bottleneck_id` | String | Sequential ID (e.g., FRIC_001) |
| `latitude` | Float | WGS84 decimal degrees |
| `longitude` | Float | WGS84 decimal degrees |
| `route_segment` | String | Official road code |
| `distributor_network` | String | i-DE / Endesa / Viesgo |
| `estimated_demand_kw` | Float | n_chargers_proposed × 150 |
| `grid_status` | Categorical | Moderate or Congested only |

---

## Data Sources

### Mandatory
| # | Name | Type | Notes |
|---|---|---|---|
| 1 | Ministry of Transport road network | Geospatial | Interurban road backbone |
| 2 | National Access Point — EV charging points | CSV | Existing charger baseline |
| 3 | datos.gob.es GitHub fork (exercise 3) | Python/model | **Must fork and use output for 2027 EV projection** |

### Additional (Grid Capacity)
| # | Distributor | Dataset | Coverage |
|---|---|---|---|
| 4 | Iberdrola / i-DE | Consumption capacity map | Most of Spain |
| 5 | Endesa / e-distribución | Network capacity nodes (CSV/XLSX) | South & east Spain |
| 6 | Viesgo | Interactive grid map | Northern Spain |

### Supporting
| # | Name | Notes |
|---|---|---|
| 7 | DGT vehicle registrations | Historical EV adoption by province |
| 8 | Local open data portals (e.g., datos.gob.es/Vigo) | Granular local charger data |

---

## Deliverables Checklist

- [ ] **Deliverable 1:** Google Colab notebook(s) — commented, all cells executed, outputs visible
- [ ] **Deliverable 2:** Three CSV files (File 1, File 2, File 3) in exact format
- [ ] **Deliverable 3:** BI Visualization — self-contained map, color-coded by grid_status
- [ ] **Deliverable 4:** Analytical Report (3–5 pages) — methodology, assumptions, citations
- [ ] **Deliverable 5:** Final Presentation (max 5 min pitch)

---

## Evaluation Weights

| Component | Weight |
|---|---|
| Technical + BI Visualization | 50% |
| Analytical Report + Presentation | 50% |

### Technical sub-criteria
- T1: Problem understanding & assumptions documentation
- T2: Data exploration & source quality
- T3: Methodology (optimization + grid viability)
- T4: Output dataset compliance
- T5: Code quality & reproducibility
- B4: BI Visualization

### Report/Presentation sub-criteria
- B1: Integration of technical & strategic analysis
- B2: Coherence & feasibility of roadmap
- B3: Strategic relevance for Iberdrola
- B5: Clarity & persuasiveness of pitch
- B6: Formal compliance & citation

---

## Key Assumptions to Document

- EV average autonomy (e.g., 300–400 km) → station spacing logic
- Minimum/maximum inter-station distance on each corridor
- Grid capacity thresholds for Sufficient / Moderate / Congested classification
- Spatial matching methodology (how nearest substation is assigned to each proposed station)
- Demand weighting per route (traffic volume × EV penetration rate)

---

## Project Folder Structure

```
Datathon/
├── CLAUDE.md               ← this file
├── environment.yml         ← conda environment
├── Sources/
│   └── IE-Iberdrola Datathon Marzo 2026.pdf
├── data/
│   ├── raw/                ← downloaded source data (never modify)
│   └── processed/          ← cleaned/merged datasets
├── notebooks/              ← Google Colab .ipynb files
├── outputs/
│   ├── File 1.csv
│   ├── File 2.csv
│   └── File 3.csv
├── visualizations/         ← BI map (self-contained HTML or similar)
└── report/                 ← Analytical Report and Presentation
```

---

## Style & Collaboration Notes

- Keep code modular: one notebook per major step (data ingestion, EV projection, optimization, grid analysis, output generation).
- All assumptions must be commented inline AND documented in the report.
- When using geospatial joins, use WGS84 (EPSG:4326) consistently.
- Prefer `geopandas` for spatial operations and `folium`/`plotly` for visualization.
- Cite every external dataset with URL and access date in the report.
