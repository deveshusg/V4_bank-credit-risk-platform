# How to run

Run every command from the repo folder (`E:\Repos\V4_bank-credit-risk-platform`) with the
repo's Python: `.venv\Scripts\python.exe`. Each script prints a short summary and ends with
PASS or FAIL.

## Module 1: data foundation (built)

| Step | Command | What it does | Time on the full data |
|---|---|---|---|
| 1 | `.venv\Scripts\python.exe residential_mortgage\00_data\convert_raw_to_parquet.py all` | Converts each quarter's text to a Parquet file, with a conversion record | about 9 hours |
| 2 | `.venv\Scripts\python.exe residential_mortgage\00_data\build_base_tables.py all` | Builds `loans_table`, the development subset and `loan_monthly_view`; 8 checks per quarter | about 5 hours |
| 3 | `.venv\Scripts\python.exe residential_mortgage\00_data\build_macro_tables.py` | Builds the interest rate, unemployment and house price tables; 6 checks | seconds |
| 4 | `.venv\Scripts\python.exe residential_mortgage\01_data_foundation\03_leakage_audit.py` | Classifies every field (allowed, lagged, quarantined) | seconds |
| 5 | `.venv\Scripts\python.exe residential_mortgage\01_data_foundation\04_feature_catalogue.py` | Writes the field register and `docs\module_1\feature_catalogue.md` | about 15 minutes |
| 6 | See below | Runs the EDA notebook | 1 to 3 hours |

Steps 1 and 2 skip quarters already done, so they can be stopped and run again.

**EDA notebook (step 6).** Set the Jupyter path, then run the notebook in place:

```
$env:JUPYTER_PATH = 'E:\Repos\V4_bank-credit-risk-platform\.venv\share\jupyter'
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace residential_mortgage\01_data_foundation\02_eda.ipynb --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=v4-credit-risk
```

For the 10% development subset, also set `$env:EDA_SAMPLE = '1'` and send the outputs
elsewhere with `$env:EDA_OUT`.

## Modules 2 to 8 (not built yet)

Each module folder has a README listing its planned scripts and what each needs first. The
commands are added here as each module is built.
