"""Validate the saved v2 deliverables without analysis dependencies or writes."""

import csv
from collections import Counter
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_csv(relative, fields):
    with (ROOT / relative).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        require(set(fields) <= set(reader.fieldnames or []),
                f"{relative}: missing required columns")
        rows = list(reader)
    require(bool(rows), f"{relative}: empty file")
    return rows


def site_key(row):
    return (row["route_segment"], float(row["latitude"]), float(row["longitude"]))


def validate():
    kpis = read_csv("outputs/v2/File 1.csv", [
        "total_proposed_stations", "total_existing_stations_baseline",
        "total_friction_points", "total_ev_projected_2027"])
    require(len(kpis) == 1, "File 1 must contain one KPI row")
    kpi = {key: int(value) for key, value in kpis[0].items()}
    require(all(value > 0 for value in kpi.values()), "KPIs must be positive")
    fields = ["location_id", "latitude", "longitude", "route_segment",
              "n_chargers_proposed", "grid_status"]
    sites = read_csv("outputs/v2/File 2.csv", fields)
    extended = read_csv("outputs/v2/extended_candidates.csv", fields + [
        "distributor_network", "estimated_demand_kw", "phase", "priority_score"])
    friction = read_csv("outputs/v2/File 3.csv", [
        "bottleneck_id", "latitude", "longitude", "route_segment",
        "distributor_network", "estimated_demand_kw", "grid_status"])
    require(len(sites) == len(extended) == kpi["total_proposed_stations"],
            "Station counts disagree")
    require(len(friction) == kpi["total_friction_points"], "Friction count disagrees")
    for rows, id_field in [(sites, "location_id"), (extended, "location_id"),
                           (friction, "bottleneck_id")]:
        ids = [row[id_field] for row in rows]
        require(all(ids) and len(ids) == len(set(ids)), f"Duplicate/empty {id_field}")
        for row in rows:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            require(math.isfinite(lat) and math.isfinite(lon) and
                    27 <= lat <= 44 and -19 <= lon <= 5, "Coordinate outside Spain bounds")
            require(bool(row["route_segment"]), "Missing road code")
    by_id = {row["location_id"]: row for row in extended}
    for row in sites:
        other = by_id.get(row["location_id"], {})
        require(all(row[field] == other.get(field) for field in fields),
                f"Extended data differs for {row['location_id']}")
    for row in extended:
        chargers = int(row["n_chargers_proposed"])
        require(4 <= chargers <= 16, "Charger count outside configured range")
        require(row["grid_status"] in {"Sufficient", "Moderate", "Congested"},
                "Invalid grid status")
        require(float(row["estimated_demand_kw"]) == chargers * 150,
                "Charger power differs from 150 kW")
        require(row["phase"] in {"1", "2", "3"}, "Invalid deployment phase")
        require(0 <= float(row["priority_score"]) <= 1, "Invalid priority score")
        score, status = float(row["priority_score"]), row["grid_status"]
        expected = 3 if status == "Congested" else (
            1 if score >= 0.30 and status == "Sufficient" else 2 if score >= 0.12 else 3)
        require(int(row["phase"]) == expected, "Phase disagrees with saved scenario rules")
    constrained = {site_key(row): row for row in extended
                   if row["grid_status"] in {"Moderate", "Congested"}}
    require(len(constrained) == len(friction), "Friction sites disagree")
    require({site_key(row) for row in friction} == set(constrained),
            "Friction locations disagree")
    for row in friction:
        other = constrained[site_key(row)]
        require(row["distributor_network"] in {"i-DE", "Endesa", "Viesgo"},
                "Unknown distributor")
        require(row["grid_status"] == other["grid_status"] and
                row["distributor_network"] == other["distributor_network"] and
                float(row["estimated_demand_kw"]) == float(other["estimated_demand_kw"]),
                "Friction status/distributor/demand differs")
    projection = json.loads((ROOT / "data/processed/ev_projection_results.json").read_text())
    require(kpi["total_ev_projected_2027"] == projection["total_ev_projected_2027"],
            "Forecast KPI differs")
    require(projection["total_ev_projected_2027"] == sum(projection[key] for key in [
        "total_historical_ev_2015_2025", "ev_new_registrations_2026_forecast",
        "ev_new_registrations_2027_forecast"]), "Forecast components disagree")
    return {**kpi, "total_chargers": sum(int(r["n_chargers_proposed"]) for r in sites),
            "capacity_kw": sum(float(r["estimated_demand_kw"]) for r in extended),
            "grid_status": dict(Counter(r["grid_status"] for r in sites)),
            "deployment_phases": dict(sorted(Counter(r["phase"] for r in extended).items()))}


if __name__ == "__main__":
    try:
        print(json.dumps(validate(), indent=2))
        print("PASS: saved deliverables are internally consistent; analysis was not rerun.")
    except (ValueError, KeyError, OSError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
