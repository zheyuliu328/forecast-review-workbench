# Forecast Review Workbench

[中文使用指南](docs/QUICKSTART.zh-CN.md)

A local browser tool for reviewing **your own forecast files**. Bring an actual-values table, one to five candidate prediction tables and an optional supplied baseline. Map their columns, check coverage and definitions, compare errors on the same sample, write a review decision, and download an offline evidence bundle.

The application reads CSV and value-only Excel files. Files travel only between your browser and a Python process on this computer; there is no external upload, account, API key, telemetry or runtime data download.

![Actual workbench with invented forecasts, shared-sample metrics and visible date gaps](docs/images/workbench.png)

The first release has 89 passing Python tests, real CSV/XLSX browser acceptance, an independently checked export and documented limits. [Verification record](docs/VALIDATION.md) · [Recorded local evidence](docs/local-verification.json).

## Open the tool

Python 3.10 or newer. From this checkout:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
forecast-review
```

The browser opens automatically. On macOS, `start.command` performs the first local setup and opens the installed tool; first installation can require internet access for Python packages. Subsequent use runs offline. After updating the source, reinstall with `python -m pip install .`.

## A real file workflow

1. Select your actual-values file and candidate prediction files. Choose the Excel sheet and header row, then map date, value and optional entity columns. Headers can differ between files.
2. Declare the inclusive evaluation range, frequency, target, unit, forecast horizon and target transformation. Entity-based data require an explicit list of expected entities.
   The mapped dates are target periods; horizon does not shift them.
3. Review missing, duplicate, invalid and out-of-range records. Conflicting definitions block numerical comparison. Missing values are never filled with zero.
4. Explicitly accept the available common sample. MAE, RMSE and signed bias then use exactly the same valid keys for every candidate and the optional baseline.
5. Inspect the plot, period segments and row diagnostics, add a manual decision with its reasoning, and download the ZIP. Extract it and open `report.html` without the application.

Changing inputs, mappings, definitions, source declarations or sample acceptance invalidates old review notes. Downloading recomputes the review and refuses stale notes.

## Try the coverage trap

The optional **Explore an example** uses newly invented files with 12 expected months: candidate A covers nine, candidate B covers ten, and only seven are shared. A appears better on its own easier sample; B has lower error on the common seven months. All five excluded months remain visible. These are deliberately constructed forecasts, not fitted model results.

The tool does not depend on this fixture: the same file pickers and mappings accept external CSV/XLSX. [Example files](examples) can also be selected manually.

## Evidence and automation

The export includes readable HTML, common-sample metrics, every expected row, every mapped input row, issues, exact JSON, declarations, manual notes and SHA-256 fingerprints. CSV text is escaped against spreadsheet formula execution; JSON retains exact selected values. Original files are never changed.

For a reproducible command-line example:

```sh
forecast-review --example --output /tmp/forecast-review-new
```

For your own saved settings, use `forecast-review --review request.json --output /path/to/new-directory`. File objects can use `{"path": "actual.csv"}` relative to the settings file. [The input contract](docs/CONTRACT.md) documents mappings and declarations. Existing output paths are refused; a complete bundle publishes atomically. Exit 0 means a common-sample comparison was computed, 1 means a pending review was exported, and 2 means execution failed. No exit code approves a model.

## Scope

- Continuous targets and one declared horizon; daily, monthly or quarterly period keys, with optional exact text entity IDs.
- Values must already occupy the same target space. The tool does not train models, fit baselines, infer Excel formula freshness, convert units or invert transformations.
- A supplied prediction file cannot establish that training was independent, free of leakage, or untouched by holdout inspection. Source definitions and manual opinions remain caller declarations.
- Available-sample metrics are diagnostic only. Coverage gaps restrict the meaning of the common-sample conclusion, even when its error is small.
- The local server binds to loopback only. It is a personal desktop tool, not a network deployment or multiuser service.

An independent project by Zheyu Liu, implemented with AI assistance and explicit reviewable checks. All bundled examples are newly invented. No employer/client code, templates, business data or private history are included. [Methods and source declaration](docs/DATA_AND_METHODS.md) · [Verification record](docs/VALIDATION.md).

## Development

```sh
python -m pip install '.[dev]'
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
python -m build --wheel
```

The [browser acceptance check](docs/VALIDATION.md) uses real CSV/Excel file selection, downloads and independently recomputes the evidence, and checks desktop/narrow layouts. Node is needed for development browser tests only.

MIT licensed.
