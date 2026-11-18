# Publication preparation

Prepared locally on **2026-11-18** for the `ishashahwork` portfolio, starting from upstream `main` at `ba832fa604fa426fb4518c291cc6c313baecf227`.

## Final version and changes

- `v2/` and `outputs/v2/` are the final saved project version, as identified by the original commit message and methodology report. The top-level `outputs/` CSVs belong to v1.
- Replaced the outdated v1-first README with a portfolio overview, final-version links, measured CSV totals, a reproducible chart, tools, run instructions, and explicit evidence limits.
- Kept original source/output directories and all retained datasets byte-for-byte. The original single commit and Marco Sinaniz's authorship remain intact; see [credits](CREDITS.md).
- Removed 11 regenerable logs, cache/intermediate files, and the duplicate v1 co-location export. The exact list is in [removed-generated-files.txt](removed-generated-files.txt); every file remains recoverable from the original Git commit.
- Extended ignore rules for credentials, local environments, logs, and v2 intermediates. Raw data, large GeoPackages, and generated map HTML remain excluded.
- Replaced machine-specific Windows data paths in the MITMA processor, DGT province preparation, and MITMA exploration scripts with repository-root paths. Historical v1 notebook builders remain documented as machine-specific utilities.
- Added a read-only CSV validator, chart script, and `--check-inputs` runner option. The runner now stops before analysis if required files are missing. Modeling calculations, planning parameters, and saved deliverables were preserved.
- Made direct geospatial/ingestion dependencies explicit in the original Conda environment. Added clarifications to the original methodology report, including a phase-rule description consistent with the code and a distinction between the spacing target and verified coverage.

## Verification

The checks below cover the publication changes and saved outputs; they do not establish an end-to-end rerun.

| Check | Result |
| --- | --- |
| CSV consistency | 603 sites; 4,175 chargers; 626,250 kW; 581 Sufficient / 12 Moderate / 10 Congested; 22 friction points; phases 159 / 374 / 70 |
| Cross-file checks | IDs, coordinates, charger sizing, friction status/distributor/demand, KPI counts, forecast components, and phase rules agree |
| Result preservation | All 19 retained processed-data and output files are byte-identical to the source commit |
| Validator failure cases | Altered KPI count and altered station charger count are rejected |
| Runner behavior | Missing required inputs block execution; a simulated failing step stops subsequent steps and preserves the selected interpreter |
| Python syntax / environment | Python files parse; Conda YAML parses; fresh Python 3.11 environment installation not performed |
| Documentation / figure | Relative Markdown links resolve; generated figure visually inspected; `git diff --check` passes |
| Credentials | Pattern-based scan of 70 original reachable blobs and current text finds no apparent common tokens, private keys, credential URLs, or literal secret assignments; this is not an exhaustive audit |
| Exclusions | Representative credential, environment, raw data, map, log, and intermediate paths are ignored |

The validation script ran on system Python 3.9.6. Chart generation and additional checks used the existing Anaconda Python 3.13.5 environment. The analysis environment specifies Python 3.11; GeoPandas, Shapely, Folium, osmium, and pmdarima were unavailable in the environment inspected for preparation.

`python v2/run_pipeline.py --check-inputs` correctly exits with status 1 because the road and substation GeoPackages are absent. All five amenity layers are also missing. Neither the original SARIMA forecast nor the six-step optimization was rerun. No download endpoints, full Conda solve, offline map, Colab delivery, or road-coverage guarantee was verified.

## Remaining before public upload

1. **Confirm public sharing rights.** The upstream repository is private and has no license. Confirm the team's permission, full collaborator roster, individual roles, and dataset redistribution terms. Add an appropriate license only once those rights are known.
2. **Restore reproducibility inputs.** Obtain/generate the road and grid GeoPackages and amenity layers. Confirm the exact datos.gob.es fork and historical registration snapshot if regenerating the forecast. Follow [REPRODUCING.md](REPRODUCING.md), install Python 3.11 dependencies, and run the complete pipeline in a copy to retain historical outputs.
3. **Validate substantive claims.** Check post-siting road coverage and planning assumptions before claiming a coverage guarantee, optimized global solution, validated forecast, or engineering feasibility. No such claims were added to the README.
4. **Supply missing deliverables if desired.** No final PDF report, executed Colab notebooks, final presentation, or committed interactive map exists in this source. The README links the actual Markdown methodology report. Do not publish the excluded competition briefing as a team-authored report.
5. **Review and commit this local cleanup**, then create a repository under `ishashahwork` and push the preserved history plus the new commit. Suggested slug: `spain-ev-charging-network`. Keep the source remote named `upstream`; set a separate `origin` for the new repository. No upload, source push, or repository visibility change was performed during preparation.
6. After publication, update the personal website project link and verify README rendering and downloads on GitHub.
