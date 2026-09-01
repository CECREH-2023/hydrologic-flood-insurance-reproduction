# Reproducing the primary results

## Requirements

- Conda or Mamba
- Approximately 1 GB of free working memory plus the model runtime
- A multicore CPU is helpful but not required

Create the pinned environment from the repository root:

```bash
conda env create -f environment.yml
conda activate cecreh-hydrologic-reproduction
```

## One-command run

```bash
python scripts/run_all.py --threads 4
```

`run_all.py` first runs the statistical reproduction and then validates the package. The default uses 500 state-cluster bootstrap repetitions. Use `--threads 1` if a deterministic single-thread run is preferred; the pinned environment and fixed seed are the primary reproducibility controls.

## What the code does

1. Loads 83,360 analysis-ready observations and checks the release schema.
2. Fits seven nonempty combinations of three predictor blocks for each of three outcomes.
3. Uses five grouped folds so that every observation is scored by a model trained without observations from its state.
4. Computes exact Shapley contributions for mapped zones (M), hydrology (H), and built exposure (E).
5. Resamples states 500 times while holding the out-of-fold predictions fixed to quantify evaluation uncertainty.
6. Reconstructs the primary 80/20 screen and the 90/10 and 70/30 threshold checks.
7. Checks new outputs against the reference tables and scans the release surface for excluded artifacts.

## Expected checks

The validator requires the following core results:

| Check | Expected value |
|:---|---:|
| Analysis observations | 83,360 |
| State groups | 51 |
| Full IHP-rate model out-of-fold R² | 0.113728 |
| Hydrology share of full IHP-rate R² | 0.873409 |
| Mapped-zone share of full uptake R² | 0.496683 |
| Primary screen observations | 1,348 |
| High recorded IHP burden subset | 550 |
| Selected-to-sample mean IHP-rate ratio | 2.784005 |

The shares are allocations of explained out-of-fold R², not shares of the outcomes themselves. The IHP outcome is a declaration-conditioned registration rate and remains program mediated.

The “high recorded IHP burden” subset combines the primary screen with the highest national fifth of the same recorded declaration-conditioned IHP rate. It is a descriptive overlap within the source outcome, not independent confirmation.

## Generated outputs

The run writes these files to `results/generated/`:

- `block_model_metrics.csv`: out-of-fold R² and RMSE for all model combinations.
- `shapley_attribution.csv`: block contributions and shares of full-model R².
- `asymmetry_intervals.csv`: state-cluster evaluation intervals.
- `screen_thresholds.csv`: 90/10, 80/20, and 70/30 screen summaries.
- `screen_summary.json`: detailed primary-screen counts and rates.
- `oof_scores.parquet`: deidentified out-of-fold predictions keyed only to release row IDs.
- `reproduced_core_results.png`: compact reproduction figure.
- `run_metadata.json`: runtime and model settings.
- `validation_report.json`: machine-readable verification results.

Generated outputs are intentionally ignored by Git so a reproduction run does not modify the checked-in reference package.

## Rebuilding the release file

Maintainers with access to the complete derived tract dataset can rebuild the public analysis file:

```bash
python scripts/build_release_data.py \
  --source path/to/hydrologic_blindspot_dataset_2010_2024.parquet
```

The builder selects only the approved release fields, retains observations in the study universe, replaces the source row identity with a sequential release ID, and refuses fields whose names indicate direct geography or disallowed source-record detail.

The full raw-to-derived pipeline is not included in this lean package. The upstream products, vintages, and transformation chain needed to reconstruct that pipeline are documented in [DATA_PROVENANCE.md](DATA_PROVENANCE.md).

## Troubleshooting

- If Conda reports a package-resolution conflict, create a new environment rather than updating an existing one.
- If a run is interrupted, delete only the contents of `results/generated/` and rerun the command.
- Small floating-point differences outside the pinned environment may occur. The automated checks use tight numerical tolerances and require exact sample and screen counts.
