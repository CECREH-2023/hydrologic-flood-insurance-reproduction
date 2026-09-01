# Data provenance

## Reproduction data

`data/analysis_ready.parquet` is a purpose-built statistical release with 83,360 rows and 39 fields. Each row represents one observation in the 2020 census-tract analysis universe, but the file does not include a tract identifier. `record_id` is a sequential release-row key and cannot be joined to the source geography from this repository.

The file is sufficient to reproduce the primary model comparison, Shapley decomposition, state-grouped uncertainty intervals, and tract-screen totals. It is not intended to reproduce the full geospatial extraction and historical crosswalk pipeline.

## Source products used in the reproduced analysis

| Source | Provider | Study role | Study vintage | Official access |
|:---|:---|:---|:---|:---|
| TIGER/Line tracts and geographic relationship files | U.S. Census Bureau | 2020 tract analysis geography and geographic harmonization | 2010 and 2020 relationships; 2020 tract boundaries | [Census TIGER/Line](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) |
| American Community Survey five-year estimates | U.S. Census Bureau | Household, population, and housing denominators | 2010–2024 | [Census Data API](https://www.census.gov/data/developers/data-sets/acs-5year.html) |
| IHP Valid Registrations v2 | FEMA OpenFEMA | Flood-damage registrations | 2010–2024 | [OpenFEMA dataset](https://www.fema.gov/openfema-data-page/individuals-and-households-program-valid-registrations-v2) |
| Disaster Declarations Summaries v2 | FEMA OpenFEMA | County-level declaration exposure | 2010–2024 | [OpenFEMA dataset](https://www.fema.gov/openfema-data-page/disaster-declarations-summaries-v2) |
| FIMA NFIP Redacted Claims v2 | FEMA OpenFEMA | Insured flood claims | 2010–2024 | [OpenFEMA dataset](https://www.fema.gov/openfema-data-page/fima-nfip-redacted-claims-v2) |
| FIMA NFIP Redacted Policies v2 | FEMA OpenFEMA | Active NFIP policy terms | 2024 | [OpenFEMA dataset](https://www.fema.gov/openfema-data-page/fima-nfip-redacted-policies-v2) |
| National Flood Hazard Layer | FEMA | SFHA and flood-zone area shares | Extracted 3 March 2026 | [FEMA Flood Map Service Center](https://msc.fema.gov/portal/advanceSearch) |
| Gridded Soil Survey Geographic database | USDA Natural Resources Conservation Service | Soil hydrology, drainage, water table, storage, and slope attributes | 2025 state databases | [gSSURGO](https://www.nrcs.usda.gov/resources/data-and-reports/gridded-soil-survey-geographic-gssurgo-database) |
| PRISM time-series precipitation | PRISM Climate Group | Mean and maximum annual precipitation | 2010–2024 annual grids | [PRISM data](https://prism.oregonstate.edu/) |
| Annual National Land Cover Database | USGS/MRLC | Developed-land share | Through 2024 | [Annual NLCD](https://www.mrlc.gov/data/project/annual-nlcd) |
| National Structure Inventory | U.S. Army Corps of Engineers | Total and residential structure counts | 2022 | [NSI downloads](https://nsi.sec.usace.army.mil/downloads/) |

## Transformation chain

1. Establish the 2020 national tract universe for the 50 states and District of Columbia.
2. Harmonize historical tract-linked records to the 2020 geography using Census relationship files and population or housing weights where required.
3. Aggregate public FEMA IHP registrations, declarations, NFIP claims, and NFIP policy terms to the tract analysis unit.
4. Calculate the declaration-conditioned IHP registration rate per 1,000 household-declaration exposures, cumulative IHP registrations per 1,000 households, NFIP claims per 1,000 housing units, and active 2024 policy terms per 1,000 housing units.
5. Overlay NFHL polygons and calculate six mapped-zone area-share features.
6. Overlay gSSURGO map units with tracts. Calculate categorical shares and area-weighted continuous soil attributes using mapped-soil area as the denominator. Preserve unavailable attributes as missing.
7. Summarize annual PRISM precipitation over 2010–2024 and calculate mean and maximum annual precipitation measures.
8. Combine Annual NLCD developed-land share, 2022 NSI structure counts, ACS densities, and tract land area as the built-exposure block.
9. Apply `log(1 + rate)` to the three modeled outcomes, retain observations meeting the analysis-universe rules, and assign state fold groups.
10. Export the approved release fields, omit direct tract identity and raw administrative counts, and assign a sequential `record_id`.

## Quality controls represented in this package

- Exact expected row and column counts.
- Unique release-row IDs and 51 state fold groups.
- Missing soil attributes remain missing rather than being converted to zero.
- Reference output comparisons for every model combination and Shapley contribution.
- Exact screen-count and population/housing-total checks.
- Automated checks for direct geography fields, source-record details, secrets, machine-specific paths, and macOS metadata.

## Provider notices

The source products remain governed by their providers’ conditions. This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau. FEMA’s OpenFEMA IHP release is a public-use dataset from which FEMA reports that personally identifiable information has been removed; this repository nevertheless does not redistribute applicant-level rows.
