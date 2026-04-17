"""
Download MITMA Road Routes Data (estudios_rutas)
=================================================
Source: https://movilidad-opendata.mitma.es/ (S3 bucket: mitma-movilidad-v2)

Downloads:
  1. Geometry shapefile — official Ministry road segment geometries + road codes
     → data/raw/mitma_rutas/geometria/
  2. Segment traffic info (informacion_tramo) — traffic volumes per road segment
     → data/raw/mitma_rutas/informacion_tramo/
     We download a representative sample: 1 summer weekday, 1 summer weekend,
     1 autumn weekday — enough to compute average daily traffic per segment.

Skipped:
  - od_rutas/       (~40 MB each, optional OD matrices)
  - tramo_ruta/     (1.5–2 GB each, not needed for our use case)
  - calidad/        (quality flags, not needed)
"""

import requests
import time
from datetime import datetime
from pathlib import Path

BASE_URL = "https://movilidad-opendata.mitma.es"

# ── Output directories ────────────────────────────────────────────────────────
OUT_BASE = Path("data/raw/mitma_rutas")
GEO_DIR  = OUT_BASE / "geometria"
INFO_DIR = OUT_BASE / "informacion_tramo"
LOG_FILE = OUT_BASE / "download_log.txt"

GEO_DIR.mkdir(parents=True, exist_ok=True)
INFO_DIR.mkdir(parents=True, exist_ok=True)

# ── Logger — writes to console AND log file simultaneously ────────────────────
def log(msg: str, end: str = "\n") -> None:
    print(msg, end=end, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + end)

# ── Files to download ─────────────────────────────────────────────────────────

# 1. Geometry shapefile (all 5 components + validation CSV)
GEOMETRY_FILES = [
    "estudios_rutas/geometria/Geometria_tramos_2023_2024/Geometria_tramos.cpg",
    "estudios_rutas/geometria/Geometria_tramos_2023_2024/Geometria_tramos.dbf",
    "estudios_rutas/geometria/Geometria_tramos_2023_2024/Geometria_tramos.prj",
    "estudios_rutas/geometria/Geometria_tramos_2023_2024/Geometria_tramos.shp",
    "estudios_rutas/geometria/Geometria_tramos_2023_2024/Geometria_tramos.shx",
    "estudios_rutas/geometria/Geometria_tramos_2023_2024/rt_tramo_val.csv",
]

# 2. Segment info sample — representative days:
#    20230826 = Saturday (summer peak)
#    20230829 = Tuesday (summer weekday)
#    20231016 = Monday (autumn weekday)
#    20241016 = Monday (autumn 2024, most recent comparable)
INFO_FILES = [
    "estudios_rutas/informacion_tramo/20230826_Tramos_info_odmatrix.csv.gz",
    "estudios_rutas/informacion_tramo/20230829_Tramos_info_odmatrix.csv.gz",
    "estudios_rutas/informacion_tramo/20231016_Tramos_info_odmatrix.csv.gz",
    "estudios_rutas/informacion_tramo/20241016_Tramos_info_odmatrix.csv.gz",
]


def fmt_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"


def download_file(s3_key: str, out_dir: Path, file_num: int, total_files: int) -> bool:
    """Download a single file. Returns True on success, False on failure."""
    filename = Path(s3_key).name
    dest = out_dir / filename
    started_at = datetime.now().strftime("%H:%M:%S")

    if dest.exists():
        size_mb = dest.stat().st_size / 1e6
        log(f"  [{file_num}/{total_files}] SKIP  {filename}  ({size_mb:.1f} MB already on disk)")
        return True

    url = f"{BASE_URL}/{s3_key}"
    log(f"  [{file_num}/{total_files}] START {filename}  @ {started_at}")

    try:
        t0 = time.time()
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0

            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1 MB chunks
                    f.write(chunk)
                    downloaded += len(chunk)

                    elapsed = time.time() - t0
                    speed   = downloaded / elapsed if elapsed > 0 else 0  # bytes/s
                    pct     = downloaded / total * 100 if total else 0
                    eta     = fmt_eta((total - downloaded) / speed) if speed > 0 and total else "?"

                    progress = (
                        f"\r    {pct:5.1f}%  "
                        f"{downloaded/1e6:6.1f} / {total/1e6:.1f} MB  |  "
                        f"{speed/1e6:5.2f} MB/s  |  ETA {eta}   "
                    )
                    print(progress, end="", flush=True)

        elapsed_total = time.time() - t0
        avg_speed = downloaded / elapsed_total / 1e6
        finished_at = datetime.now().strftime("%H:%M:%S")

        # Clear the progress line, then log the completion line to both console and file
        print("\r" + " " * 80 + "\r", end="", flush=True)
        log(
            f"  [{file_num}/{total_files}] OK    {filename}  "
            f"{downloaded/1e6:.1f} MB  in {fmt_eta(elapsed_total)}  "
            f"({avg_speed:.2f} MB/s)  @ {finished_at}"
        )
        return True

    except Exception as e:
        print()
        log(f"  [{file_num}/{total_files}] ERROR {filename}: {e}")
        if dest.exists():
            dest.unlink()  # remove partial file
        return False


# ── Run downloads ─────────────────────────────────────────────────────────────

ALL_FILES = [(k, GEO_DIR) for k in GEOMETRY_FILES] + [(k, INFO_DIR) for k in INFO_FILES]
TOTAL = len(ALL_FILES)

header = (
    f"{'=' * 60}\n"
    f"MITMA Road Routes Downloader\n"
    f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    f"Total files: {TOTAL}  |  Log: {LOG_FILE}\n"
    f"{'=' * 60}"
)
log(header)

log("\n[Section 1/2] Geometry shapefile")
for i, key in enumerate(GEOMETRY_FILES, start=1):
    download_file(key, GEO_DIR, i, TOTAL)

log(f"\n[Section 2/2] Traffic segment info ({len(INFO_FILES)} sample days)")
for i, key in enumerate(INFO_FILES, start=len(GEOMETRY_FILES) + 1):
    download_file(key, INFO_DIR, i, TOTAL)

log("\n" + "=" * 60)
log(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log(f"  Geometry    → {GEO_DIR}")
log(f"  Segment info → {INFO_DIR}")
log(f"  Log file     → {LOG_FILE}")
log("\nNext step: run 01e_process_mitma_roads.py")
