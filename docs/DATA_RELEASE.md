# Public release boundary

## Included

- One analysis-ready Parquet file with 83,360 release rows and 39 approved fields.
- State codes used for grouped model evaluation.
- Public-source mapped-zone, soil, precipitation, land-cover, structure-count, density, and tract-area predictors.
- Derived rates and their log transforms used by the primary models.
- Population and housing-unit fields needed to reproduce aggregate screen totals.
- Reference statistical results and publication-facing figures.

## Excluded

- Direct census tract, county, ZIP Code, address, or coordinate identifiers.
- Applicant-level IHP records or household-level insurance indicators.
- Raw registration, claim, or policy counts.
- Claim payments, award amounts, premiums, coverage amounts, or other administrative monetary fields.
- Crosswalk keys that would restore tract identity to the release rows.
- Raw and intermediate geospatial data.
- Working notes, review records, logs, draft manuscripts, and machine-specific configuration.

The release uses a sequential `record_id` solely to align generated out-of-fold scores with the included rows. It carries no source geography meaning.

## Why the release is narrower than the source data

The model requires tract-level predictors and outcomes, but public reproduction does not require the identifiers or source-record detail used to construct them. Removing those fields reduces re-identification and disclosure risk while preserving the primary statistical computation.

The file still contains state codes because the study’s evaluation design leaves states out of training. The package should therefore be treated as an aggregate research dataset, not as anonymous microdata.

## Rules for future extracts

This release decision applies only to the included file. Any later location-linked administrative extract should receive a separate review before public distribution. At minimum:

- Aggregate records before release and avoid applicant-level rows.
- Base suppression on source-record counts before fractional geographic allocation.
- Suppress cells with fewer than 10 contributing source records and apply complementary suppression where totals could reveal them.
- Remove amounts, direct identifiers, and crosswalk keys unless they are essential and separately approved for release.
- Document any changed fields, thresholds, and linkage risks in a new release note.

These package rules are conservative publication controls, not a legal or institutional determination about every possible reuse of the source products.
