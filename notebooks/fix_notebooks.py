"""Fix notebooks 01 and 02 and re-execute them."""
import nbformat as nbf
import subprocess, sys
from pathlib import Path

PYTHON_ENV = sys.executable
NB_DIR = Path("C:/Users/LEGION/Desktop/MASTERS/Datathon/notebooks/v1")

def execute(path):
    print(f"  Executing {path.name} ...", flush=True)
    r = subprocess.run([
        PYTHON_ENV, "-m", "nbconvert",
        "--to", "notebook", "--execute", "--inplace",
        "--ExecutePreprocessor.timeout=600",
        "--ExecutePreprocessor.kernel_name=python3",
        str(path),
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [ERR]\n{r.stderr[-1500:]}")
    else:
        print(f"  [OK]")

# ── Fix notebook 1 ────────────────────────────────────────────────────────────
p1 = NB_DIR / "01_data_ingestion.ipynb"
with open(p1, encoding="utf-8") as f:
    nb1 = nbf.read(f, as_version=4)

# Fix the DGT cell — compute ev_penetration_factor inline
for cell in nb1.cells:
    if "ev_penetration_factor" in cell.source and cell.cell_type == "code":
        cell.source = """import pandas as pd
import numpy as np

ev_prov = pd.read_csv("data/processed/ev_share_by_province.csv", dtype={"CPRO": str})
# Compute penetration factor (not stored in CSV — computed here for display)
median_share = ev_prov["ev_share"].median()
ev_prov["ev_penetration_factor"] = np.clip(ev_prov["ev_share"] / median_share, 0.5, 2.0)

print(f"Provinces in dataset: {len(ev_prov)}")
print(f"\\nTop 10 provinces by 2027 projected EV fleet:")
print(ev_prov[["CPRO","province_name","ev_share","ev_fleet_2027","ev_penetration_factor"]]
      .head(10).to_string(index=False))
print(f"\\nNational total: {ev_prov['ev_fleet_2027'].sum():,} EVs")"""
        break

with open(p1, "w", encoding="utf-8") as f:
    nbf.write(nb1, f)
print("Fixed notebook 01")
execute(p1)

# ── Fix notebook 2 ────────────────────────────────────────────────────────────
p2 = NB_DIR / "02_ev_projection.ipynb"
with open(p2, encoding="utf-8") as f:
    nb2 = nbf.read(f, as_version=4)

BASE = "C:/Users/LEGION/Desktop/MASTERS/Datathon"
for cell in nb2.cells:
    if cell.cell_type == "code":
        # Replace relative paths with absolute paths
        cell.source = cell.source.replace(
            '"data/processed/', f'"{BASE}/data/processed/'
        ).replace(
            "'data/processed/", f"'{BASE}/data/processed/"
        )

with open(p2, "w", encoding="utf-8") as f:
    nbf.write(nb2, f)
print("Fixed notebook 02")
execute(p2)
