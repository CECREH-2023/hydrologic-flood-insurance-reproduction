# Analysis-ready data

`analysis_ready.parquet` contains the approved statistical release used by `scripts/reproduce.py`.

| Property | Value |
|:---|---:|
| Rows | 83,360 |
| Columns | 39 |
| State fold groups | 51 |
| Direct tract identifiers | None |
| Applicant-level records | None |
| SHA-256 | `a2872b5b72cab54ec986bc7ed68edf512e60c341c8b465fd026401aaeb5db779` |

`record_id` is a sequential release key. It is not derived from a Census GEOID and cannot be used to recover tract identity from this repository. `state_fips` is retained because the evaluation design groups observations by state.

See [VARIABLES.csv](VARIABLES.csv) for field definitions and [../docs/DATA_RELEASE.md](../docs/DATA_RELEASE.md) for the release boundary.
