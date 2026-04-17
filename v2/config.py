"""
Hybrid EV Charging Network v2 — Configuration & Assumptions
============================================================
All parameters, thresholds, and assumptions in one place.
Every value is justified and documented.
"""

# ─────────────────────────────────────────────────────────────
# PATHS — reuse data from the main pipeline
# ─────────────────────────────────────────────────────────────
ROADS_GPKG           = "../data/processed/interurban_roads_mitma.gpkg"
EV_BASELINE_CSV      = "../data/processed/ev_charging_baseline.csv"
GRID_SUBS_GPKG       = "../data/processed/grid_substations_dedup.gpkg"
EV_PROJECTION_JSON   = "../data/processed/ev_projection_results.json"
EV_SHARE_PROVINCE    = "../data/processed/ev_share_by_province.csv"
AMENITIES_DIR        = "../data/raw/amenities"

OUTPUT_DIR           = "../outputs/v2"
DATA_DIR             = "intermediate"   # local intermediate files

# ─────────────────────────────────────────────────────────────
# CRS
# ─────────────────────────────────────────────────────────────
CRS_WGS84  = "EPSG:4326"
CRS_METRIC = "EPSG:25830"  # ETRS89 / UTM zone 30N (Spain)

# ─────────────────────────────────────────────────────────────
# SECTION 2 — ROAD SEGMENTATION
# ─────────────────────────────────────────────────────────────
SEGMENT_LENGTH_KM    = 20    # target analytical segment length
SEGMENT_MIN_KM       = 10    # don't create segments shorter than this
SEGMENT_MAX_KM       = 30    # acceptable upper bound

# ─────────────────────────────────────────────────────────────
# SECTION 3 — COVERAGE LAYER
# ─────────────────────────────────────────────────────────────
COVERAGE_RADIUS_KM   = 30    # effective coverage per station along corridor
TARGET_SPACING_KM    = 55    # target max spacing between stations (50–60 range)
MAX_GAP_ALLOWED_KM   = 60    # hard limit — no gap should exceed this
SNAP_TO_ROAD_MAX_KM  = 5     # max distance to snap existing station to corridor

# ─────────────────────────────────────────────────────────────
# SECTION 4 — DEMAND MODEL
# ─────────────────────────────────────────────────────────────
# EV_share_2027: computed from projection (659,323 EVs / ~25M total fleet)
# Total fleet ~24.8M passenger cars in Spain (DGT 2024)
TOTAL_FLEET_SPAIN    = 24_800_000
EV_PROJECTED_2027    = 659_323
EV_SHARE_2027        = EV_PROJECTED_2027 / TOTAL_FLEET_SPAIN  # ~2.66%

# Charging need factor: fraction of EV interurban traffic needing a public charge
# Justification: most interurban trips are <300km, ~15% of long-distance EV
# trips need a mid-route fast charge on any given day
CHARGING_NEED_FACTOR = 0.15

# Corridor multipliers reflecting importance
CORRIDOR_MULTIPLIERS = {
    "primary":   1.15,   # top-15 corridors by total km / strategic importance
    "standard":  1.00,   # typical autopista / autovía
    "secondary": 0.90,   # low-traffic carreteras nacionales
}

# Primary corridors (top routes by km + strategic Mediterranean/Atlantic axes)
PRIMARY_CORRIDORS = {
    "A-4", "A-7", "A-2", "A-66", "A-6", "AP-7N", "A-8", "A-3",
    "A-23", "A-92", "A-5", "A-62", "AP-7S", "A-1", "AP-68",
}

# ─────────────────────────────────────────────────────────────
# SECTION 5 — EXISTING SUPPLY MODEL
# ─────────────────────────────────────────────────────────────
DEFAULT_CHARGERS_PER_STATION  = 2
DEFAULT_KW_PER_CHARGER        = 50
DEFAULT_SUPPLY_PER_STATION_KW = DEFAULT_CHARGERS_PER_STATION * DEFAULT_KW_PER_CHARGER  # 100 kW

# ─────────────────────────────────────────────────────────────
# SECTION 9 — STATION SIZING
# ─────────────────────────────────────────────────────────────
CHARGER_KW          = 150    # fixed by competition rules
CHARGER_MIN         = 4      # minimum viable new station
CHARGER_STANDARD    = 8      # standard station midpoint
CHARGER_HIGH        = 12     # high-demand hub
CHARGER_MAX         = 16     # maximum unless very strong justification

# ─────────────────────────────────────────────────────────────
# SECTION 10 — GRID FEASIBILITY
# ─────────────────────────────────────────────────────────────
GRID_RATIO_SUFFICIENT = 0.40   # ratio <= this → Sufficient
GRID_RATIO_MODERATE   = 0.70   # ratio <= this → Moderate, above → Congested

# Voltage-based capacity estimation (when capacity_mw is not available)
# Conservative planning values for distribution substations
VOLTAGE_CAPACITY_MAP = {
    132: 40.0,   # MW — HV/MV transformer station
    110: 30.0,
    66:  15.0,
    55:  12.0,
    50:  10.0,
    45:   8.0,
    30:   5.0,
    25:   4.0,
    20:   3.0,
    15:   2.0,
    13.2: 1.5,
    11:   1.0,
    10:   0.8,
}

# ─────────────────────────────────────────────────────────────
# SECTION 12 — AMENITY SCORING
# ─────────────────────────────────────────────────────────────
AMENITY_RADIUS_KM    = 2.0   # search radius around candidate for amenities
AMENITY_SNAP_MAX_KM  = 3.0   # max distance to nudge candidate toward amenity

# ─────────────────────────────────────────────────────────────
# SECTION 13 — PRIORITIZATION WEIGHTS
# ─────────────────────────────────────────────────────────────
W_GAP           = 0.45
W_TRAFFIC       = 0.30
W_AMENITY       = 0.10
W_GRID_PENALTY  = 0.15

# ─────────────────────────────────────────────────────────────
# SECTION 14 — PHASING
# ─────────────────────────────────────────────────────────────
# Phase thresholds on priority score (0–1 scale)
# Use percentile-based logic: top ~30% → Phase 1, next ~40% → Phase 2, rest → Phase 3
PHASE_1_THRESHOLD = 0.30   # top priority → Phase 1
PHASE_2_THRESHOLD = 0.12   # moderate priority → Phase 2
# Below PHASE_2_THRESHOLD → Phase 3
