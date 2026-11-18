# Ingestion and earlier analysis

This historical directory contains Python scripts. Run ingestion from the repository root. The **current planning pipeline is [`v2/`](../v2/)**, with final saved results under [`outputs/v2/`](../outputs/v2/).

- `01a_*` through `01f_*`: downloads, parsing, and data preparation shared with v2. Some providers require manual input or large files.
- `02_ev_projection.py`: SARIMA forecast requiring untracked registration Parquets.
- `03_optimization.py`, `03b_colocation_score.py`, `04_grid_analysis.py`, `05_generate_outputs.py`, `06_visualization.py`: earlier v1 planning/output workflow, retained for reference.
- `03c_extract_amenities_pbf.py`: shared OSM amenity extraction.
- `01_eda.py`, `explore_mitma.py`, `inspect_grid.py`: exploration.
- `build_colab_notebooks.py`, `fix_notebooks.py`, `backup_outputs.py`: historical v1 delivery helpers; not required for v2. Notebook builders retain machine-specific paths and expect untracked inputs.

Read [the reproduction guide](../docs/REPRODUCING.md) before running scripts. Source directories were retained to preserve relative paths.
