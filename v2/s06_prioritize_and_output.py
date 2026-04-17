"""
STEP 6 — Prioritization, Phasing, and Output Generation
=========================================================
1. Compute priority score per candidate
2. Assign deployment phases
3. Generate File 1, File 2, File 3 CSVs
4. Generate interactive BI visualization

Input:  v2/intermediate/final_candidates.gpkg
        v2/intermediate/friction_points.gpkg
        data/processed/ev_charging_baseline.csv
        data/processed/ev_projection_results.json
Output: outputs/v2/File 1.csv
        outputs/v2/File 2.csv
        outputs/v2/File 3.csv
        visualizations/v2_ev_network_map.html
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import json, os, sys
warnings_module = __import__('warnings')
warnings_module.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from config import *

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 1. Load data
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 6 — Prioritization, Phasing & Output Generation")
print("=" * 60)

candidates = gpd.read_file(os.path.join(DATA_DIR, "final_candidates.gpkg"))
print(f"Loaded {len(candidates)} final candidates")

with open(EV_PROJECTION_JSON) as f:
    ev_proj = json.load(f)

baseline = pd.read_csv(EV_BASELINE_CSV)

# ─────────────────────────────────────────────────────────────
# 2. PRIORITIZATION SCORE (Section 13)
# ─────────────────────────────────────────────────────────────
print("\n--- Computing Priority Scores ---")

# Normalize each component to 0–1
def normalize_col(s):
    mn, mx = s.min(), s.max()
    if mx == mn:
        return pd.Series(0.5, index=s.index)
    return (s - mn) / (mx - mn)

candidates['norm_gap'] = normalize_col(candidates['seg_gap_kw'].fillna(0).clip(lower=0))
candidates['norm_traffic'] = normalize_col(candidates['seg_avg_traffic'].fillna(0))
candidates['norm_amenity'] = normalize_col(candidates['amenity_score'].fillna(0))

# Grid risk: higher ratio = higher risk
candidates['norm_grid_risk'] = normalize_col(candidates['grid_load_ratio_adj'].fillna(0))

candidates['priority_score'] = (
    W_GAP         * candidates['norm_gap']
  + W_TRAFFIC     * candidates['norm_traffic']
  + W_AMENITY     * candidates['norm_amenity']
  - W_GRID_PENALTY * candidates['norm_grid_risk']
)

# Rescale to 0–1
candidates['priority_score'] = normalize_col(candidates['priority_score'])

print(f"Priority score range: {candidates['priority_score'].min():.3f} - {candidates['priority_score'].max():.3f}")
print(f"Priority score mean:  {candidates['priority_score'].mean():.3f}")

# ─────────────────────────────────────────────────────────────
# 3. PHASING (Section 14)
# ─────────────────────────────────────────────────────────────
print("\n--- Assigning Deployment Phases ---")

def assign_phase(row):
    score = row['priority_score']
    status = row['grid_status']

    # Congested sites → Phase 3 regardless of score
    if status == 'Congested':
        return 3

    # High priority + Sufficient grid → Phase 1
    if score >= PHASE_1_THRESHOLD and status == 'Sufficient':
        return 1

    # Moderate score or Moderate grid → Phase 2
    if score >= PHASE_2_THRESHOLD:
        return 2

    # Low priority → Phase 3
    return 3

candidates['phase'] = candidates.apply(assign_phase, axis=1)

print("Phase distribution:")
print(candidates['phase'].value_counts().sort_index().to_string())
print("\nPhase × Grid Status:")
print(pd.crosstab(candidates['phase'], candidates['grid_status']).to_string())

# ─────────────────────────────────────────────────────────────
# 4. Generate location_id
# ─────────────────────────────────────────────────────────────
# Sort by phase then priority score for nice IDs
candidates = candidates.sort_values(['phase', 'priority_score'], ascending=[True, False]).reset_index(drop=True)
candidates['location_id'] = [f"IBE_{i+1:03d}" for i in range(len(candidates))]

# ─────────────────────────────────────────────────────────────
# 5. FILE 2 — Proposed Charging Locations
# ─────────────────────────────────────────────────────────────
print("\n--- Generating File 2 (Proposed Locations) ---")

file2 = candidates[[
    'location_id', 'latitude', 'longitude', 'route_segment',
    'n_chargers_proposed', 'grid_status',
]].copy()

# Validate
assert file2['location_id'].is_unique, "location_id must be unique"
assert file2['latitude'].between(-90, 90).all(), "latitude out of range"
assert file2['longitude'].between(-180, 180).all(), "longitude out of range"
assert file2['grid_status'].isin(['Sufficient', 'Moderate', 'Congested']).all()

file2.to_csv(os.path.join(OUTPUT_DIR, "File 2.csv"), index=False)
print(f"File 2: {len(file2)} rows → {OUTPUT_DIR}/File 2.csv")

# ─────────────────────────────────────────────────────────────
# 6. FILE 3 — Friction Points
# ─────────────────────────────────────────────────────────────
print("\n--- Generating File 3 (Friction Points) ---")

friction = candidates[candidates['grid_status'].isin(['Moderate', 'Congested'])].copy()
friction = friction.sort_values('grid_load_ratio_adj', ascending=False).reset_index(drop=True)
friction['bottleneck_id'] = [f"FRIC_{i+1:03d}" for i in range(len(friction))]

file3 = friction[[
    'bottleneck_id', 'latitude', 'longitude', 'route_segment',
    'distributor_network', 'estimated_demand_kw', 'grid_status',
]].copy()

# Validate: only Moderate and Congested
assert file3['grid_status'].isin(['Moderate', 'Congested']).all()

file3.to_csv(os.path.join(OUTPUT_DIR, "File 3.csv"), index=False)
print(f"File 3: {len(file3)} rows → {OUTPUT_DIR}/File 3.csv")

# ─────────────────────────────────────────────────────────────
# 7. FILE 1 — Global KPIs
# ─────────────────────────────────────────────────────────────
print("\n--- Generating File 1 (Global KPIs) ---")

# Filter baseline to interurban
# Simple heuristic: stations within 5km of any interurban road segment
from shapely.strtree import STRtree

segments = gpd.read_file(os.path.join(DATA_DIR, "road_segments_wgs84.gpkg"))
baseline_gdf = gpd.GeoDataFrame(
    baseline,
    geometry=gpd.points_from_xy(baseline['longitude'], baseline['latitude']),
    crs=CRS_WGS84,
).to_crs(CRS_METRIC)

segments_m = segments.to_crs(CRS_METRIC)
road_buffer = segments_m.geometry.buffer(5000).unary_union  # 5km buffer

interurban_mask = baseline_gdf.geometry.within(road_buffer)
n_existing_interurban = interurban_mask.sum()

file1 = pd.DataFrame([{
    'total_proposed_stations': len(file2),
    'total_existing_stations_baseline': n_existing_interurban,
    'total_friction_points': len(file3),
    'total_ev_projected_2027': ev_proj['total_ev_projected_2027'],
}])

file1.to_csv(os.path.join(OUTPUT_DIR, "File 1.csv"), index=False)
print(f"File 1 → {OUTPUT_DIR}/File 1.csv")
print(file1.to_string(index=False))

# ─────────────────────────────────────────────────────────────
# 8. Extended dataset for analysis
# ─────────────────────────────────────────────────────────────
print("\n--- Saving extended candidate dataset ---")

extended = candidates[[
    'location_id', 'latitude', 'longitude', 'route_segment',
    'n_chargers_proposed', 'grid_status', 'distributor_network',
    'estimated_demand_kw', 'coverage_candidate_flag', 'demand_candidate_flag',
    'priority_score', 'phase', 'candidate_type',
    'n_chargers_initial', 'sizing_action', 'grid_load_ratio_adj',
    'seg_avg_traffic', 'seg_gap_kw', 'amenity_score',
    'corridor_class', 'sub_capacity_mw',
]].copy()

extended.to_csv(os.path.join(OUTPUT_DIR, "extended_candidates.csv"), index=False)
print(f"Extended dataset: {len(extended)} rows → {OUTPUT_DIR}/extended_candidates.csv")

# ─────────────────────────────────────────────────────────────
# 9. BI VISUALIZATION
# ─────────────────────────────────────────────────────────────
print("\n--- Generating BI Visualization ---")

try:
    import folium
    from folium.plugins import MarkerCluster, Fullscreen, MiniMap

    # -------------------------------------------------------------
    # KPI computations for header panel
    # -------------------------------------------------------------
    CAPEX_PER_CHARGER_EUR = 60_000  # rough industry figure for 150 kW DC charger (site + civil)
    n_prop           = len(candidates)
    n_chargers_total = int(candidates['n_chargers_proposed'].sum())
    total_peak_kw    = float(candidates['estimated_demand_kw'].sum())
    n_friction       = len(friction)
    ev_2027          = int(ev_proj['total_ev_projected_2027'])
    capex_m_eur      = n_chargers_total * CAPEX_PER_CHARGER_EUR / 1_000_000
    total_corridor_km = float(segments['segment_length_km'].sum())

    ph1 = int((candidates['phase'] == 1).sum())
    ph2 = int((candidates['phase'] == 2).sum())
    ph3 = int((candidates['phase'] == 3).sum())

    gs_suf = int((candidates['grid_status'] == 'Sufficient').sum())
    gs_mod = int((candidates['grid_status'] == 'Moderate').sum())
    gs_con = int((candidates['grid_status'] == 'Congested').sum())

    dist_counts = candidates['distributor_network'].value_counts().to_dict()

    # Center on Spain
    m = folium.Map(location=[40.0, -3.5], zoom_start=6,
                   tiles='CartoDB positron', control_scale=True)
    Fullscreen().add_to(m)
    MiniMap(toggle_display=True, position='bottomright').add_to(m)

    # -------------------------------------------------------------
    # Road-segment layers (traffic heat + route-type toggles)
    # -------------------------------------------------------------
    print("  Building road-segment layers...")

    # Quintile breakpoints for traffic colouring
    tq = segments['avg_traffic'].replace(0, np.nan).quantile([0.2, 0.4, 0.6, 0.8]).tolist()
    TRAFFIC_COLORS = ['#2c7bb6', '#74add1', '#fee08b', '#fdae61', '#d73027']  # low→high
    TRAFFIC_LABELS = [
        f'Very low (< {int(tq[0]):,})',
        f'Low ({int(tq[0]):,} – {int(tq[1]):,})',
        f'Medium ({int(tq[1]):,} – {int(tq[2]):,})',
        f'High ({int(tq[2]):,} – {int(tq[3]):,})',
        f'Very high (≥ {int(tq[3]):,})',
    ]

    def traffic_color(v):
        if pd.isna(v) or v <= 0: return '#cccccc'
        if v <= tq[0]: return TRAFFIC_COLORS[0]
        if v <= tq[1]: return TRAFFIC_COLORS[1]
        if v <= tq[2]: return TRAFFIC_COLORS[2]
        if v <= tq[3]: return TRAFFIC_COLORS[3]
        return TRAFFIC_COLORS[4]

    # Simplify geometries + round coords aggressively to keep HTML size small.
    # 0.002° simplify tolerance ≈ 220 m — fine at national zoom levels.
    # Coord rounding to 4 decimals ≈ 11 m precision → shrinks GeoJSON ~3×.
    from shapely.geometry import mapping, shape

    def _round_coords(geom, nd=4):
        gj = mapping(geom)
        def _r(c):
            if isinstance(c, (int, float)):
                return round(c, nd)
            if len(c) and isinstance(c[0], (int, float)):
                return [round(v, nd) for v in c]
            return [_r(x) for x in c]
        gj['coordinates'] = _r(gj['coordinates'])
        return shape(gj)

    seg_viz = segments[['route_segment', 'road_category', 'corridor_class',
                        'avg_traffic', 'segment_length_km', 'geometry']].copy()
    seg_viz['geometry'] = seg_viz['geometry'].simplify(0.002, preserve_topology=True)
    seg_viz = seg_viz[~seg_viz.geometry.is_empty].copy()
    seg_viz['geometry'] = seg_viz['geometry'].apply(_round_coords)
    seg_viz['avg_traffic_int'] = seg_viz['avg_traffic'].fillna(0).astype(int)
    seg_viz['traffic_color'] = seg_viz['avg_traffic'].apply(traffic_color)
    seg_viz['segment_length_km'] = seg_viz['segment_length_km'].round(1)

    # Layer: Routes coloured by traffic (AADT heat) — default ON
    traffic_layer = folium.FeatureGroup(name='🚗 Routes — Traffic heat (AADT)', show=True)
    folium.GeoJson(
        seg_viz.__geo_interface__,
        style_function=lambda f: {
            'color': f['properties']['traffic_color'],
            'weight': 4 if f['properties']['corridor_class'] == 'primary'
                     else (3 if f['properties']['corridor_class'] == 'standard' else 2),
            'opacity': 0.85,
        },
        highlight_function=lambda f: {'weight': 6, 'opacity': 1.0},
        tooltip=folium.GeoJsonTooltip(
            fields=['route_segment', 'road_category', 'corridor_class',
                    'avg_traffic_int', 'segment_length_km'],
            aliases=['Route', 'Road type', 'Corridor class',
                     'Traffic (AADT)', 'Segment length (km)'],
            sticky=True, localize=True,
        ),
    ).add_to(traffic_layer)
    traffic_layer.add_to(m)

    # Layers: Routes by road category (off by default — toggle to show)
    CAT_COLORS = {
        'Autopista':          '#6a3d9a',   # purple — tolled motorway
        'Autovía':            '#1f78b4',   # blue   — free motorway
        'Carretera Nacional': '#33a02c',   # green  — national road
    }
    for cat, col in CAT_COLORS.items():
        sub = seg_viz[seg_viz['road_category'] == cat]
        if sub.empty:
            continue
        km_total = sub['segment_length_km'].sum()
        lyr = folium.FeatureGroup(
            name=f'🛣️ {cat} ({len(sub)} seg · {km_total:,.0f} km)',
            show=False,
        )
        folium.GeoJson(
            sub.__geo_interface__,
            style_function=lambda f, color=col: {
                'color': color, 'weight': 3, 'opacity': 0.8,
            },
            highlight_function=lambda f: {'weight': 5, 'opacity': 1.0},
            tooltip=folium.GeoJsonTooltip(
                fields=['route_segment', 'avg_traffic_int', 'corridor_class'],
                aliases=['Route', 'Traffic (AADT)', 'Corridor class'],
                sticky=True, localize=True,
            ),
        ).add_to(lyr)
        lyr.add_to(m)

    # -------------------------------------------------------------
    # Proposed stations — one layer per deployment phase
    # -------------------------------------------------------------
    print("  Building proposed-station layers...")
    status_colors = {'Sufficient': '#2ca02c', 'Moderate': '#ff7f0e', 'Congested': '#d62728'}
    phase_meta = {
        1: {'emoji': '🟢', 'label': 'Phase 1 (build 2026–27)', 'show': True},
        2: {'emoji': '🟡', 'label': 'Phase 2 (build 2028–29)', 'show': True},
        3: {'emoji': '🔴', 'label': 'Phase 3 (build 2030+ / grid-gated)', 'show': True},
    }

    for ph in (1, 2, 3):
        sub = candidates[candidates['phase'] == ph]
        meta = phase_meta[ph]
        lyr = folium.FeatureGroup(
            name=f"{meta['emoji']} {meta['label']} — {len(sub)} stations",
            show=meta['show'],
        )
        for _, row in sub.iterrows():
            color = status_colors.get(row['grid_status'], 'gray')
            capex_k = row['n_chargers_proposed'] * CAPEX_PER_CHARGER_EUR / 1000
            popup_html = f"""
            <div style="font-family:Arial,sans-serif;font-size:12px;min-width:220px">
              <b style='font-size:13px;color:#0a5bad;'>{row['location_id']}</b>
              <span style='float:right;background:{color};color:white;padding:1px 6px;border-radius:3px;font-size:10px;'>
                {row['grid_status']}
              </span>
              <hr style='margin:4px 0'>
              <b>Route:</b> {row['route_segment']} ({row['corridor_class']})<br>
              <b>Chargers:</b> {row['n_chargers_proposed']} × 150 kW
                = {row['estimated_demand_kw']:,.0f} kW<br>
              <b>Phase:</b> {row['phase']} &nbsp;·&nbsp;
              <b>Priority:</b> {row['priority_score']:.2f}<br>
              <b>Type:</b> {row['candidate_type']}<br>
              <b>Distributor:</b> {row['distributor_network']}<br>
              <b>Traffic (AADT):</b> {int(row['seg_avg_traffic']):,}<br>
              <b>Grid load ratio:</b> {row['grid_load_ratio_adj']:.0%}<br>
              <b>Est. CAPEX:</b> €{capex_k:,.0f}k
            </div>
            """
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=max(4, row['n_chargers_proposed'] / 1.8),
                color=color, weight=1.5,
                fill=True, fill_color=color, fill_opacity=0.75,
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=f"{row['location_id']} · {row['route_segment']} · "
                        f"{row['n_chargers_proposed']}×150 kW · {row['grid_status']}",
            ).add_to(lyr)
        lyr.add_to(m)

    # -------------------------------------------------------------
    # Friction points layer
    # -------------------------------------------------------------
    print("  Building friction-point layer...")
    friction_layer = folium.FeatureGroup(
        name=f'⚠️ Friction points (grid upgrade needed) — {len(friction)}',
        show=True,
    )
    for _, row in friction.iterrows():
        color = 'red' if row['grid_status'] == 'Congested' else 'orange'
        popup_html = f"""
        <div style="font-family:Arial,sans-serif;font-size:12px;min-width:220px">
          <b style='color:#c00;'>⚠ {row['bottleneck_id']}</b><br>
          <b>Route:</b> {row['route_segment']}<br>
          <b>Grid status:</b> {row['grid_status']}<br>
          <b>Distributor:</b> {row['distributor_network']}<br>
          <b>Demand:</b> {row['estimated_demand_kw']:,.0f} kW<br>
          <b>Sub. capacity:</b> {row['sub_capacity_mw']:.1f} MW<br>
        </div>
        """
        folium.Marker(
            location=[row['latitude'], row['longitude']],
            icon=folium.Icon(color=color, icon='warning-sign', prefix='glyphicon'),
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=f"{row['bottleneck_id']} · {row['grid_status']}",
        ).add_to(friction_layer)
    friction_layer.add_to(m)

    # -------------------------------------------------------------
    # Existing baseline stations (interurban subset) — clustered
    # -------------------------------------------------------------
    print("  Building existing-baseline layer...")
    baseline_interurban = baseline[interurban_mask.values].reset_index(drop=True)
    existing_layer = folium.FeatureGroup(
        name=f'⚪ Existing stations (interurban) — {len(baseline_interurban):,}',
        show=False,
    )
    existing_cluster = MarkerCluster(
        disableClusteringAtZoom=9,
        maxClusterRadius=50,
    ).add_to(existing_layer)
    for _, row in baseline_interurban.iterrows():
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=2, color='#888888', weight=1,
            fill=True, fill_opacity=0.5,
        ).add_to(existing_cluster)
    existing_layer.add_to(m)

    folium.LayerControl(collapsed=False, position='topright').add_to(m)

    # -------------------------------------------------------------
    # KPI header panel (top)
    # -------------------------------------------------------------
    kpi_html = f"""
    <div style="position:fixed; top:8px; left:50%; transform:translateX(-50%);
         z-index:9999; background:rgba(255,255,255,0.96);
         padding:8px 14px; border-radius:8px;
         box-shadow:0 2px 10px rgba(0,0,0,0.18);
         font-family:Arial,sans-serif; font-size:11px;
         display:flex; gap:14px; align-items:center;
         border-left:5px solid #0a5bad;">
      <div style='line-height:1.1'>
        <div style='font-size:13px;font-weight:700;color:#0a5bad;'>Iberdrola EV Charging Network</div>
        <div style='font-size:10px;color:#555'>2027 deployment scenario · Interurban Spain</div>
      </div>
      <div style='border-left:1px solid #ddd;padding-left:12px;text-align:center'>
        <div style='font-size:15px;font-weight:700;color:#0a5bad'>{n_prop}</div>
        <div>Proposed stations</div>
      </div>
      <div style='text-align:center'>
        <div style='font-size:15px;font-weight:700'>{n_chargers_total:,}</div>
        <div>150 kW chargers</div>
      </div>
      <div style='text-align:center'>
        <div style='font-size:15px;font-weight:700'>{total_peak_kw/1000:.1f} MW</div>
        <div>Peak demand</div>
      </div>
      <div style='text-align:center'>
        <div style='font-size:15px;font-weight:700;color:#c00'>{n_friction}</div>
        <div>Friction pts</div>
      </div>
      <div style='text-align:center'>
        <div style='font-size:15px;font-weight:700'>{ev_2027:,}</div>
        <div>EVs in 2027</div>
      </div>
      <div style='text-align:center'>
        <div style='font-size:15px;font-weight:700'>€{capex_m_eur:.1f} M</div>
        <div>Est. CAPEX<sup>*</sup></div>
      </div>
      <div style='text-align:center'>
        <div style='font-size:15px;font-weight:700'>{total_corridor_km:,.0f} km</div>
        <div>Corridors analysed</div>
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(kpi_html))

    # -------------------------------------------------------------
    # Phase / distributor breakdown panel (bottom-left)
    # -------------------------------------------------------------
    breakdown_html = f"""
    <div style="position:fixed; bottom:18px; left:14px; z-index:9999;
         background:rgba(255,255,255,0.96); padding:10px 12px;
         border-radius:6px; box-shadow:0 2px 8px rgba(0,0,0,0.15);
         font-family:Arial,sans-serif; font-size:11px; min-width:200px;">
      <div style='font-weight:700;color:#0a5bad;margin-bottom:4px;'>Deployment roadmap</div>
      <table style='width:100%;border-collapse:collapse'>
        <tr><td>🟢 Phase 1 (2026–27)</td><td style='text-align:right'><b>{ph1}</b></td></tr>
        <tr><td>🟡 Phase 2 (2028–29)</td><td style='text-align:right'><b>{ph2}</b></td></tr>
        <tr><td>🔴 Phase 3 (2030+)</td><td style='text-align:right'><b>{ph3}</b></td></tr>
      </table>
      <div style='font-weight:700;color:#0a5bad;margin:6px 0 4px;'>Grid status</div>
      <table style='width:100%;border-collapse:collapse'>
        <tr><td><span style='color:#2ca02c'>●</span> Sufficient</td><td style='text-align:right'><b>{gs_suf}</b></td></tr>
        <tr><td><span style='color:#ff7f0e'>●</span> Moderate</td><td style='text-align:right'><b>{gs_mod}</b></td></tr>
        <tr><td><span style='color:#d62728'>●</span> Congested</td><td style='text-align:right'><b>{gs_con}</b></td></tr>
      </table>
      <div style='font-weight:700;color:#0a5bad;margin:6px 0 4px;'>Distributor mix</div>
      <table style='width:100%;border-collapse:collapse'>
        <tr><td>i-DE (Iberdrola)</td><td style='text-align:right'><b>{dist_counts.get('i-DE', 0)}</b></td></tr>
        <tr><td>Endesa</td><td style='text-align:right'><b>{dist_counts.get('Endesa', 0)}</b></td></tr>
        <tr><td>Viesgo</td><td style='text-align:right'><b>{dist_counts.get('Viesgo', 0)}</b></td></tr>
      </table>
      <div style='margin-top:6px;font-size:9px;color:#777'>
        * CAPEX: €{CAPEX_PER_CHARGER_EUR/1000:.0f}k per 150 kW charger (site + civil, industry estimate).
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(breakdown_html))

    # -------------------------------------------------------------
    # Legend (bottom-right) — traffic gradient + route types
    # -------------------------------------------------------------
    legend_html = f"""
    <div style="position:fixed; bottom:18px; right:14px; z-index:9999;
         background:rgba(255,255,255,0.96); padding:10px 12px;
         border-radius:6px; box-shadow:0 2px 8px rgba(0,0,0,0.15);
         font-family:Arial,sans-serif; font-size:11px; min-width:210px;">
      <div style='font-weight:700;color:#0a5bad;margin-bottom:4px;'>Traffic intensity (AADT)</div>
      <div style='display:flex;height:10px;border-radius:2px;overflow:hidden;margin-bottom:3px;'>
        <div style='flex:1;background:{TRAFFIC_COLORS[0]}'></div>
        <div style='flex:1;background:{TRAFFIC_COLORS[1]}'></div>
        <div style='flex:1;background:{TRAFFIC_COLORS[2]}'></div>
        <div style='flex:1;background:{TRAFFIC_COLORS[3]}'></div>
        <div style='flex:1;background:{TRAFFIC_COLORS[4]}'></div>
      </div>
      <div style='display:flex;justify-content:space-between;font-size:9px;color:#555'>
        <span>low</span><span>high</span>
      </div>
      <div style='font-weight:700;color:#0a5bad;margin:8px 0 3px;'>Road type</div>
      <div><span style='display:inline-block;width:14px;height:3px;background:{CAT_COLORS["Autopista"]};vertical-align:middle'></span>
           Autopista (tolled)</div>
      <div><span style='display:inline-block;width:14px;height:3px;background:{CAT_COLORS["Autovía"]};vertical-align:middle'></span>
           Autovía (motorway)</div>
      <div><span style='display:inline-block;width:14px;height:3px;background:{CAT_COLORS["Carretera Nacional"]};vertical-align:middle'></span>
           Carretera Nacional</div>
      <div style='font-weight:700;color:#0a5bad;margin:8px 0 3px;'>Station grid status</div>
      <div><span style='color:#2ca02c;font-size:14px;'>●</span> Sufficient &nbsp;
           <span style='color:#ff7f0e;font-size:14px;'>●</span> Moderate &nbsp;
           <span style='color:#d62728;font-size:14px;'>●</span> Congested</div>
      <div style='margin-top:4px;color:#777;font-size:9px;'>Circle size ∝ # of chargers.</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    # Give the map some top margin so the header doesn't overlap controls
    m.get_root().html.add_child(folium.Element(
        "<style>.folium-map{margin-top:0!important}</style>"
    ))

    viz_dir = "../visualizations"
    os.makedirs(viz_dir, exist_ok=True)
    map_path = os.path.join(viz_dir, "v2_ev_network_map.html")
    m.save(map_path)
    size_mb = os.path.getsize(map_path) / 1024 / 1024
    print(f"Map saved → {map_path} ({size_mb:.1f} MB)")

except ImportError:
    print("folium not installed — skipping visualization")

# ─────────────────────────────────────────────────────────────
# FINAL SUMMARY
# ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("FINAL PIPELINE SUMMARY")
print(f"{'='*60}")
print(f"Total proposed stations:      {len(candidates)}")
print(f"Total chargers:               {candidates['n_chargers_proposed'].sum()}")
print(f"Total capacity:               {candidates['estimated_demand_kw'].sum():,.0f} kW")
print(f"Existing interurban baseline: {n_existing_interurban}")
print(f"Friction points:              {len(friction)}")
print(f"EV projected 2027:            {ev_proj['total_ev_projected_2027']:,}")
print(f"\nBy grid status:")
print(f"  Sufficient: {(candidates['grid_status'] == 'Sufficient').sum()}")
print(f"  Moderate:   {(candidates['grid_status'] == 'Moderate').sum()}")
print(f"  Congested:  {(candidates['grid_status'] == 'Congested').sum()}")
print(f"\nBy phase:")
print(f"  Phase 1: {(candidates['phase'] == 1).sum()}")
print(f"  Phase 2: {(candidates['phase'] == 2).sum()}")
print(f"  Phase 3: {(candidates['phase'] == 3).sum()}")
print(f"\nBy candidate type:")
print(candidates['candidate_type'].value_counts().to_string())
print(f"\nOutput files:")
print(f"  {OUTPUT_DIR}/File 1.csv")
print(f"  {OUTPUT_DIR}/File 2.csv")
print(f"  {OUTPUT_DIR}/File 3.csv")
print(f"  {OUTPUT_DIR}/extended_candidates.csv")
