# Hybrid EV Charging Network — Pipeline Methodology Report

**IE / Iberdrola Sustainability Datathon 2026**
**Team approach: v2 — Hybrid Coverage + Demand Model**

---

## 1. Executive Summary

This pipeline proposes **603 new interurban fast-charging stations** across Spain's motorway and national road network for a **2027 operational scenario**. The methodology is a **hybrid model** that combines two complementary layers:

1. **Coverage layer** — guarantees no corridor gap exceeds 60 km between fast chargers, eliminating range anxiety.
2. **Demand-reinforcement layer** — identifies segments where projected EV traffic outstrips existing charging supply and places additional capacity.

These two candidate pools are merged, sized according to local demand, tested against the electrical grid, and phased into a three-stage deployment roadmap.

**Key results:**

| Metric | Value |
|---|---|
| Proposed stations | 603 |
| Total 150 kW chargers | 4,175 |
| Total proposed capacity | 626,250 kW |
| Existing interurban baseline | 7,106 stations |
| Friction points (grid-constrained) | 22 |
| Projected EVs in Spain by 2027 | 659,323 |

---

## 2. Design Philosophy

The model avoids two common failure modes:

- **Pure geometry models** place stations at fixed intervals (e.g., every 50 km) regardless of demand, producing stations in low-traffic corridors while ignoring high-traffic bottlenecks.
- **Pure demand models** cluster stations near high-traffic nodes but can leave physical coverage gaps on secondary corridors.

Our hybrid approach first ensures geometric coverage (no driver should ever be stranded), then reinforces with demand-based stations where traffic justifies additional capacity. This two-layer design is both **defensible** (every station has an explicit justification) and **practical** (it maps directly to Iberdrola's phased deployment logic).

---

## 3. Data Inputs

All data was pre-processed and validated in a separate ingestion pipeline. The optimization pipeline consumes the following processed datasets:

| Dataset | Source | Records | Key fields |
|---|---|---|---|
| Road network | MITMA official interurban network | 224,839 micro-segments across 707 routes (62,982 km) | `route_segment`, `road_category`, `avg_total` (IMD traffic), `demand_score` |
| Existing chargers | National Access Point (DGT DATEX2) | 11,567 stations | `latitude`, `longitude`, `max_power_kw`, `total_power_kw` |
| Grid substations | i-DE + Endesa + Viesgo (merged, deduplicated) | 2,116 substations | `capacity_mw`, `voltage_kv`, `distributor_network` |
| EV projection | SARIMA model on datos.gob.es registration data | 659,323 projected EVs | Mandatory fork output |
| Amenities | OpenStreetMap extract (PBF) | 111,571 POIs across 5 categories | fuel, service areas, restaurants, supermarkets, hotels |

---

## 4. Pipeline Architecture

The pipeline consists of **6 sequential steps**, each producing intermediate geospatial files that feed the next:

```
s01_segment_roads.py     Road segmentation (~20 km units)
        |
s02_coverage_layer.py    Snap existing chargers, find gaps, generate coverage candidates
        |
s03_demand_and_supply.py Demand index + supply model + gap analysis + demand candidates
        |
s04_merge_and_snap.py    Merge pools, amenity snapping, station sizing
        |
s05_grid_feasibility.py  Grid matching, adaptive sizing loop, friction points
        |
s06_prioritize_and_output.py  Priority scoring, phasing, File 1/2/3, BI map
```

All parameters are centralized in `config.py` for easy sensitivity testing.

---

## 5. Step-by-Step Methodology

### Step 1 — Road Segmentation

**Purpose:** Convert 224,839 MITMA micro-segments (avg 0.28 km) into manageable analytical units.

**Method:**
1. For each of the 707 routes, micro-segments are sorted spatially along their principal axis (using centroid coordinates and principal component direction).
2. Consecutive micro-segments are batched into groups that sum to approximately **20 km**.
3. Trailing short segments (<10 km) are merged into the preceding segment to avoid tiny fragments.
4. Traffic metrics (`avg_total`, `demand_score`) are aggregated as **length-weighted averages** across the micro-segments in each batch.

**Corridor classification** is assigned per route:
- **Primary** (15 strategic corridors): A-1, A-2, A-3, A-4, A-5, A-6, A-7, A-8, A-23, A-52, A-62, A-66, A-92, AP-7N, AP-68
- **Standard**: other Autopistas and Autovias
- **Secondary**: Carreteras Nacionales

**Result:** 3,281 analytical segments (avg 19.2 km, median 20.3 km) covering 62,943 km.

| Corridor class | Segments | Total km |
|---|---|---|
| Primary | 999 | 20,769 |
| Standard | 1,153 | 20,379 |
| Secondary | 1,129 | 21,795 |

---

### Step 2 — Coverage Layer

**Purpose:** Guarantee that no interurban corridor has a gap longer than 60 km between fast chargers.

**Method:**

1. **Filter existing stations to fast chargers only** (max_power_kw >= 50 kW). Slow urban chargers (22 kW Type 2) do not provide meaningful interurban coverage. This reduces the baseline from 11,567 to 5,169 relevant stations.

2. **Snap to corridors:** Each fast charger is matched to its nearest road segment within a 5 km buffer. Result: **3,454 fast chargers** mapped to the road network.

3. **Gap analysis:** For each route (restricted to routes longer than 30 km = 217 routes), existing stations are ordered by their along-road km position. Gaps between consecutive stations — including gaps from the route start/end to the nearest station — are measured.

4. **Candidate placement:** Wherever a gap exceeds the **60 km threshold**, the minimum number of new candidates is placed to bring spacing down to the **55 km target**. Candidates are distributed evenly within each gap (not anchored at corridor endpoints).

**Key parameters:**

| Parameter | Value | Justification |
|---|---|---|
| Fast-charge threshold | 50 kW | Below this, charging time is too long for interurban use |
| Snap distance | 5 km | Captures stations near motorway exits |
| Max allowed gap | 60 km | Conservative: ensures a 300 km range EV always has 5x margin |
| Target spacing | 55 km | Places stations at comfortable intervals within gaps |

**Result:** 567 coverage candidates generated. Gap distribution:

| Gap statistic | Value |
|---|---|
| Mean gap | 48.8 km |
| Median gap | 21.8 km |
| Max gap | 586 km |
| Gaps > 60 km | 319 |
| Gaps > 150 km | 71 |

Routes with most coverage candidates: A-66 (26), A-23 (20), A-8 (19), A-2 (18), A-4 (18).

---

### Step 3 — Demand Model, Existing Supply, and Gap Analysis

**Purpose:** Identify segments where projected EV traffic demand exceeds existing charging supply.

#### 3a. Demand Index

For each of the 3,281 segments:

```
DemandIndex = Traffic_IMD x EV_share_2027 x charging_need_factor x corridor_multiplier
```

| Parameter | Value | Justification |
|---|---|---|
| `Traffic_IMD` | Per-segment (MITMA avg_total) | Official daily traffic intensity (vehicles/day) |
| `EV_share_2027` | 2.66% | 659,323 projected EVs / 24.8M total fleet (DGT 2024) |
| `charging_need_factor` | 0.15 (15%) | Fraction of interurban EV traffic needing a mid-route fast charge on any given day. Most trips are <300 km; ~15% of long-distance trips require a stop. |
| `corridor_multiplier` | Primary: 1.15, Standard: 1.00, Secondary: 0.90 | Reflects strategic importance of major corridors |

**Result:** Demand index ranges from 0.00 to 361.56 (mean 42.78), representing estimated daily EVs requiring a charge at each 20 km segment.

#### 3b. Existing Supply Model

All 11,567 baseline stations (not just fast chargers) are mapped to their nearest road segment within 5 km. For each station:
- If `total_power_kw` is available and > 0, use that value.
- Otherwise, apply the conservative default: **2 chargers x 50 kW = 100 kW per station**.

**Result:** 7,109 stations mapped to corridors. 1,410 segments (43%) have existing supply.

#### 3c. Gap Calculation

The demand index is converted to kW-equivalent for direct comparison with supply:

```
demand_kw_equiv = (DemandIndex / 48) x 150
```

Where 48 = estimated charging sessions per 150 kW charger per day (15-min average session over 12 peak hours).

```
Gap_kw = demand_kw_equiv - existing_supply_kw
```

- Segments with Gap > 0: **2,158 out of 3,281** (66% have unmet demand)
- Segments with Gap <= 0: existing supply roughly satisfies projected need

#### 3d. Demand-Reinforcement Candidates

1. Identify **high-gap segments**: top 25% of positive-gap segments (threshold: 164 kW). Result: 540 segments.
2. **Cluster** adjacent high-gap segments on the same route (segments within 40 km of each other are grouped).
3. Place one candidate at each cluster centroid.

**Result:** 150 demand-reinforcement candidates. Top routes by cluster demand: A-3, AP-7N, A-5, A-8, A-7.

---

### Step 4 — Candidate Merging, Amenity Snapping, and Station Sizing

**Purpose:** Combine coverage and demand candidates into one unified set, improve siting with amenity proximity, and assign initial charger counts.

#### 4a. Merge and Deduplication

Starting pool: 567 coverage + 150 demand = **717 candidates**.

Coverage-aware deduplication within 5 km:
- Coverage candidates are **protected** — they cannot be removed (removing them re-creates a gap).
- When a demand candidate falls within 5 km of a coverage candidate, the demand candidate is absorbed and the coverage candidate is reclassified as `coverage+demand`.
- Two demand candidates within 5 km are consolidated (keep the higher-gap one).

**Result after dedup:** 603 candidates.

| Type | Count |
|---|---|
| Coverage only | 458 |
| Demand only | 79 |
| Coverage + Demand | 66 |

#### 4b. Amenity Scoring and Snapping

Each candidate is scored by counting nearby points of interest within a **2 km radius**, weighted by type:

| Amenity type | Weight | Rationale |
|---|---|---|
| Service areas | 3.0 | Purpose-built for road users |
| Fuel stations | 2.0 | Existing infrastructure, easy to co-locate |
| Restaurants | 1.0 | Enhances user experience |
| Supermarkets | 0.5 | Secondary convenience |
| Hotels | 0.5 | Secondary convenience |

Candidates with **zero amenity score** are nudged up to **3 km** toward the nearest amenity (if any), improving real-world siting without compromising corridor coverage.

**Result:** 79 candidates snapped to nearby amenities.

#### 4c. Station Sizing

Charger counts are assigned based on demand gap tier + traffic tier + corridor class:

| Demand gap (kW) | Traffic (IMD) | Base chargers |
|---|---|---|
| <= 50 | <= 5,000 | 4 |
| 50–200 | 5,000–15,000 | 6 |
| 200–500 | > 15,000 | 8–10 |
| > 500 | any | 10–12 |

Adjustments:
- Primary corridor bonus: +2 chargers (capped at 12)
- Coverage+demand dual candidates: minimum 8 chargers
- All chargers are **150 kW** (fixed by competition rules)
- Range: 4 (minimum viable) to 16 (maximum hub)

**Result:**

| Chargers | Stations |
|---|---|
| 4 | 198 |
| 6 | 138 |
| 8 | 130 |
| 10 | 58 |
| 12 | 76 |
| Other (5, 9) | 3 |
| **Total chargers** | **4,220** |

---

### Step 5 — Grid Feasibility and Adaptive Sizing

**Purpose:** Test each candidate against the electrical distribution grid and adjust sizing where necessary.

#### 5a. Capacity Estimation

Of 2,116 grid substations, only 229 have reported `capacity_mw`. For the remaining 1,887, capacity is estimated from voltage level using conservative planning factors:

| Voltage (kV) | Estimated capacity (MW) |
|---|---|
| 132 | 40.0 |
| 110 | 30.0 |
| 66 | 15.0 |
| 45 | 8.0 |
| 20 | 3.0 |
| 10 | 0.8 |

#### 5b. Grid Matching

Each candidate is matched to its **nearest substation** via spatial index. Average distance: 12.3 km.

**Distributor coverage of proposed stations:**

| Distributor | Stations |
|---|---|
| Endesa | 275 |
| i-DE | 271 |
| Viesgo | 57 |

#### 5c. Grid Load Ratio

```
grid_load_ratio = proposed_demand_kw / available_capacity_kw
```

Classification thresholds:

| Status | Ratio | Meaning |
|---|---|---|
| **Sufficient** | <= 0.40 | Viable with comfortable margin |
| **Moderate** | 0.40–0.70 | Viable but constrained |
| **Congested** | > 0.70 | Requires grid reinforcement |

#### 5d. Adaptive Sizing Loop (Critical)

The initial sizing from Step 4 is **not treated as final**. An adjustment loop runs:

- **Sufficient (571 stations):** Keep initial sizing — no change.
- **Moderate (13 initially):** Try reducing by 2 chargers. If the new ratio falls to Sufficient, apply the reduction. Otherwise, keep original and flag as constrained.
- **Congested (19 initially):** Iteratively reduce chargers (down to minimum of 4) until status improves. If no feasible sizing exists, mark as a **friction point** requiring grid reinforcement.

**Sizing actions taken:**

| Action | Stations |
|---|---|
| Kept (Sufficient) | 571 |
| Reduced to Sufficient | 10 |
| Reduced to Moderate | 9 |
| Kept as Moderate | 3 |
| Friction point (irreducible) | 10 |

**Final grid status after adjustment:**

| Status | Stations |
|---|---|
| Sufficient | 581 |
| Moderate | 12 |
| Congested | 10 |

Total chargers adjusted: 4,220 -> **4,175** (net reduction of 45 chargers).

#### 5e. Friction Points

22 locations where `grid_status` is Moderate or Congested are flagged as friction points. These are sites where:
- Mobility demand justifies charging infrastructure, but
- The electrical grid cannot easily support the proposed load.

**Friction by distributor:**

| Distributor | Friction points |
|---|---|
| Viesgo | 14 |
| Endesa | 7 |
| i-DE | 1 |

Viesgo's northern Spain network accounts for the majority of friction points, consistent with its smaller and more constrained distribution grid.

---

### Step 6 — Prioritization, Phasing, and Output Generation

#### 6a. Priority Score

Each candidate receives a composite score (0–1 scale):

```
PriorityScore = 0.45 x norm_gap + 0.30 x norm_traffic + 0.10 x norm_amenity - 0.15 x norm_grid_risk
```

| Component | Weight | Rationale |
|---|---|---|
| Demand gap | 0.45 | Dominant — unmet need drives deployment priority |
| Traffic | 0.30 | Higher traffic = more potential users |
| Amenity score | 0.10 | Better user experience, higher utilization |
| Grid risk penalty | -0.15 | Penalizes constrained sites |

All components are min-max normalized to [0, 1]. The final score is also rescaled to [0, 1].

**Result:** Mean priority score = 0.245, range 0.000–1.000.

#### 6b. Deployment Phasing

| Phase | Criteria | Stations |
|---|---|---|
| **Phase 1** | Priority >= 0.30 AND grid Sufficient | 159 |
| **Phase 2** | Priority >= 0.12 (or Moderate grid) | 374 |
| **Phase 3** | Low priority OR grid Congested | 70 |

**Phase vs. candidate type:**

| Phase | Coverage | Coverage+Demand | Demand |
|---|---|---|---|
| 1 | 67 | 29 | 63 |
| 2 | 325 | 34 | 15 |
| 3 | 66 | 3 | 1 |

**Interpretation:**
- **Phase 1** (159 stations): Immediate deployment on major corridors. Mix of high-demand sites and critical coverage gaps on primary routes. All have sufficient grid capacity.
- **Phase 2** (374 stations): Core network buildout. Predominantly coverage stations filling remaining gaps. Some grid-moderate sites included.
- **Phase 3** (70 stations): Deferred sites requiring grid reinforcement, partnership agreements with Viesgo/Endesa, or lower-priority coverage on secondary corridors.

---

## 6. Output Files

### File 1 — Global KPIs (`File 1.csv`)

| Field | Value |
|---|---|
| `total_proposed_stations` | 603 |
| `total_existing_stations_baseline` | 7,106 |
| `total_friction_points` | 22 |
| `total_ev_projected_2027` | 659,323 |

### File 2 — Proposed Charging Locations (`File 2.csv`)

603 rows with fields: `location_id` (IBE_001–IBE_603), `latitude`, `longitude`, `route_segment`, `n_chargers_proposed`, `grid_status`.

### File 3 — Friction Points (`File 3.csv`)

22 rows with fields: `bottleneck_id` (FRIC_001–FRIC_022), `latitude`, `longitude`, `route_segment`, `distributor_network`, `estimated_demand_kw`, `grid_status`.

### Extended Dataset (`extended_candidates.csv`)

603 rows with all analytical fields: priority score, phase, candidate type, sizing action, grid load ratio, traffic, demand gap, amenity score, corridor class, and substation capacity.

### BI Visualization (`v2_ev_network_map.html`)

Self-contained interactive Folium map (3.2 MB) with three toggleable layers:
- Proposed stations (color-coded by grid status, sized by charger count)
- Friction points (warning markers)
- Existing baseline stations (clustered grey dots)

---

## 7. Core Assumptions Table

| Assumption | Value | Justification |
|---|---|---|
| EV fleet Spain 2027 | 659,323 | SARIMA forecast on datos.gob.es registration data (mandatory source) |
| Total vehicle fleet | 24.8M | DGT 2024 passenger car census |
| EV share 2027 | 2.66% | Projected EVs / total fleet |
| Charging need factor | 15% | Fraction of interurban EV trips needing a fast charge on a given day |
| Target corridor spacing | 55 km | Anti-range-anxiety: comfortable for 300+ km range EVs |
| Max allowed gap | 60 km | Hard coverage limit |
| Fast-charge threshold | 50 kW | Below this is not viable for interurban use |
| Existing station default supply | 100 kW (2 x 50 kW) | Conservative assumption when station-level data is missing |
| Charger standard | 150 kW | Fixed by competition rules |
| Min chargers per station | 4 | Minimum viable fast-charging site |
| Max chargers per station | 16 | Maximum hub (strong justification required) |
| Grid Sufficient threshold | ratio <= 0.40 | Planning margin of 60% headroom |
| Grid Moderate threshold | ratio 0.40–0.70 | Constrained but feasible |
| Grid Congested threshold | ratio > 0.70 | Requires reinforcement |
| Segment analysis unit | ~20 km | Balances granularity with computational tractability |
| Amenity search radius | 2 km | Captures walkable/adjacent amenities |
| Amenity snap distance | 3 km | Maximum relocation toward better siting |

---

## 8. Sensitivity Analysis Recommendations

The following parameters should be stress-tested:

| Parameter | Baseline | Test range | Impact |
|---|---|---|---|
| `charging_need_factor` | 0.15 | 0.10 – 0.25 | Directly scales demand; higher values increase station count and sizing |
| `MAX_GAP_ALLOWED_KM` | 60 km | 40 – 80 km | Tighter gaps increase coverage candidates dramatically |
| `FAST_CHARGE_THRESHOLD_KW` | 50 kW | 22 – 100 kW | Lower threshold fills more gaps with existing supply; higher threshold creates more gaps |
| `GRID_RATIO_SUFFICIENT` | 0.40 | 0.30 – 0.50 | Stricter threshold increases friction points |
| `corridor_multiplier` (primary) | 1.15 | 1.00 – 1.30 | Affects sizing on major corridors |
| `DEFAULT_SUPPLY_PER_STATION_KW` | 100 | 50 – 150 | Lower value increases gap; higher value reduces it |
| `TARGET_SPACING_KM` | 55 km | 40 – 60 km | Affects how many candidates are placed per gap |

---

## 9. Limitations and Flagged Assumptions

1. **Candidate siting is approximate.** Coordinates are interpolated along road geometry or snapped to the nearest amenity POI. Real siting requires land acquisition, permitting, and site surveys.

2. **Grid capacity is partially estimated.** Only 229 of 2,116 substations have reported capacity; the remainder use voltage-based heuristics. Actual grid connection feasibility requires distributor-specific studies.

3. **National EV share used uniformly.** Province-level EV penetration varies significantly (Barcelona 16.4% vs. rural provinces <1%). The model uses national average, letting traffic intensity carry the spatial variation. A province-weighted model could improve local accuracy but adds complexity.

4. **No explicit route-level traffic assignment.** The demand model uses MITMA segment-level IMD (daily intensity), not O-D traffic assignment. This is a practical choice under datathon time constraints.

5. **Competitor supply is included but treated conservatively.** All existing stations are counted as supply regardless of operator. In practice, Iberdrola would prioritize locations where its own network has gaps, even if competitors are present.

6. **Amenity data is static.** Based on a 2024 OSM extract. New service areas or fuel station closures would affect siting quality.

---

## 10. Reproducibility

The full pipeline runs from pre-processed data in approximately 5–10 minutes:

```bash
cd v2/
conda run -n datathon python run_pipeline.py
```

All intermediate files are saved to `v2/intermediate/` as GeoPackage files for inspection. Output CSVs are written to `outputs/v2/`. The interactive map is saved to `visualizations/v2_ev_network_map.html`.

Every parameter is defined in `config.py` — no magic numbers are embedded in pipeline scripts.
