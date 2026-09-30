# Forecast Review: quick start

[Open the tool](https://forecast-review-zheyuliu.mystic-pear-2111.chatgpt.site) · [Tools and status](https://forecast-review-zheyuliu.mystic-pear-2111.chatgpt.site/tools.html)

No installation or account is required. Select **Try an example** or use your own CSV/Excel files. The first run downloads about 17 MB of calculation components. Your files are processed in the browser.

## Compare existing forecasts

1. Select actual values and a prediction file. Add other predictions or a baseline as needed. Each file needs date and value columns; Excel also offers worksheet and header-row selection.
2. Check the date/value mappings and continue. Declare the target, unit and full expected period. Dates represent the periods being forecast; the tool does not shift them automatically.
3. Confirm consistent definitions across files before applying shared definitions. Preserve genuine differences and investigate their sources.
4. Check comparable coverage. Inspect missing values, duplicates and exclusions, then explicitly accept the common sample.
5. View MAE, RMSE and bias on identical records. Add review notes as needed and download the review bundle.

The example expects 12 months but shares only 7. A appears better on its own sample; B has lower error on the common sample. Five excluded months remain outside the conclusion.

Changing files, mappings, scope or units invalidates old results and sample acceptance; notes require reconfirmation. Multi-entity data requires the complete expected entity ID list. Leading zeros and whitespace are meaningful.

## Run historical regression experiments

1. Open **Other tasks**, then the regression experiment page. Select monthly history and date/actual-value columns.
2. Choose 1–5 raw features with lag and publication-delay declarations. Do not pre-shift the source columns; the tool applies the lags.
3. Specify the development end month and time split. Run development experiments. Five features produce 15 one/two-factor candidates plus two baselines; failed candidates remain visible.
4. Review development results before explicitly revealing the holdout. The development-selected candidate is not reselected using holdout scores.
5. Download the experiment bundle or transfer predictions into forecast review. Common-sample acceptance is still required after transfer.

Months must be consecutive and unique. Missing features exclude affected common-sample months; missing actuals, formulas and invalid numbers block execution. Only monthly linear-regression candidates are supported. Target transformation is a declaration, not an automatic inverse transformation. A previously seen holdout does not become unseen when rerun.

## Reconcile line items and totals

1. Select reference and comparison files. Confirm record ID and value columns.
2. Confirm date, measure, risk type, tenor, currency and unit definitions, then set tolerances.
3. Run reconciliation. Groups are calculated only after explicit additivity acceptance; reported totals may be supplied for each side.
4. Inspect line, group and total results separately. Offsetting differences do not make out-of-tolerance lines pass. Reviewer acceptance does not change calculation status.
5. Download the reconciliation bundle, preserving source values, provenance, row differences and explanations.

Completeness uses the union of both files: records missing from both cannot be detected. Relative tolerance is a proportion; 0.001 means one tenth of one percent.

## Files and reports

- Limits: 10 MiB, 10,000 rows and 100 columns per file; 40 MiB per request. Processing stops after two minutes and can be cancelled.
- Closing or refreshing discards current results. Experiment transfer temporarily uses this tab's session storage and removes the data after the destination reads it.
- Forecast bundles contain selected field values, row diagnostics and source hashes. Experiment and reconciliation bundles include original-file snapshots, including unmapped columns and other worksheets. Treat them with the same sensitivity as the original files.
- Extract the bundle and open report.html. CSV/JSON files and hash manifests support recomputation.

