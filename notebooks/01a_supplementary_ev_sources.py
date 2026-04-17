"""
Supplementary EV Charging Sources — Madrid + Castilla y León
=============================================================
Downloads two additional open-data EV charging datasets, saves them as
separate raw files, then compares against our existing DGT NAP baseline
to quantify net new stations added (after deduplication).

Sources:
  - Madrid (Municipal): datos.madrid.es — updated monthly, CC BY 4.0
    https://datos.madrid.es/egob/catalogo/208979-0-puntos-recarga-historico.csv
  - Castilla y León (Regional, 9 provinces): datosabiertos.jcyl.es — updated annually
    https://datosabiertos.jcyl.es/web/jcyl/risp/es/energia/vehiculo_electrico/1284273412751.csv

Output files:
  data/raw/madrid_ev_charging_raw.csv
  data/raw/castilla_leon_ev_charging_raw.csv
  data/processed/supplementary_ev_madrid.csv
  data/processed/supplementary_ev_castilla_leon.csv
  data/processed/ev_charging_baseline_enriched.csv   ← merged final

Also considered but excluded due to staleness:
  - Vigo (last updated March 2020)
  - Barcelona (data files only up to 2023 Q2)
  - La Rioja (last updated January 2023)
"""

import requests
import pandas as pd
import numpy as np
import os
from io import StringIO
from datetime import date
from pyproj import Transformer

os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

BASELINE_CSV = "data/processed/ev_charging_baseline.csv"

# ─────────────────────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────────────────────

def download_csv(url, raw_path, encoding="utf-8", sep=",", skiprows=0):
    """Download a CSV from a URL, save raw, return DataFrame."""
    print(f"  GET {url}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DatathonProject/1.0)"}
    resp = requests.get(url, headers=headers, timeout=120)
    resp.raise_for_status()
    with open(raw_path, "wb") as f:
        f.write(resp.content)
    print(f"  Saved {len(resp.content)/1024:.1f} KB → {raw_path}")
    content = resp.content.decode(encoding, errors="replace")
    df = pd.read_csv(StringIO(content), sep=sep, skiprows=skiprows, low_memory=False)
    print(f"  Parsed {len(df)} rows × {len(df.columns)} columns")
    return df


def normalise(df_raw, source_name):
    """
    Map source-specific columns → baseline schema:
      site_id, national_id, name, latitude, longitude, postcode,
      country, operator, type_of_site, n_connectors, max_power_kw,
      total_power_kw, connector_types, source
    Latitude/longitude are mandatory; everything else best-effort.
    """
    df = df_raw.copy()
    # Lowercase all column names for easier matching
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    print(f"\n  [{source_name}] Raw columns: {df.columns.tolist()}")

    out = pd.DataFrame()

    # ── Madrid ────────────────────────────────────────────────────────────────
    if source_name == "Madrid":
        # Geoportal Madrid CSV columns (semicolon-separated, ETRS89/UTM zone 30N):
        # COD_DIS, DISTRITO, COD_BAR, BARRIO, UBICACIÓN, EMPLAZAMIE, INFO_ADICI,
        # Nº_EQUIPO, CARACTERÍ, OPERADOR, POINT_X, POINT_Y
        # Coordinates are in metres (EPSG:25830) — must reproject to WGS84
        x_col   = next((c for c in df.columns if "point_x" in c), None)
        y_col   = next((c for c in df.columns if "point_y" in c), None)
        name_col = next((c for c in df.columns if "ubicaci" in c or "emplaza" in c), None)
        op_col   = next((c for c in df.columns if "operador" in c), None)
        spec_col = next((c for c in df.columns if "caracter" in c or "info_adic" in c), None)

        if x_col is None or y_col is None:
            print(f"  WARNING: could not identify UTM coordinate columns in Madrid dataset")
            print(f"  Available columns: {df.columns.tolist()}")
            return pd.DataFrame()

        # Reproject UTM EPSG:25830 → WGS84 EPSG:4326
        transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
        x = pd.to_numeric(df[x_col], errors="coerce")
        y = pd.to_numeric(df[y_col], errors="coerce")
        valid = x.notna() & y.notna()
        lon_vals, lat_vals = transformer.transform(x[valid].values, y[valid].values)

        out = pd.DataFrame(index=df[valid].index)
        out["latitude"]       = lat_vals
        out["longitude"]      = lon_vals
        out["name"]           = df.loc[valid, name_col].astype(str) if name_col else np.nan
        out["operator"]       = df.loc[valid, op_col].astype(str)   if op_col   else np.nan
        out["max_power_kw"]   = np.nan  # packed in CARACTERÍ free text — not parsed
        out["n_connectors"]   = np.nan
        out["postcode"]       = np.nan
        out["connector_types"]= df.loc[valid, spec_col].astype(str) if spec_col else np.nan
        out["total_power_kw"] = np.nan
        out["type_of_site"]   = np.nan
        out["national_id"]    = np.nan
        out["country"]        = "ES"
        print(f"  Reprojected {valid.sum()} rows from UTM EPSG:25830 → WGS84")

    # ── Castilla y León ───────────────────────────────────────────────────────
    elif source_name == "CastillaLeon":
        # Actual columns: Nombre, Dirección, Operador, Número de conectores,
        # Tipo de conector, DMS (grados y minutos decimales) (N, W),
        # DD (Grados decimales) (N, W)
        # Coordinates packed in "DD" column as "41.541513,-4.658719"
        dd_col  = next((c for c in df.columns if "dd_" in c or "grados_dec" in c), None)
        name_col = next((c for c in df.columns if "nombre" in c or "direcci" in c), None)
        op_col   = next((c for c in df.columns if "operador" in c), None)
        pts_col  = next((c for c in df.columns if "conector" in c and "número" in c or "n_mero" in c or "número_de" in c), None)
        con_col  = next((c for c in df.columns if "tipo" in c and "conector" in c), None)

        if dd_col is None:
            print(f"  WARNING: could not identify DD coordinate column in Castilla y León dataset")
            print(f"  Available columns: {df.columns.tolist()}")
            return pd.DataFrame()

        # Parse "lat,lon" from the DD column (e.g. "41.541513,-4.658719")
        coords = df[dd_col].astype(str).str.strip().str.split(",", expand=True)
        out["latitude"]       = pd.to_numeric(coords[0], errors="coerce")
        out["longitude"]      = pd.to_numeric(coords[1], errors="coerce")
        out["name"]           = df[name_col].astype(str) if name_col else np.nan
        out["operator"]       = df[op_col].astype(str)   if op_col   else np.nan
        out["n_connectors"]   = pd.to_numeric(df[pts_col], errors="coerce") if pts_col else np.nan
        out["connector_types"]= df[con_col].astype(str)  if con_col  else np.nan
        out["max_power_kw"]   = np.nan  # not included in this dataset
        out["total_power_kw"] = np.nan
        out["postcode"]       = np.nan
        out["type_of_site"]   = np.nan
        out["national_id"]    = np.nan
        out["country"]        = "ES"

    out["site_id"] = [f"{source_name.upper()[:3]}_{i+1:04d}" for i in range(len(out))]
    out["source"]  = source_name
    out = out.dropna(subset=["latitude", "longitude"])
    print(f"  [{source_name}] Normalised → {len(out)} rows with valid coordinates")
    return out


def deduplicate(baseline_df, new_df, source_name, radius_deg=0.002):
    """
    Flag rows in new_df that are already in baseline_df based on geographic
    proximity (default ~200 m at Spain's latitude).
    Returns (new_only_df, n_duplicates).
    """
    from scipy.spatial import cKDTree

    if new_df.empty:
        return new_df, 0

    base_coords = baseline_df[["latitude", "longitude"]].dropna().values
    new_coords  = new_df[["latitude", "longitude"]].dropna().values

    if len(base_coords) == 0:
        return new_df, 0

    tree = cKDTree(base_coords)
    distances, _ = tree.query(new_coords, k=1)
    is_duplicate = distances < radius_deg

    n_dup = is_duplicate.sum()
    new_only = new_df[~is_duplicate].copy()
    print(f"  [{source_name}] {len(new_df)} total → {n_dup} duplicates (within {radius_deg}°) → {len(new_only)} net new")
    return new_only, int(n_dup)


# ─────────────────────────────────────────────────────────────────────────────
# 1. LOAD BASELINE
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 1 — Load existing DGT NAP baseline")
print("=" * 70)
baseline = pd.read_csv(BASELINE_CSV)
baseline["source"] = "DGT_NAP"
print(f"  Baseline: {len(baseline)} stations")


# ─────────────────────────────────────────────────────────────────────────────
# 2. MADRID
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 2 — Madrid Municipal Dataset (datos.madrid.es)")
print("Source: https://datos.madrid.es/egob/catalogo/208979-0-puntos-recarga-historico.csv")
print("Updated: monthly | License: CC BY 4.0")
print("=" * 70)

MADRID_URL = "https://geoportal.madrid.es/fsdescargas/IDEAM_WBGEOPORTAL/MOVILIDAD/VEHICULOS_ELECTRICOS/CSV/PUNTOS_PUBLICOS_RECARGA_VEHICULOS_ELECTRICOS.csv"
MADRID_RAW = "data/raw/madrid_ev_charging_raw.csv"
MADRID_OUT = "data/processed/supplementary_ev_madrid.csv"

try:
    madrid_raw = download_csv(MADRID_URL, MADRID_RAW, encoding="utf-8", sep=";", skiprows=0)
    madrid_norm = normalise(madrid_raw, "Madrid")
    if not madrid_norm.empty:
        madrid_norm.to_csv(MADRID_OUT, index=False, encoding="utf-8")
        print(f"  Saved normalised Madrid data → {MADRID_OUT}")
except Exception as e:
    print(f"  ERROR downloading Madrid data: {e}")
    madrid_norm = pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# 3. CASTILLA Y LEÓN
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 3 — Castilla y León Regional Dataset (datosabiertos.jcyl.es)")
print("Source: https://datosabiertos.jcyl.es/web/jcyl/risp/es/energia/vehiculo_electrico/1284273412751.csv")
print("Updated: annually (~3,378 points as of 2026) | License: CC BY 4.0")
print("=" * 70)

CYL_URL = "https://datosabiertos.jcyl.es/web/jcyl/risp/es/energia/vehiculo_electrico/1284273412751.csv"
CYL_RAW  = "data/raw/castilla_leon_ev_charging_raw.csv"
CYL_OUT  = "data/processed/supplementary_ev_castilla_leon.csv"

try:
    cyl_raw = download_csv(CYL_URL, CYL_RAW, encoding="utf-8", sep=";", skiprows=0)
    cyl_norm = normalise(cyl_raw, "CastillaLeon")
    if not cyl_norm.empty:
        cyl_norm.to_csv(CYL_OUT, index=False, encoding="utf-8")
        print(f"  Saved normalised Castilla y León data → {CYL_OUT}")
except Exception as e:
    print(f"  ERROR downloading Castilla y León data: {e}")
    cyl_norm = pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# 4. DEDUPLICATION COMPARISON
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 4 — Deduplication comparison vs DGT NAP baseline")
print("  Method: spatial proximity < 0.002° (~200 m) treated as same station")
print("=" * 70)

madrid_new,  madrid_dups  = deduplicate(baseline, madrid_norm,  "Madrid")
cyl_new,     cyl_dups     = deduplicate(baseline, cyl_norm,     "CastillaLeon")

# Cross-deduplicate the two new sources against each other
if not madrid_new.empty and not cyl_new.empty:
    cyl_new_final, cross_dups = deduplicate(madrid_new, cyl_new, "CastillaLeon-vs-Madrid")
else:
    cyl_new_final = cyl_new
    cross_dups = 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. SUMMARY REPORT
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 5 — Summary")
print("=" * 70)

n_baseline    = len(baseline)
n_madrid_raw  = len(madrid_norm)  if not madrid_norm.empty  else 0
n_cyl_raw     = len(cyl_norm)     if not cyl_norm.empty     else 0
n_madrid_new  = len(madrid_new)
n_cyl_new     = len(cyl_new_final)
n_total_new   = n_madrid_new + n_cyl_new

print(f"  DGT NAP baseline:                      {n_baseline:>6,} stations")
print(f"")
print(f"  Madrid dataset (raw):                  {n_madrid_raw:>6,} stations")
print(f"    └─ duplicates vs baseline:            {madrid_dups:>6,}")
print(f"    └─ NET NEW from Madrid:               {n_madrid_new:>6,}")
print(f"")
print(f"  Castilla y León dataset (raw):         {n_cyl_raw:>6,} stations")
print(f"    └─ duplicates vs baseline:            {cyl_dups:>6,}")
print(f"    └─ cross-dups vs Madrid new:          {cross_dups:>6,}")
print(f"    └─ NET NEW from Castilla y León:      {n_cyl_new:>6,}")
print(f"")
print(f"  ─────────────────────────────────────────────────")
print(f"  TOTAL NET NEW stations:                {n_total_new:>6,}")
print(f"  Enriched baseline total:               {n_baseline + n_total_new:>6,} stations")


# ─────────────────────────────────────────────────────────────────────────────
# 6. MERGE (only if net new stations exist)
# ─────────────────────────────────────────────────────────────────────────────
if n_total_new > 0:
    print("\n" + "=" * 70)
    print("STEP 6 — Merging into enriched baseline")
    print("=" * 70)

    # Align columns to baseline schema (drop 'source' for File 1/2/3 compatibility)
    baseline_cols = baseline.columns.tolist()
    if "source" not in baseline_cols:
        baseline_cols.append("source")

    def align_cols(df, cols):
        for c in cols:
            if c not in df.columns:
                df[c] = np.nan
        return df[cols]

    parts = [align_cols(baseline, baseline_cols)]
    if n_madrid_new > 0:
        parts.append(align_cols(madrid_new, baseline_cols))
    if n_cyl_new > 0:
        parts.append(align_cols(cyl_new_final, baseline_cols))

    enriched = pd.concat(parts, ignore_index=True)
    ENRICHED_OUT = "data/processed/ev_charging_baseline_enriched.csv"
    enriched.to_csv(ENRICHED_OUT, index=False, encoding="utf-8")
    print(f"  Saved enriched baseline → {ENRICHED_OUT}")
    print(f"  Final row count: {len(enriched):,}")
else:
    print("\n  No net new stations — enriched baseline not written (original is sufficient).")

print("\nDone.")
print(f"Access date: {date.today().isoformat()}")
