"""
Amenity Extraction from OSM PBF
================================
Reads spain-*.osm.pbf from data/raw/ and extracts the 5 amenity types
needed for co-location scoring. No internet required.

Output files (data/raw/amenities/):
  fuel.geojson          — petrol stations
  service_areas.geojson — highway service areas
  supermarkets.geojson  — supermarkets + hypermarkets
  hotels.geojson        — hotels + motels
  restaurants.geojson   — restaurants + fast food

Runtime: ~2–4 minutes on the full Spain PBF.
"""

import osmium
import json
import os
import glob

os.makedirs("data/raw/amenities", exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Locate PBF file
# ─────────────────────────────────────────────────────────────────────────────
pbf_candidates = glob.glob("data/raw/*.osm.pbf")
if not pbf_candidates:
    raise FileNotFoundError("No .osm.pbf file found in data/raw/")
PBF_FILE = pbf_candidates[0]
print(f"Using PBF: {PBF_FILE}")
print(f"File size: {os.path.getsize(PBF_FILE)/1024/1024:.0f} MB\n")

# ─────────────────────────────────────────────────────────────────────────────
# Tag filters — which tags map to which output bucket
# ─────────────────────────────────────────────────────────────────────────────
FILTERS = {
    "fuel":          lambda t: t.get("amenity") == "fuel",
    "service_areas": lambda t: t.get("highway") == "services",
    "supermarkets":  lambda t: t.get("shop") in ("supermarket", "hypermarket"),
    "hotels":        lambda t: t.get("tourism") in ("hotel", "motel"),
    "restaurants":   lambda t: t.get("amenity") in ("restaurant", "fast_food"),
}

# ─────────────────────────────────────────────────────────────────────────────
# Handler — collects nodes and way centroids
# ─────────────────────────────────────────────────────────────────────────────
class AmenityHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.features = {k: [] for k in FILTERS}
        self.counts = {k: 0 for k in FILTERS}

    def _record(self, lat, lon, tags_dict):
        for bucket, test in FILTERS.items():
            if test(tags_dict):
                self.features[bucket].append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {k: v for k, v in tags_dict.items()
                                   if k in ("name", "amenity", "highway",
                                            "shop", "tourism", "brand")},
                })
                self.counts[bucket] += 1

    def node(self, n):
        if n.location.valid():
            tags = {t.k: t.v for t in n.tags}
            self._record(n.location.lat, n.location.lon, tags)

    def way(self, w):
        # Use centroid of way envelope for POIs that are mapped as areas
        try:
            tags = {t.k: t.v for t in w.tags}
            # Quick check before computing centroid
            if any(test(tags) for test in FILTERS.values()):
                loc = w.nodes[len(w.nodes) // 2].location
                if loc.valid():
                    self._record(loc.lat, loc.lon, tags)
        except Exception:
            pass


print("Parsing PBF — this takes 2–4 minutes...")
handler = AmenityHandler()
handler.apply_file(PBF_FILE, locations=True, idx="flex_mem")

# ─────────────────────────────────────────────────────────────────────────────
# Save GeoJSON files
# ─────────────────────────────────────────────────────────────────────────────
print("\nResults:")
for bucket, features in handler.features.items():
    out_path = f"data/raw/amenities/{bucket}.geojson"
    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  {bucket:<16} {handler.counts[bucket]:>5,} features  →  {out_path}  ({size_kb:.0f} KB)")

print("\nDone. Run 03b_colocation_score.py next.")
