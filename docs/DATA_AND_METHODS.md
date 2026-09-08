# Data, methods and attribution

## What this tool implements

A review starts with a caller-defined expected universe: an inclusive period range, optionally crossed with explicitly named entities. A row is eligible only when actuals, every candidate and the optional supplied baseline each have exactly one valid observation for its key. Missing observations remain in the expected denominator. Duplicate keys are never paired arbitrarily.

The date column is the **target/evaluation period**. It is not the forecast creation date. Horizon is a consistency declaration and never shifts dates or proves that forecasts existed before their target periods. Monthly and quarterly normalization is explicit; daily scope includes every calendar date, not only business days. Entity identifiers must be text and are compared exactly, including leading zeros and spaces.

The reviewer must accept the common sample before comparison metrics are produced. Each forecast's available-sample metrics are separately labelled diagnostic and may use different rows. If any source declares a different target, unit, horizon, transformation or frequency, all numerical comparisons and overlaid plots are blocked. No automatic unit conversion, transformation inversion or missing-value imputation is performed.

For the same accepted observations, let `e = prediction - actual`:

| Measure | Formula | Interpretation |
| --- | --- | --- |
| MAE | `sum(abs(e)) / n` | Average absolute error in the declared target space |
| RMSE | `sqrt(sum(e²) / n)` | Root mean squared error; larger errors have more influence |
| Bias | `sum(e) / n` | Positive means average overprediction |
| Baseline gain | `(baseline_error - candidate_error) / baseline_error * 100` | Positive means smaller error; undefined when baseline error is zero |

The engine uses bounded decimal input and Decimal arithmetic with a 600-digit working context. Reported metrics are decimal strings with up to 40 significant digits. The UI and HTML report round values for readability; exact reported values and residuals remain in JSON/CSV. Period segments use the accepted common keys within each declared interval. An empty interval has no metric, rather than a manufactured zero. No automatic winner or model approval is generated.

## What is included in an export

The ZIP contains nine files: readable offline HTML, exact results JSON, manual notes, common-sample metrics CSV, all expected evaluation rows, every nonempty mapped input row, issues, mappings/declarations and a manifest. Raw source files remain separate; input byte hashes identify them. The export includes selected source values and should be handled as carefully as the inputs.

Source notes and definitions are caller declarations. Hashes detect byte changes but do not establish who supplied a file or authenticate its contents. A manual opinion is bound to the input/settings fingerprint. Changing the reviewed inputs or sample acceptance invalidates that opinion; the GUI requires explicit reconsideration even if a setting is later restored to its old value. Export recomputes the results before accepting notes.

Excel inputs are read only. Selected formulas are blocked even if cached values are present; provide a values-only extract. Formula-like CSV text is escaped for spreadsheet use, while controlled numerical result columns stay numeric. JSON preserves the selected raw field values. The application does not modify input files or existing output directories.

## Independent material and acknowledged reuse

All bundled data, field layouts, forecasts and tests are independently invented. The twelve-month example deliberately creates a coverage trap; it is not a fitted model, backtest, customer extract or evidence of predictive skill. The browser acceptance fixture independently uses five periods, two different CSV layouts and a two-sheet Excel file with its header on row 3.

The problem design draws on general reconciliation and model-review practices: explicit definitions, expected coverage, key alignment, comparable denominators and traceable opinions. No employer or customer code, templates, identifiers, data, screenshots or private repository history are included.

One small implementation is adapted from the author's public MIT-licensed [Financial Control Tower](https://github.com/zheyuliu328/financial-control-tower): atomic publication into a new directory without replacing an existing output. Its attribution is retained in `exporter.py`. The review engine, file contract, interface and fixtures are new implementations for this project.

## Primary technical references

- Python's [Decimal documentation](https://docs.python.org/3/library/decimal.html) explains controlled decimal precision and rounding.
- openpyxl's [read-only mode](https://openpyxl.readthedocs.io/en/stable/optimized.html) supports iterating workbooks without editing them. The tool separately checks ZIP sizes, XML, selected formulas and bounded rows/columns.
- Python's [HTTP server documentation](https://docs.python.org/3/library/http.server.html) describes the local transport used here. This application binds to loopback and adds bounded requests, Host/Origin checks and a per-process request token; it is a personal desktop tool, not a production network service.

These references support implementation choices, not the authenticity or suitability of supplied forecasts. Prediction files alone cannot prove training independence, absence of leakage, untouched holdouts, regulatory compliance or production readiness.
