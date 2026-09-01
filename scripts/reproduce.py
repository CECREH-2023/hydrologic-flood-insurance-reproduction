#!/usr/bin/env python3
"""Reproduce the main model comparison and screening results.

The included analysis-ready file contains public-source tract covariates and
derived rates but omits direct tract identifiers and source-record counts.
Models are evaluated with five state-grouped folds so every observation is
scored by a model trained without observations from its state.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from itertools import combinations
from math import factorial
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = PACKAGE_ROOT / "data" / "analysis_ready.parquet"
DEFAULT_OUTPUT = PACKAGE_ROOT / "results" / "generated"

RANDOM_STATE = 42
N_SPLITS = 5
HIGH_PERCENTILE = 0.80
LOW_PERCENTILE = 0.20
LOW_SFHA_SHARE = 0.05

MAPPED_ZONE_FEATURES = [
    "nfhl_sfha_share_land",
    "nfhl_500yr_share_total",
    "nfhl_floodway_share_total",
    "nfhl_zone_a_share_total",
    "nfhl_zone_ae_share_total",
    "nfhl_zone_ve_share_total",
]

HYDROLOGY_FEATURES = [
    "soil_hsg_a_share",
    "soil_hsg_b_share",
    "soil_hsg_c_share",
    "soil_hsg_d_share",
    "soil_hsg_dual_share",
    "soil_poorly_drained_share",
    "soil_floodfreq_frequent_share",
    "soil_ponding_present_share",
    "soil_shallow_water_table_share",
    "soil_wtdepannmin_area_mean_cm",
    "soil_aws0150wta_area_mean",
    "soil_slopegradwta_area_mean_pct",
    "soil_rootznaws_area_mean",
    "soil_droughty_area_mean",
    "prism_ppt_annual_mean_2010_2024_mm",
    "prism_ppt_annual_max_2010_2024_mm",
]

BUILT_EXPOSURE_FEATURES = [
    "nlcd_developed_share",
    "nsi_structure_count",
    "nsi_residential_structure_count",
    "eda_housing_unit_density_per_km2_land",
    "log1p_eda_population_density_per_km2_land",
    "tract_land_km2",
]

FEATURE_BLOCKS = {
    "M": MAPPED_ZONE_FEATURES,
    "H": HYDROLOGY_FEATURES,
    "E": BUILT_EXPOSURE_FEATURES,
}

MODEL_COMBINATIONS = ["M", "H", "E", "M+H", "M+E", "H+E", "M+H+E"]

OUTCOMES = {
    "ihp_flood": "log1p_ihp_declaration_conditioned_incidence_proxy_rate",
    "claims": "log1p_claims_rate",
    "uptake": "log1p_uptake_rate",
}


def log(message: str) -> None:
    print(f"[reproduction] {message}", flush=True)


def read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    table = pq.read_table(path, columns=columns)
    return pd.DataFrame(table.to_pydict())


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    arrays = {column: pa.array(frame[column].tolist()) for column in frame.columns}
    pq.write_table(pa.table(arrays), path, compression="zstd", compression_level=9)


def required_columns() -> list[str]:
    columns = [
        "record_id",
        "state_fips",
        *OUTCOMES.values(),
        "ihp_declaration_conditioned_incidence_proxy_rate",
        "ihp_cumulative_administrative_burden_rate",
        "claims_rate",
        "uptake_rate",
        "acs_total_pop",
        "acs_housing_units",
        *MAPPED_ZONE_FEATURES,
        *HYDROLOGY_FEATURES,
        *BUILT_EXPOSURE_FEATURES,
    ]
    return list(dict.fromkeys(columns))


def load_analysis_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Analysis-ready file not found: {path}")
    frame = read_parquet(path)
    missing = sorted(set(required_columns()) - set(frame.columns))
    if missing:
        raise ValueError(f"Analysis-ready file is missing columns: {', '.join(missing)}")
    if len(frame) != 83_360:
        raise ValueError(f"Expected 83,360 observations, found {len(frame):,}")
    if frame["record_id"].isna().any() or not frame["record_id"].is_unique:
        raise ValueError("record_id must be complete and unique")
    if frame["state_fips"].nunique() != 51:
        raise ValueError("Expected 50 states plus the District of Columbia")
    return frame.reset_index(drop=True)


def model_features(combination: str) -> list[str]:
    columns: list[str] = []
    for block in combination.split("+"):
        columns.extend(FEATURE_BLOCKS[block])
    return columns


def make_regressor(threads: int):
    from xgboost import XGBRegressor

    return XGBRegressor(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.04,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=2.0,
        objective="reg:squarederror",
        random_state=RANDOM_STATE,
        n_jobs=threads,
        missing=np.nan,
        verbosity=0,
    )


def out_of_fold_predictions(
    predictors: np.ndarray,
    outcome: np.ndarray,
    groups: np.ndarray,
    threads: int,
) -> np.ndarray:
    from sklearn.model_selection import GroupKFold

    predictions = np.full(len(outcome), np.nan)
    splitter = GroupKFold(n_splits=N_SPLITS)
    for train_index, test_index in splitter.split(predictors, outcome, groups):
        model = make_regressor(threads)
        model.fit(predictors[train_index], outcome[train_index])
        predictions[test_index] = model.predict(predictors[test_index])
    return predictions


def r_squared(outcome: np.ndarray, prediction: np.ndarray) -> float:
    residual_sum = float(np.sum((outcome - prediction) ** 2))
    total_sum = float(np.sum((outcome - np.mean(outcome)) ** 2))
    return 1.0 - residual_sum / total_sum if total_sum > 0 else np.nan


def shapley_attribution(
    values_by_combination: dict[str, float],
    clamp_negative_values: bool = True,
) -> dict[str, float]:
    blocks = ["M", "H", "E"]
    values: dict[frozenset[str], float] = {frozenset(): 0.0}
    for combination, value in values_by_combination.items():
        stored = max(float(value), 0.0) if clamp_negative_values else float(value)
        values[frozenset(combination.split("+"))] = stored

    attributions: dict[str, float] = {}
    for block in blocks:
        total = 0.0
        other_blocks = [candidate for candidate in blocks if candidate != block]
        for size in range(len(other_blocks) + 1):
            for subset_tuple in combinations(other_blocks, size):
                subset = frozenset(subset_tuple)
                weight = (
                    factorial(len(subset))
                    * factorial(len(blocks) - len(subset) - 1)
                    / factorial(len(blocks))
                )
                total += weight * (values[subset | {block}] - values[subset])
        attributions[block] = total
    return attributions


def fit_model_grid(
    frame: pd.DataFrame,
    threads: int,
) -> tuple[pd.DataFrame, dict[tuple[str, str], np.ndarray]]:
    groups = frame["state_fips"].astype(str).to_numpy()
    fit_rows: list[dict[str, float | int | str]] = []
    predictions: dict[tuple[str, str], np.ndarray] = {}

    for outcome_name, outcome_column in OUTCOMES.items():
        outcome = pd.to_numeric(frame[outcome_column], errors="coerce").to_numpy()
        finite = np.isfinite(outcome)
        if not finite.all():
            raise ValueError(f"Outcome {outcome_name} contains non-finite values")
        for combination in MODEL_COMBINATIONS:
            predictors = frame[model_features(combination)].apply(
                pd.to_numeric, errors="coerce"
            ).to_numpy()
            prediction = out_of_fold_predictions(
                predictors, outcome, groups, threads=threads
            )
            fit_rows.append(
                {
                    "outcome": outcome_name,
                    "combo": combination,
                    "n": int(finite.sum()),
                    "oof_r2": r_squared(outcome, prediction),
                    "oof_rmse": float(np.sqrt(np.mean((outcome - prediction) ** 2))),
                }
            )
            predictions[(outcome_name, combination)] = prediction
            log(
                f"{outcome_name:9s} {combination:5s} "
                f"R2={fit_rows[-1]['oof_r2']:.4f}"
            )

    return pd.DataFrame(fit_rows), predictions


def calculate_shapley_table(fits: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for outcome_name in OUTCOMES:
        subset = fits[fits["outcome"] == outcome_name]
        value_map = dict(zip(subset["combo"], subset["oof_r2"], strict=True))
        clamped = shapley_attribution(value_map)
        unclamped = shapley_attribution(value_map, clamp_negative_values=False)
        full_r2 = float(value_map["M+H+E"])
        denominator = max(full_r2, 1e-12)
        for block in ["M", "H", "E"]:
            others = "+".join(
                sorted(set("MHE") - {block}, key="MHE".index)
            )
            rows.append(
                {
                    "outcome": outcome_name,
                    "block": block,
                    "shapley_r2": clamped[block],
                    "share_of_full_r2": clamped[block] / denominator,
                    "shapley_r2_unclamped": unclamped[block],
                    "share_unclamped": unclamped[block] / denominator,
                    "full_r2": full_r2,
                    "delta_r2_given_others": full_r2 - value_map[others],
                }
            )
    return pd.DataFrame(rows)


def bootstrap_intervals(
    frame: pd.DataFrame,
    predictions: dict[tuple[str, str], np.ndarray],
    shapley_table: pd.DataFrame,
    repetitions: int,
) -> pd.DataFrame:
    random = np.random.default_rng(RANDOM_STATE)
    states = frame["state_fips"].astype(str).to_numpy()
    unique_states = np.unique(states)
    indexes_by_state = {
        state: np.where(states == state)[0] for state in unique_states
    }
    outcomes = {
        name: pd.to_numeric(frame[column], errors="coerce").to_numpy()
        for name, column in OUTCOMES.items()
    }

    rows: list[dict[str, float | int]] = []
    for repetition in range(repetitions):
        sampled_states = random.choice(
            unique_states, size=len(unique_states), replace=True
        )
        indexes = np.concatenate(
            [indexes_by_state[state] for state in sampled_states]
        )
        shares: dict[str, dict[str, float]] = {}
        for outcome_name, outcome in outcomes.items():
            value_map = {
                combination: r_squared(
                    outcome[indexes],
                    predictions[(outcome_name, combination)][indexes],
                )
                for combination in MODEL_COMBINATIONS
            }
            attribution = shapley_attribution(value_map)
            denominator = max(value_map["M+H+E"], 1e-12)
            shares[outcome_name] = {
                block: value / denominator for block, value in attribution.items()
            }
        rows.append(
            {
                "rep": repetition,
                "s_H_ihp_flood": shares["ihp_flood"]["H"],
                "s_H_claims": shares["claims"]["H"],
                "s_H_uptake": shares["uptake"]["H"],
                "s_M_ihp_flood": shares["ihp_flood"]["M"],
                "s_M_uptake": shares["uptake"]["M"],
                "A_H_primary": shares["ihp_flood"]["H"]
                - shares["uptake"]["H"],
                "A_H_claims": shares["claims"]["H"]
                - shares["uptake"]["H"],
                "A_M": shares["uptake"]["M"] - shares["ihp_flood"]["M"],
            }
        )

    bootstrap = pd.DataFrame(rows)
    summary = (
        bootstrap.drop(columns="rep")
        .quantile([0.025, 0.5, 0.975])
        .T.reset_index()
    )
    summary.columns = ["statistic", "ci_lower", "median", "ci_upper"]

    def share(outcome: str, block: str) -> float:
        row = shapley_table.query("outcome == @outcome and block == @block")
        return float(row["share_of_full_r2"].iloc[0])

    point_estimates = {
        "A_H_primary": share("ihp_flood", "H") - share("uptake", "H"),
        "A_H_claims": share("claims", "H") - share("uptake", "H"),
        "A_M": share("uptake", "M") - share("ihp_flood", "M"),
    }
    summary["point_estimate"] = summary["statistic"].map(point_estimates)
    summary["bootstrap_reps"] = repetitions
    summary["bootstrap_mode"] = (
        "state-cluster evaluation bootstrap (fixed OOF predictions)"
    )
    return summary


def screen_results(
    frame: pd.DataFrame,
    predictions: dict[tuple[str, str], np.ndarray],
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    score_percentile = pd.Series(
        predictions[("ihp_flood", "H+E")], index=frame.index
    ).rank(pct=True)
    uptake_percentile = pd.to_numeric(frame["uptake_rate"], errors="coerce").rank(
        pct=True
    )
    low_mapped_exposure = (
        pd.to_numeric(frame["nfhl_sfha_share_land"], errors="coerce")
        .fillna(0.0)
        .le(LOW_SFHA_SHARE)
    )
    recorded_ihp_rate_percentile = pd.to_numeric(
        frame["ihp_declaration_conditioned_incidence_proxy_rate"],
        errors="coerce",
    ).rank(pct=True)

    primary = (
        score_percentile.ge(HIGH_PERCENTILE)
        & low_mapped_exposure
        & uptake_percentile.le(LOW_PERCENTILE)
    )
    high_recorded_burden = primary & recorded_ihp_rate_percentile.ge(
        HIGH_PERCENTILE
    )

    universe_rate = float(
        pd.to_numeric(
            frame["ihp_declaration_conditioned_incidence_proxy_rate"],
            errors="coerce",
        ).mean()
    )
    selected_rate = float(
        pd.to_numeric(
            frame.loc[
                primary, "ihp_declaration_conditioned_incidence_proxy_rate"
            ],
            errors="coerce",
        ).mean()
    )

    summary: dict[str, float | int] = {
        "analysis_rows": int(len(frame)),
        "state_groups": int(frame["state_fips"].nunique()),
        "primary_screen_rows": int(primary.sum()),
        "high_recorded_burden_rows": int(high_recorded_burden.sum()),
        "selected_population": float(
            pd.to_numeric(frame.loc[primary, "acs_total_pop"], errors="coerce").sum()
        ),
        "selected_housing_units": float(
            pd.to_numeric(
                frame.loc[primary, "acs_housing_units"], errors="coerce"
            ).sum()
        ),
        "selected_mean_ihp_rate": selected_rate,
        "universe_mean_ihp_rate": universe_rate,
        "selected_to_universe_mean_ratio": selected_rate / universe_rate,
        "selected_mean_nfip_uptake": float(
            pd.to_numeric(frame.loc[primary, "uptake_rate"], errors="coerce").mean()
        ),
        "universe_mean_nfip_uptake": float(
            pd.to_numeric(frame["uptake_rate"], errors="coerce").mean()
        ),
    }

    threshold_rows: list[dict[str, float | int | str]] = []
    rate = pd.to_numeric(
        frame["ihp_declaration_conditioned_incidence_proxy_rate"], errors="coerce"
    )
    for high_cut, low_cut in [(0.90, 0.10), (0.80, 0.20), (0.70, 0.30)]:
        selected = (
            score_percentile.ge(high_cut)
            & low_mapped_exposure
            & uptake_percentile.le(low_cut)
        )
        selected_values = rate[selected]
        threshold_rows.append(
            {
                "threshold": f"{int(high_cut * 100)}/{int(low_cut * 100)}",
                "tracts": int(selected.sum()),
                "median_ihp_flood_rate": float(selected_values.median()),
                "universe_median": float(rate.median()),
                "mean_ihp_flood_rate": float(selected_values.mean()),
                "universe_mean": float(rate.mean()),
                "mean_ratio": float(selected_values.mean() / rate.mean()),
            }
        )
    return pd.DataFrame(threshold_rows), summary


def plot_reproduced_results(
    shapley_table: pd.DataFrame,
    screen_summary: dict[str, float | int],
    output_path: Path,
) -> None:
    os.environ.setdefault(
        "MPLCONFIGDIR", str(PACKAGE_ROOT / ".cache" / "matplotlib")
    )
    import matplotlib.pyplot as plt

    labels = {
        "ihp_flood": "IHP registration rate",
        "claims": "NFIP claims",
        "uptake": "NFIP uptake",
    }
    colors = {"M": "#4477AA", "H": "#228833", "E": "#BBBBBB"}
    figure, axes = plt.subplots(1, 3, figsize=(14.5, 4.6))

    x_positions = np.arange(len(OUTCOMES))
    width = 0.24
    for offset, block in zip([-width, 0.0, width], ["M", "H", "E"], strict=True):
        values = [
            float(
                shapley_table.query("outcome == @outcome and block == @block")[
                    "share_of_full_r2"
                ].iloc[0]
            )
            for outcome in OUTCOMES
        ]
        axes[0].bar(
            x_positions + offset,
            values,
            width=width,
            color=colors[block],
            label={"M": "Mapped zones", "H": "Hydrology", "E": "Built exposure"}[block],
        )
    axes[0].set_xticks(x_positions, [labels[name] for name in OUTCOMES])
    axes[0].set_ylabel("Share of full-model out-of-fold R2")
    axes[0].set_title("a. Sources of model performance", loc="left")
    axes[0].legend(frameon=False)

    increment_rows = []
    for outcome in OUTCOMES:
        full = float(
            shapley_table.query("outcome == @outcome and block == 'H'")[
                "full_r2"
            ].iloc[0]
        )
        hydrology_increment = float(
            shapley_table.query("outcome == @outcome and block == 'H'")[
                "delta_r2_given_others"
            ].iloc[0]
        )
        mapped_increment = float(
            shapley_table.query("outcome == @outcome and block == 'M'")[
                "delta_r2_given_others"
            ].iloc[0]
        )
        increment_rows.append((full, hydrology_increment, mapped_increment))
    y_positions = np.arange(len(OUTCOMES))
    axes[1].barh(
        y_positions - 0.18,
        [row[1] for row in increment_rows],
        height=0.34,
        color=colors["H"],
        label="Add hydrology after M + E",
    )
    axes[1].barh(
        y_positions + 0.18,
        [row[2] for row in increment_rows],
        height=0.34,
        color=colors["M"],
        label="Add mapped zones after H + E",
    )
    axes[1].set_yticks(y_positions, [labels[name] for name in OUTCOMES])
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Increase in out-of-fold R2")
    axes[1].set_title("b. Added information", loc="left")
    axes[1].legend(
        frameon=False,
        fontsize=8,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
    )

    categories = ["Selected tracts", "High recorded\nburden subset"]
    counts = [
        int(screen_summary["primary_screen_rows"]),
        int(screen_summary["high_recorded_burden_rows"]),
    ]
    bars = axes[2].bar(categories, counts, color=["#EE7733", "#AA3377"])
    axes[2].bar_label(bars, labels=[f"{value:,}" for value in counts], padding=3)
    axes[2].set_ylim(0, max(counts) * 1.16)
    axes[2].set_ylabel("Number of observations")
    axes[2].set_title(
        "c. Exploratory screen\n"
        "Selected mean IHP rate / sample mean: "
        f"{screen_summary['selected_to_universe_mean_ratio']:.2f}",
        loc="left",
        fontsize=11,
    )

    figure.tight_layout()
    figure.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def run(args: argparse.Namespace) -> None:
    started = time.time()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = load_analysis_data(args.data.resolve())
    log(f"Loaded {len(frame):,} observations")

    fits, predictions = fit_model_grid(frame, threads=args.threads)
    shapley_table = calculate_shapley_table(fits)
    intervals = bootstrap_intervals(
        frame,
        predictions,
        shapley_table,
        repetitions=args.bootstrap_reps,
    )
    thresholds, screen_summary = screen_results(frame, predictions)

    fits.to_csv(output_dir / "block_model_metrics.csv", index=False)
    shapley_table.to_csv(output_dir / "shapley_attribution.csv", index=False)
    intervals.to_csv(output_dir / "asymmetry_intervals.csv", index=False)
    thresholds.to_csv(output_dir / "screen_thresholds.csv", index=False)
    (output_dir / "screen_summary.json").write_text(
        json.dumps(screen_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    score_frame = pd.DataFrame({"record_id": frame["record_id"]})
    for outcome_name in OUTCOMES:
        for combination in MODEL_COMBINATIONS:
            score_frame[f"oof_{outcome_name}_{combination.replace('+', '')}"] = (
                predictions[(outcome_name, combination)]
            )
    write_parquet(score_frame, output_dir / "oof_scores.parquet")

    if not args.skip_figure:
        plot_reproduced_results(
            shapley_table, screen_summary, output_dir / "reproduced_core_results.png"
        )

    metadata = {
        "bootstrap_repetitions": args.bootstrap_reps,
        "elapsed_seconds": round(time.time() - started, 3),
        "model_random_state": RANDOM_STATE,
        "python": platform.python_version(),
        "rows": len(frame),
        "state_grouped_folds": N_SPLITS,
        "threads": args.threads,
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    log(f"Wrote results to {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="Path to the included analysis-ready Parquet file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for reproduced results",
    )
    parser.add_argument(
        "--bootstrap-reps",
        type=int,
        default=500,
        help="Number of state-cluster bootstrap repetitions",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=-1,
        help="Threads passed to XGBoost; -1 uses all available cores",
    )
    parser.add_argument(
        "--skip-figure",
        action="store_true",
        help="Skip the compact reproduced-results figure",
    )
    arguments = parser.parse_args()
    if arguments.bootstrap_reps < 1:
        parser.error("--bootstrap-reps must be positive")
    return arguments


if __name__ == "__main__":
    run(parse_args())
