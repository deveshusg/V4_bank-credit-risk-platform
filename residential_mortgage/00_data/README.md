# Module 0: Data Ingestion, Macro Tables & Stratified Sample DB

Builds and validates the base data stores in dependency order under `00_data/scripts/`.

| # | Script | What it does | Reads | Writes |
|---|---|---|---|---|
| 00 | `field_map.py` | 113-field Fannie Mae schema map & column types (`loans_table` + `loan_monthly_view`) | `references/fannie_mae_glossary_file_layout.pdf` | — |
| 01 | `01_convert_raw_to_parquet.py` | Converts raw CSVs from `Performance_All.zip` into ZSTD Parquet + `.conversion.json` | `raw/fannie_mae/Performance_All.zip` | `raw/parquet/YYYYQn.parquet` |
| 02 | `02_build_base_tables.py` | Materializes `loans_table` and refreshes `loan_monthly_view`; 7 atomic checks per quarter | `raw/parquet/` | `processed/mortgages.duckdb` |
| 03 | `03_build_macro_tables.py` | Loads FRED (`FEDFUNDS`, `UNRATE`) + FHFA (`hpi_master.csv`) and PRA LGD discount rates; 6 checks | `raw/macro/` | Target DB (`sample` default, or `--full`) |
| 04 | `04_build_sample_db.py` | Builds self-contained 0.03% per-quarter stratified `mortgages_sample.duckdb` (~55 MB, GitHub-tracked) | `processed/mortgages.duckdb` | `processed/module_outputs/00_data/mortgages_sample.duckdb` |

## Subfolders
- `scripts/`: Runnable data pipeline scripts (`01_`–`04_`) and `field_map.py`.
- `raw/`: Source zip, FRED/FHFA CSVs, and extracted Parquets (gitignored; preserved via `.gitkeep`).
- `processed/`: Full `mortgages.duckdb` (gitignored) and `module_outputs/` (holds `mortgages_sample.duckdb` + all downstream module outputs separated into `sample/` and `full/`).
- `tests/`, `notebooks/`, `docs/`: Module test, notebook, and private local design folders.
