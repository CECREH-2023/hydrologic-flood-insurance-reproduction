#!/usr/bin/env python3
"""Create the public analysis-ready file from the complete derived dataset."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from reproduce import (
    BUILT_EXPOSURE_FEATURES,
    HYDROLOGY_FEATURES,
    MAPPED_ZONE_FEATURES,
    OUTCOMES,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PACKAGE_ROOT / "data" / "analysis_ready.parquet"

RELEASE_FIELDS = list(
    dict.fromkeys(
        [
            "state_fips",
            "in_universe",
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
    )
)

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(source: Path, output: Path) -> None:
    table = pq.read_table(source, columns=RELEASE_FIELDS)
    frame = pd.DataFrame(table.to_pydict())
    frame = frame.loc[frame["in_universe"].astype(bool)].drop(
        columns="in_universe"
    )
    frame = frame.reset_index(drop=True)
    frame.insert(0, "record_id", range(1, len(frame) + 1))

    prohibited = [
        column
        for column in frame.columns
        if column != "record_id"
        and any(part in column.lower() for part in PROHIBITED_FIELD_PARTS)
    ]
    if prohibited:
        raise ValueError(f"Release fields contain prohibited names: {prohibited}")
    if len(frame) != 83_360:
        raise ValueError(f"Expected 83,360 release rows, found {len(frame):,}")

    output.parent.mkdir(parents=True, exist_ok=True)
    arrays = {column: pa.array(frame[column].tolist()) for column in frame.columns}
    metadata = {
        b"title": b"Hydrologic flood-insurance analysis-ready release",
        b"release_scope": b"Deidentified tract-analysis rows for statistical reproduction",
        b"privacy": b"No direct tract identifiers, applicant records, or raw event counts",
        b"source_file": source.name.encode("utf-8"),
    }
    release_table = pa.table(arrays).replace_schema_metadata(metadata)
    pq.write_table(
        release_table,
        output,
        compression="zstd",
        compression_level=9,
    )
    print(
        f"Wrote {len(frame):,} rows and {len(frame.columns)} columns to {output}\n"
        f"SHA-256: {sha256(output)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Complete derived hydrologic analysis Parquet file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination for the public analysis-ready file",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    build(arguments.source.resolve(), arguments.output.resolve())
