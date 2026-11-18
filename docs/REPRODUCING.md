# Reproducing the analysis

## Inspect saved deliverables

From the repository root:

```bash
python3 tools/verify_publication.py
```

This checks CSV schemas, IDs, coordinates, station/friction totals, charger sizing, cross-file consistency, projection totals, and phase labels. It uses the standard library, changes no results, and does not rerun the optimization or independently validate its assumptions.

## Environment and required inputs

```bash
conda env create -f environment.yml
conda activate datathon
python v2/run_pipeline.py --check-inputs
```

The environment specifies Python 3.11. Shapely 2+ is required by code treating STRtree results as indices. Direct geospatial and ingestion dependencies are now explicit, including osmium for PBF extraction. The broad original exploratory environment is retained. A fresh Conda install/solve has not been verified; dependencies are not fully locked.

| Input (relative to repository root) | In Git? | Restore using |
| --- | --- | --- |
| `data/processed/interurban_roads_mitma.gpkg` | No | `notebooks/01d_download_mitma_rutas.py`, then `notebooks/01e_process_mitma_roads.py` |
| `data/processed/ev_charging_baseline.csv` | Yes | Saved DGT/NAP baseline; download/parse scripts also retained |
| `data/processed/grid_substations_dedup.gpkg` | No | `notebooks/01c_deduplicate_grid.py` on the committed merged CSV |
| `data/processed/ev_projection_results.json` | Yes | Saved SARIMA projection; rerunning requires absent registration Parquets |
| `data/raw/amenities/*.geojson` (five layers) | No | Supply a Spain `.osm.pbf` in `data/raw/`, then run `notebooks/03c_extract_amenities_pbf.py` |

Run ingestion from the **repository root**, after installing dependencies and reviewing download sizes:

```bash
python notebooks/01d_download_mitma_rutas.py
python notebooks/01e_process_mitma_roads.py
python notebooks/01c_deduplicate_grid.py
# Supply the Spain PBF locally before extracting amenities:
python notebooks/03c_extract_amenities_pbf.py
```

Download endpoints were inspected in code but not checked live. Current snapshots may yield different results. Historical road processing uses EPSG:3857 for some lengths; v2 uses EPSG:25830. This preparation preserves those calculations and makes no new accuracy claim.

The five amenity layers are `fuel`, `service_areas`, `restaurants`, `supermarkets`, and `hotels`. v2 can skip absent layers; the runner warns because that changes scoring and siting. Supply all five to reproduce the saved scenario. `EV_SHARE_PROVINCE` appears in config, but current v2 steps use national EV share rather than consuming that province file.

To regenerate the forecast, confirm the exact datos.gob.es fork, populate `data/raw/parquets_procesados/`, then run `python notebooks/02_ev_projection.py`. The script does not download these Parquets. The repository URL in `DATA_SOURCES.md` is marked as a search lead, rather than a verified fork identifier.

## Execute v2

Back up `outputs/v2/` to retain historical results, then run from the root:

```bash
python v2/run_pipeline.py --check-inputs
python v2/run_pipeline.py
```

The runner selects `v2/` automatically. Steps write ignored GeoPackages under `v2/intermediate/`, replace four CSVs under `outputs/v2/`, and generate ignored `visualizations/v2_ev_network_map.html`. The Folium map references external assets and tiles; fully offline operation is unverified. Run individual step scripts from `v2/`; importing them executes their analysis at module level.

`notebooks/` contains shared ingestion and earlier v1 planning scripts. v1 writes the top-level `outputs/File 1.csv`, `File 2.csv`, and `File 3.csv`. Its historical `build_colab_notebooks.py` and `fix_notebooks.py` retain Windows-specific paths and are not needed for v2. They have not been rerun. No executed `.ipynb`, final PDF report, or final presentation is tracked. Use [the Markdown methodology report](../v2/METHODOLOGY_REPORT.md).
