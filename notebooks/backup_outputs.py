"""
Backup Outputs — Version Snapshot
===================================
Run this BEFORE re-running any pipeline step that overwrites outputs/.
Creates a timestamped folder under outputs/archive/ with:
  - File 1.csv, File 2.csv, File 3.csv
  - A README.txt summarising the run

Usage:
  python notebooks/backup_outputs.py --label "added_province_weighting"
  python notebooks/backup_outputs.py          (uses timestamp only)

Colab note: run this cell before re-running any optimization/grid/output cells.
"""

import shutil
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime

OUTPUTS_DIR = Path("outputs")
ARCHIVE_DIR = OUTPUTS_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# ── Version label ─────────────────────────────────────────────────────────────
label = ""
for arg in sys.argv[1:]:
    if arg.startswith("--label="):
        label = arg.split("=", 1)[1]
    elif arg == "--label" and sys.argv.index(arg) + 1 < len(sys.argv):
        label = sys.argv[sys.argv.index(arg) + 1]

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
folder_name = f"{ts}_{label}" if label else ts
version_dir = ARCHIVE_DIR / folder_name
version_dir.mkdir()

# ── Copy files ────────────────────────────────────────────────────────────────
files_copied = []
for fname in ["File 1.csv", "File 2.csv", "File 3.csv"]:
    src = OUTPUTS_DIR / fname
    if src.exists():
        shutil.copy2(src, version_dir / fname)
        files_copied.append(fname)

# ── Write README ──────────────────────────────────────────────────────────────
readme_lines = [f"Snapshot: {ts}", f"Label:    {label or '(none)'}", ""]

for fname in files_copied:
    fpath = version_dir / fname
    try:
        df = pd.read_csv(fpath)
        readme_lines.append(f"── {fname} ({len(df)} rows) ──")
        readme_lines.append(df.to_string(index=False))
        readme_lines.append("")
    except Exception as e:
        readme_lines.append(f"── {fname}: could not read ({e})")

with open(version_dir / "README.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(readme_lines))

print(f"Snapshot saved → {version_dir}")
for f in files_copied:
    print(f"  {f}")
print(f"  README.txt")
