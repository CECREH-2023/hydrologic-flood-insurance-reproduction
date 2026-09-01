#!/usr/bin/env python3
"""Validate the public reproduction package and generated results."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from reproduce import required_columns


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PACKAGE_ROOT / "data" / "analysis_ready.parquet"
GENERATED = PACKAGE_ROOT / "results" / "generated"
REFERENCE = PACKAGE_ROOT / "results" / "reference"

EXPECTED_ROWS = 83_360
EXPECTED_COLUMNS = 39
EXPECTED_SCREEN = {
    "analysis_rows": 83_360,
    "state_groups": 51,
    "primary_screen_rows": 1_348,
    "high_recorded_burden_rows": 550,
    "selected_population": 4_820_026.2899,
    "selected_housing_units": 2_142_189.6542,
    "selected_to_universe_mean_ratio": 2.784004767683808,
}

REQUIRED_FILES = [
    "README.md",
    "CITATION.cff",
    "MANIFEST.sha256",
    "environment.yml",
    "data/README.md",
    "data/VARIABLES.csv",
    "data/analysis_ready.parquet",
    "docs/DATA_PROVENANCE.md",
    "docs/DATA_RELEASE.md",
    "docs/REPRODUCING.md",
    "figures/fig01_predictive_asymmetry.png",
    "figures/fig02_damage_outside_sfha.png",
    "figures/fig03_national_flood_geographies.png",
    "figures/fig04_screen_robustness.png",
    "results/reference/asymmetry_intervals.csv",
    "results/reference/block_model_metrics.csv",
    "results/reference/screen_thresholds.csv",
    "results/reference/shapley_attribution.csv",
    "scripts/build_release_data.py",
    "scripts/reproduce.py",
    "scripts/run_all.py",
    "scripts/verify_package.py",
]

PROHIBITED_FIELD_PARTS = (
    "geoid",
    "county",
    "zip",
    "applicant",
    "address",
    "amount",
    "paid",
    "registration_count",
    "claim_row_count",
    "policy_count",
)

TEXT_SUFFIXES = {".cff", ".csv", ".gitignore", ".md", ".py", ".yaml", ".yml"}
DISALLOWED_LITERALS = (
    "/" + "Users/",
    "/" + "Volumes/",
    ".co" + "dex",
    ".cl" + "aude",
    "jrand" + "re2",
)
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"][^'\"]+"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_close(actual: float, expected: float, label: str) -> None:
    if not np.isclose(actual, expected, rtol=1e-8, atol=1e-10):
        raise AssertionError(f"{label}: expected {expected}, found {actual}")


def check_required_files() -> dict[str, int]:
    missing = [path for path in REQUIRED_FILES if not (PACKAGE_ROOT / path).is_file()]
    if missing:
        raise AssertionError(f"Missing required files: {missing}")
    return {"required_files": len(REQUIRED_FILES)}


def check_release_data() -> dict[str, int]:
    table = pq.read_table(DATA_PATH)
    columns = table.column_names
    if table.num_rows != EXPECTED_ROWS or table.num_columns != EXPECTED_COLUMNS:
        raise AssertionError(
            f"Expected {EXPECTED_ROWS} x {EXPECTED_COLUMNS}; "
            f"found {table.num_rows} x {table.num_columns}"
        )
    if columns != required_columns():
        raise AssertionError("Release schema or column order differs from the model schema")
    prohibited = [
        column
        for column in columns
        if column != "record_id"
        and any(part in column.lower() for part in PROHIBITED_FIELD_PARTS)
    ]
    if prohibited:
        raise AssertionError(f"Prohibited release fields: {prohibited}")

    frame = pd.DataFrame(table.select(["record_id", "state_fips"]).to_pydict())
    if frame["record_id"].isna().any() or not frame["record_id"].is_unique:
        raise AssertionError("record_id must be complete and unique")
    if frame["state_fips"].nunique() != 51:
        raise AssertionError("Expected 51 state fold groups")
    return {
        "release_rows": table.num_rows,
        "release_columns": table.num_columns,
        "state_groups": int(frame["state_fips"].nunique()),
    }


def check_release_surface() -> dict[str, int]:
    sidecars: list[str] = []
    text_violations: list[str] = []
    secret_violations: list[str] = []
    text_files = 0

    for path in PACKAGE_ROOT.rglob("*"):
        relative = path.relative_to(PACKAGE_ROOT)
        if ".git" in relative.parts or ".cache" in relative.parts:
            continue
        if path.name.startswith("._") or path.name == ".DS_Store" or path.name == "__MACOSX":
            sidecars.append(str(relative))
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text_files += 1
        content = path.read_text(encoding="utf-8", errors="replace")
        for literal in DISALLOWED_LITERALS:
            if literal in content:
                text_violations.append(f"{relative}: {literal}")
        if SECRET_PATTERN.search(content):
            secret_violations.append(str(relative))

    if sidecars:
        raise AssertionError(f"macOS metadata found: {sidecars}")
    if text_violations:
        raise AssertionError(f"Machine-specific or excluded text found: {text_violations}")
    if secret_violations:
        raise AssertionError(f"Possible secrets found: {secret_violations}")
    return {"text_files_scanned": text_files, "sidecar_items": 0}


def compare_table(filename: str, keys: list[str]) -> int:
    expected = pd.read_csv(REFERENCE / filename).sort_values(keys).reset_index(drop=True)
    actual = pd.read_csv(GENERATED / filename).sort_values(keys).reset_index(drop=True)
    if list(actual.columns) != list(expected.columns):
        raise AssertionError(f"Column mismatch for {filename}")
    if len(actual) != len(expected):
        raise AssertionError(f"Row-count mismatch for {filename}")

    for column in expected.columns:
        if pd.api.types.is_numeric_dtype(expected[column]):
            if not np.allclose(
                actual[column].to_numpy(),
                expected[column].to_numpy(),
                rtol=1e-8,
                atol=1e-10,
                equal_nan=True,
            ):
                difference = np.nanmax(
                    np.abs(actual[column].to_numpy() - expected[column].to_numpy())
                )
                raise AssertionError(
                    f"Numerical mismatch for {filename}:{column}; max difference {difference}"
                )
        elif not actual[column].fillna("").equals(expected[column].fillna("")):
            raise AssertionError(f"Text mismatch for {filename}:{column}")
    return len(actual)


def check_generated_results() -> dict[str, int]:
    required_generated = [
        "asymmetry_intervals.csv",
        "block_model_metrics.csv",
        "oof_scores.parquet",
        "reproduced_core_results.png",
        "run_metadata.json",
        "screen_summary.json",
        "screen_thresholds.csv",
        "shapley_attribution.csv",
    ]
    missing = [name for name in required_generated if not (GENERATED / name).is_file()]
    if missing:
        raise AssertionError(f"Missing generated results: {missing}")

    counts = {
        "model_metric_rows": compare_table("block_model_metrics.csv", ["outcome", "combo"]),
        "shapley_rows": compare_table("shapley_attribution.csv", ["outcome", "block"]),
        "screen_threshold_rows": compare_table("screen_thresholds.csv", ["threshold"]),
    }

    metadata = json.loads((GENERATED / "run_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("bootstrap_repetitions") != 500:
        raise AssertionError("Reference validation requires 500 bootstrap repetitions")
    counts["interval_rows"] = compare_table("asymmetry_intervals.csv", ["statistic"])

    screen = json.loads((GENERATED / "screen_summary.json").read_text(encoding="utf-8"))
    for key, expected in EXPECTED_SCREEN.items():
        actual = screen[key]
        if isinstance(expected, int):
            if actual != expected:
                raise AssertionError(f"{key}: expected {expected}, found {actual}")
        else:
            assert_close(float(actual), expected, key)

    scores = pq.read_table(GENERATED / "oof_scores.parquet")
    if scores.num_rows != EXPECTED_ROWS or scores.num_columns != 22:
        raise AssertionError("Generated out-of-fold score table has the wrong dimensions")
    return counts


def check_manifest() -> dict[str, int | str]:
    manifest = PACKAGE_ROOT / "MANIFEST.sha256"
    if not manifest.exists():
        return {"manifest": "not yet created", "manifest_files": 0}

    checked = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        path = PACKAGE_ROOT / relative
        if not path.is_file():
            raise AssertionError(f"Manifest file is missing: {relative}")
        if sha256(path) != expected:
            raise AssertionError(f"Manifest checksum differs: {relative}")
        checked += 1
    return {"manifest": "verified", "manifest_files": checked}


def main() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"status": "pass", "checks": {}}
    checks = report["checks"]
    assert isinstance(checks, dict)
    checks["required_files"] = check_required_files()
    checks["release_data"] = check_release_data()
    checks["release_surface"] = check_release_surface()
    checks["generated_results"] = check_generated_results()
    checks["manifest"] = check_manifest()

    output = GENERATED / "validation_report.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Package verification passed. Report: {output}")


if __name__ == "__main__":
    main()
