"""
DGT EV Registrations by Province — Extract & Weight
=====================================================
The existing parquets (from the datos.gob.es notebook) lack the CPRO (province
code) column. This script downloads 2023-2024 raw DGT monthly ZIPs, extracts
only the columns we need (including CPRO), and computes EV market share by
province. The result is used to geographically weight n_chargers in step 03.

Approach:
  - Download 24 monthly ZIPs (2023 + 2024) — most recent complete years
  - Filter to: passenger cars (COD_TIPO=40), new registrations (CLAVE_TRAMITE=1),
    electric propulsion (COD_PROPULSION_ITV=2)
  - Group by CPRO → ev_count per province
  - Compute ev_share = ev_count / total_ev_national
  - Scale to 2027 projected fleet (659,323) → ev_fleet_2027 per province

Outputs:
  data/processed/ev_by_province.csv    — EV count + share + 2027 projection
  data/processed/ev_share_by_province.csv — clean lookup for 03_optimization

Colab note: this script downloads ~300 MB of ZIPs from DGT. Run once and cache.
"""

import io
import re
import zipfile
import requests
import pandas as pd
import numpy as np
from pathlib import Path

OUT_DIR  = Path("data/processed")
CACHE_DIR = Path("data/raw/dgt_raw_province")
LOG_FILE = CACHE_DIR / "download_log.txt"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

TOTAL_EV_2027 = 659_323   # from SARIMA modelo (datos.gob.es fork)

def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Download 2023 + 2024 monthly ZIPs
# ─────────────────────────────────────────────────────────────────────────────
log("=" * 60)
log("STEP 1 — Download DGT monthly ZIPs (2023–2024)")
log("=" * 60)

YEARS_MONTHS = [(y, m) for y in [2023, 2024] for m in range(1, 13)]

def dgt_url(year, month):
    yyyymm = f"{year}{month:02d}"
    return (
        f"https://www.dgt.es/microdatos/salida/{year}/{month}/"
        f"vehiculos/matriculaciones/export_mensual_mat_{yyyymm}.zip"
    )

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

zip_paths = []
for year, month in YEARS_MONTHS:
    yyyymm = f"{year}{month:02d}"
    dest = CACHE_DIR / f"mat_{yyyymm}.zip"

    if dest.exists() and dest.stat().st_size > 10_000:
        log(f"  [SKIP] {yyyymm} already cached ({dest.stat().st_size/1e6:.1f} MB)")
        zip_paths.append(dest)
        continue

    url = dgt_url(year, month)
    try:
        r = session.get(url, timeout=60, stream=True)
        r.raise_for_status()
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=512*1024):
                f.write(chunk)
                size += len(chunk)
        log(f"  [OK]   {yyyymm} — {size/1e6:.1f} MB")
        zip_paths.append(dest)
    except Exception as e:
        log(f"  [ERR]  {yyyymm} — {e}")

log(f"\n  {len(zip_paths)} ZIP files ready")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Inspect one ZIP to find column positions (fixed-width format)
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "=" * 60)
log("STEP 2 — Inspect raw format")
log("=" * 60)

def read_dgt_zip(zip_path):
    """
    DGT files are fixed-width .txt inside a ZIP.
    We try CSV first (newer format), then fixed-width.
    Returns a DataFrame with at minimum: CPRO, COD_TIPO,
    COD_PROPULSION_ITV, CLAVE_TRAMITE columns.
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        txt_files = [n for n in names if n.endswith(('.txt', '.TXT', '.csv', '.CSV'))]
        if not txt_files:
            return None
        fname = txt_files[0]
        with zf.open(fname) as f:
            raw = f.read()

    # Try semicolon-delimited first
    try:
        df = pd.read_csv(
            io.BytesIO(raw), sep=';', encoding='latin-1',
            dtype=str, low_memory=False
        )
        if len(df.columns) > 5:
            return df
    except Exception:
        pass

    # Try pipe-delimited
    try:
        df = pd.read_csv(
            io.BytesIO(raw), sep='|', encoding='latin-1',
            dtype=str, low_memory=False
        )
        if len(df.columns) > 5:
            return df
    except Exception:
        pass

    return None

# Inspect first available ZIP
for zp in zip_paths[:1]:
    df_sample = read_dgt_zip(zp)
    if df_sample is not None:
        log(f"  File: {zp.name}")
        log(f"  Columns ({len(df_sample.columns)}): {list(df_sample.columns)[:20]}")
        log(f"  Rows: {len(df_sample):,}")
        log(f"  Sample:\n{df_sample.head(3).to_string()}")
        HAS_CPRO = any('CPRO' in c.upper() or 'PROV' in c.upper() for c in df_sample.columns)
        log(f"\n  Province column (CPRO) found: {HAS_CPRO}")
    else:
        log("  Could not parse ZIP format")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Extract EV registrations by province across all months
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "=" * 60)
log("STEP 3 — Extract EV registrations by province")
log("=" * 60)

all_ev_records = []
failed = []

for zp in zip_paths:
    try:
        df = read_dgt_zip(zp)
        if df is None:
            failed.append(zp.name)
            continue

        # Normalise column names
        df.columns = [c.strip().upper() for c in df.columns]

        # Find province column
        prov_col = next(
            (c for c in df.columns if 'CPRO' in c or c == 'PROVINCIA' or 'PROV' in c),
            None
        )
        if prov_col is None:
            log(f"  [WARN] {zp.name}: no province column, skipping")
            failed.append(zp.name)
            continue

        # Find required columns
        tipo_col  = next((c for c in df.columns if 'COD_TIPO' in c or c == 'TIPO'), None)
        prop_col  = next((c for c in df.columns if 'PROPULSION' in c), None)
        tram_col  = next((c for c in df.columns if 'TRAMITE' in c or 'CLAVE' in c), None)

        if not all([tipo_col, prop_col, tram_col]):
            log(f"  [WARN] {zp.name}: missing columns ({tipo_col},{prop_col},{tram_col})")
            failed.append(zp.name)
            continue

        # Filter:
        # COD_TIPO = '40' → passenger car (turismo)
        # COD_PROPULSION_ITV = '2' → electric
        # CLAVE_TRAMITE = '1' → new registration (not transfer/baja)
        mask = (
            (df[tipo_col].str.strip() == '40') &
            (df[prop_col].str.strip() == '2') &
            (df[tram_col].str.strip() == '1')
        )
        ev_df = df[mask][[prov_col]].copy()
        ev_df.columns = ['CPRO']
        ev_df['CPRO'] = ev_df['CPRO'].str.strip().str.zfill(2)
        all_ev_records.append(ev_df)

        log(f"  [OK] {zp.name}: {len(ev_df):,} EV registrations extracted")

    except Exception as e:
        log(f"  [ERR] {zp.name}: {e}")
        failed.append(zp.name)

if not all_ev_records:
    log("\n  No province data found in ZIPs — falling back to baseline proxy")
    # Fallback: use EV charging stations per province as proxy
    baseline = pd.read_csv("data/processed/ev_charging_baseline.csv")
    baseline["postcode_str"] = baseline["postcode"].astype(str).str.zfill(5)
    baseline["CPRO"] = baseline["postcode_str"].str[:2]
    prov_counts = baseline.groupby("CPRO")["n_connectors"].sum().reset_index()
    prov_counts.columns = ["CPRO", "ev_count"]
    prov_counts["source"] = "baseline_proxy"
    log(f"  Fallback: {len(prov_counts)} provinces from charging baseline")
else:
    combined = pd.concat(all_ev_records, ignore_index=True)
    prov_counts = combined.groupby("CPRO").size().reset_index(name="ev_count")
    prov_counts["source"] = "dgt_registrations_2023_2024"
    log(f"\n  Total EV registrations extracted: {len(combined):,}")
    log(f"  Provinces found: {len(prov_counts)}")
    if failed:
        log(f"  Failed files: {len(failed)} — {failed[:5]}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Compute EV share and 2027 projection per province
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "=" * 60)
log("STEP 4 — Compute province shares and 2027 EV fleet")
log("=" * 60)

# Province code → name lookup
PROVINCE_NAMES = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería",
    "05": "Ávila", "06": "Badajoz", "07": "Baleares", "08": "Barcelona",
    "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón",
    "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca",
    "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa",
    "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León",
    "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid",
    "29": "Málaga", "30": "Murcia", "31": "Navarra", "32": "Ourense",
    "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra",
    "37": "Salamanca", "38": "S.C. Tenerife", "39": "Cantabria", "40": "Segovia",
    "41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel",
    "45": "Toledo", "46": "Valencia", "47": "Valladolid", "48": "Vizcaya",
    "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
}

total_ev = prov_counts["ev_count"].sum()
prov_counts["ev_share"]      = prov_counts["ev_count"] / total_ev
prov_counts["ev_fleet_2027"] = (prov_counts["ev_share"] * TOTAL_EV_2027).round(0).astype(int)
prov_counts["province_name"] = prov_counts["CPRO"].map(PROVINCE_NAMES).fillna("Unknown")

# Sort by fleet size
prov_counts = prov_counts.sort_values("ev_fleet_2027", ascending=False).reset_index(drop=True)

log(f"\n  Top 15 provinces by 2027 projected EV fleet:")
log(prov_counts[["CPRO", "province_name", "ev_count", "ev_share", "ev_fleet_2027"]].head(15).to_string(index=False))
log(f"\n  Total ev_fleet_2027 sum: {prov_counts['ev_fleet_2027'].sum():,} (target: {TOTAL_EV_2027:,})")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Save outputs
# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "=" * 60)
log("STEP 5 — Save outputs")
log("=" * 60)

out1 = OUT_DIR / "ev_by_province.csv"
out2 = OUT_DIR / "ev_share_by_province.csv"

prov_counts.to_csv(out1, index=False, encoding="utf-8")

# Clean lookup file for 03_optimization.py
share_lookup = prov_counts[["CPRO", "province_name", "ev_share", "ev_fleet_2027"]].copy()
share_lookup.to_csv(out2, index=False, encoding="utf-8")

log(f"  Saved: {out1}")
log(f"  Saved: {out2}")
log(f"\n  {len(prov_counts)} provinces in output")
log("=" * 60)
log("Done. Next: update 03_optimization.py to use ev_share_by_province.csv")
