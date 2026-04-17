"""
BI Visualization — Self-Contained Interactive Map
===================================================
Generates a single HTML file with an interactive Folium map showing:

  Layer 1 — Proposed Charging Stations (File 2)
    Color-coded by grid_status:
      Green  (#2ecc71) → Sufficient
      Orange (#f39c12) → Moderate
      Red    (#e74c3c) → Congested
    Circle markers sized by n_chargers_proposed
    Popup: location_id, route, chargers, grid_status, lat/lon

  Layer 2 — Friction Points (File 3)
    Red pulsing markers for Congested
    Orange markers for Moderate
    Popup: bottleneck_id, distributor, demand_kw, grid_status

  Layer 3 — Existing Charging Baseline
    Small grey dots from ev_charging_baseline.csv

  Controls:
    Layer switcher (top-right)
    Legend (bottom-right, color-coded)
    Fullscreen button
    Mini-map

Output:
  visualizations/iberdrola_ev_network_map.html   ← self-contained, no internet needed

Requirements: folium, branca
"""

import folium
from folium import plugins
import pandas as pd
import os
import json

os.makedirs("visualizations", exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# COLOR SCHEME
# ─────────────────────────────────────────────────────────────────────────────
STATUS_COLOR = {
    "Sufficient": "#2ecc71",   # green
    "Moderate":   "#f39c12",   # orange
    "Congested":  "#e74c3c",   # red
}
STATUS_ICON = {
    "Sufficient": "bolt",
    "Moderate":   "exclamation-triangle",
    "Congested":  "times-circle",
}
BASELINE_COLOR = "#95a5a6"  # grey for existing stations

# ─────────────────────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────
print("Loading data...")

file2 = pd.read_csv("outputs/File 2.csv") if os.path.exists("outputs/File 2.csv") else pd.DataFrame()
file3 = pd.read_csv("outputs/File 3.csv") if os.path.exists("outputs/File 3.csv") else pd.DataFrame()
baseline = pd.read_csv("data/processed/ev_charging_baseline.csv") if os.path.exists("data/processed/ev_charging_baseline.csv") else pd.DataFrame()
ev_proj_path = "data/processed/ev_projection_results.json"
ev_proj = json.load(open(ev_proj_path)) if os.path.exists(ev_proj_path) else {}

print(f"  Proposed stations: {len(file2):,}")
print(f"  Friction points:   {len(file3):,}")
print(f"  Baseline stations: {len(baseline):,}")

# ─────────────────────────────────────────────────────────────────────────────
# BASE MAP — centered on Spain
# ─────────────────────────────────────────────────────────────────────────────
m = folium.Map(
    location=[40.4, -3.7],
    zoom_start=6,
    tiles=None,
    prefer_canvas=True,
)

# Tile layers
folium.TileLayer(
    "CartoDB positron",
    name="Light (CartoDB)",
    attr="© CartoDB © OpenStreetMap contributors",
).add_to(m)

folium.TileLayer(
    "OpenStreetMap",
    name="OpenStreetMap",
    attr="© OpenStreetMap contributors",
).add_to(m)

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1 — Existing baseline (grey, small, bottom layer)
# ─────────────────────────────────────────────────────────────────────────────
if not baseline.empty:
    layer_baseline = folium.FeatureGroup(name="Existing Chargers (Baseline)", show=False)
    baseline_clean = baseline.dropna(subset=["latitude", "longitude"])
    # Sample to avoid performance issues (show up to 3000 points)
    if len(baseline_clean) > 3000:
        baseline_sample = baseline_clean.sample(3000, random_state=42)
        print(f"  Baseline sampled to 3,000 for performance")
    else:
        baseline_sample = baseline_clean

    for _, row in baseline_sample.iterrows():
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=3,
            color=BASELINE_COLOR,
            fill=True,
            fill_color=BASELINE_COLOR,
            fill_opacity=0.5,
            weight=0.5,
            popup=folium.Popup(
                f"<b>Existing Station</b><br>"
                f"Connectors: {int(row['n_connectors']) if pd.notna(row.get('n_connectors')) else 'N/A'}<br>"
                f"Max power: {row.get('max_power_kw', 'N/A')} kW<br>"
                f"Type: {row.get('type_of_site', 'N/A')}",
                max_width=200,
            ),
            tooltip="Existing charger",
        ).add_to(layer_baseline)
    layer_baseline.add_to(m)
    print(f"  Added {len(baseline_sample):,} baseline markers")

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2 — Proposed stations (color-coded by grid_status)
# ─────────────────────────────────────────────────────────────────────────────
if not file2.empty:
    # Sub-layers per status for independent toggle
    for status in ["Sufficient", "Moderate", "Congested"]:
        subset = file2[file2["grid_status"] == status]
        if subset.empty:
            continue

        layer = folium.FeatureGroup(
            name=f"Proposed — {status} ({len(subset):,})",
            show=True,
        )
        color = STATUS_COLOR[status]

        for _, row in subset.iterrows():
            # Size proportional to charger count (radius 5–15)
            n_chargers = int(row.get("n_chargers_proposed", 4))
            radius = 5 + n_chargers * 0.8

            colocation = int(row["colocation_score"]) if "colocation_score" in row and pd.notna(row.get("colocation_score")) else 0
            amenity = row.get("nearest_amenity", "none") if "nearest_amenity" in row else "none"
            colocation_bar = "★" * min(colocation, 9) if colocation > 0 else "—"

            popup_html = f"""
            <div style="font-family:Arial; min-width:180px">
              <b style="color:{color}">{row['location_id']}</b><br>
              <hr style="margin:4px 0">
              <b>Route:</b> {row['route_segment']}<br>
              <b>Chargers:</b> {n_chargers} × 150 kW<br>
              <b>Total capacity:</b> {n_chargers * 150:,} kW<br>
              <b>Grid status:</b>
              <span style="color:{color}; font-weight:bold">{row['grid_status']}</span><br>
              <b>Co-location score:</b> {colocation} {colocation_bar}<br>
              <b>Nearest amenity:</b> {amenity}<br>
              <b>Lat/Lon:</b> {row['latitude']:.4f}, {row['longitude']:.4f}
            </div>
            """
            tooltip_html = (
                f"{row['location_id']} | {row['route_segment']} | "
                f"{n_chargers} chargers | {row['grid_status']}"
            )

            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                radius=radius,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.8,
                weight=1.5,
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=tooltip_html,
            ).add_to(layer)

        layer.add_to(m)
        print(f"  Added {len(subset):,} {status} proposed station markers")

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3 — Friction points (File 3, larger markers with ring)
# ─────────────────────────────────────────────────────────────────────────────
if not file3.empty:
    layer_friction = folium.FeatureGroup(
        name=f"Friction Points — Grid Stress ({len(file3):,})",
        show=True,
    )

    for _, row in file3.iterrows():
        status = row["grid_status"]
        color = STATUS_COLOR.get(status, "#e74c3c")
        demand_kw = row.get("estimated_demand_kw", 0)

        popup_html = f"""
        <div style="font-family:Arial; min-width:200px">
          <b style="color:{color}">⚡ {row['bottleneck_id']}</b><br>
          <hr style="margin:4px 0">
          <b>Route:</b> {row['route_segment']}<br>
          <b>Distributor:</b> {row.get('distributor_network', 'N/A')}<br>
          <b>Demand:</b> {demand_kw:,.0f} kW ({demand_kw/1000:.1f} MW)<br>
          <b>Grid status:</b>
          <span style="color:{color}; font-weight:bold">{status}</span><br>
          <b>Action required:</b>
          {'Grid reinforcement mandatory' if status == 'Congested' else 'Monitoring & planning advised'}
        </div>
        """

        # Outer ring to highlight friction points
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=14,
            color=color,
            fill=False,
            weight=2,
            opacity=0.6,
        ).add_to(layer_friction)

        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=8,
            color="white",
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            weight=2,
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=f"⚡ {row['bottleneck_id']} | {row.get('distributor_network','?')} | {status}",
        ).add_to(layer_friction)

    layer_friction.add_to(m)
    print(f"  Added {len(file3):,} friction point markers")

# ─────────────────────────────────────────────────────────────────────────────
# CONTROLS & PLUGINS
# ─────────────────────────────────────────────────────────────────────────────
folium.LayerControl(position="topright", collapsed=False).add_to(m)
plugins.Fullscreen(position="topleft", title="Fullscreen", force_separate_button=True).add_to(m)
plugins.MiniMap(toggle_display=True, position="bottomleft").add_to(m)

# ─────────────────────────────────────────────────────────────────────────────
# LEGEND (injected as HTML)
# ─────────────────────────────────────────────────────────────────────────────
total_ev = ev_proj.get("total_ev_projected_2027", "N/A")
n_proposed = len(file2) if not file2.empty else "N/A"
n_friction = len(file3) if not file3.empty else "N/A"
n_sufficient  = int((file2["grid_status"] == "Sufficient").sum()) if not file2.empty else 0
n_moderate    = int((file2["grid_status"] == "Moderate").sum())   if not file2.empty else 0
n_congested   = int((file2["grid_status"] == "Congested").sum())  if not file2.empty else 0

legend_html = f"""
<div style="
    position: fixed;
    bottom: 30px;
    right: 10px;
    z-index: 1000;
    background: white;
    padding: 14px 18px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    font-family: Arial, sans-serif;
    font-size: 13px;
    min-width: 230px;
">
  <div style="font-size:15px; font-weight:bold; margin-bottom:10px; color:#2c3e50;">
    🔌 Iberdrola EV Network 2027
  </div>

  <div style="margin-bottom:8px; font-weight:bold; color:#555;">
    Proposed Stations ({n_proposed:,})
  </div>
  <div style="display:flex; align-items:center; margin:4px 0;">
    <span style="width:14px;height:14px;border-radius:50%;background:#2ecc71;display:inline-block;margin-right:8px;"></span>
    Sufficient &nbsp;<span style="color:#888">({n_sufficient:,})</span>
  </div>
  <div style="display:flex; align-items:center; margin:4px 0;">
    <span style="width:14px;height:14px;border-radius:50%;background:#f39c12;display:inline-block;margin-right:8px;"></span>
    Moderate &nbsp;<span style="color:#888">({n_moderate:,})</span>
  </div>
  <div style="display:flex; align-items:center; margin:4px 0;">
    <span style="width:14px;height:14px;border-radius:50%;background:#e74c3c;display:inline-block;margin-right:8px;"></span>
    Congested &nbsp;<span style="color:#888">({n_congested:,})</span>
  </div>

  <hr style="margin:10px 0; border-color:#eee;">

  <div style="display:flex; align-items:center; margin:4px 0;">
    <span style="width:14px;height:14px;border-radius:50%;border:2px solid #e74c3c;display:inline-block;margin-right:8px;"></span>
    Friction Points &nbsp;<span style="color:#888">({n_friction:,})</span>
  </div>
  <div style="display:flex; align-items:center; margin:4px 0;">
    <span style="width:14px;height:14px;border-radius:50%;background:#95a5a6;display:inline-block;margin-right:8px;"></span>
    Existing Baseline
  </div>

  <hr style="margin:10px 0; border-color:#eee;">

  <div style="color:#7f8c8d; font-size:11px; line-height:1.5;">
    📅 2027 scenario &nbsp;|&nbsp; 150 kW chargers<br>
    🚗 {total_ev:,} EVs projected<br>
    ⚡ Gap ≤ 150 km guaranteed<br>
    <span style="margin-top:4px;display:block;">© IE × Iberdrola Datathon 2026</span>
  </div>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# ─────────────────────────────────────────────────────────────────────────────
# TITLE BAR
# ─────────────────────────────────────────────────────────────────────────────
title_html = """
<div style="
    position: fixed;
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1000;
    background: rgba(44,62,80,0.92);
    color: white;
    padding: 8px 22px;
    border-radius: 20px;
    font-family: Arial, sans-serif;
    font-size: 15px;
    font-weight: bold;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    white-space: nowrap;
">
  ⚡ Spain Interurban EV Charging Network — 2027 Scenario
</div>
"""
m.get_root().html.add_child(folium.Element(title_html))

# ─────────────────────────────────────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────────────────────────────────────
out_path = "visualizations/iberdrola_ev_network_map.html"
m.save(out_path)
print(f"\nSaved: {out_path}")
print(f"  Open in any browser — fully self-contained, no internet required")

# File size check
size_mb = os.path.getsize(out_path) / 1024 / 1024
print(f"  File size: {size_mb:.1f} MB")
