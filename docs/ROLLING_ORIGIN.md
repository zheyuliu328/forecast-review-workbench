# Rolling-origin review (schema 2)

This browser and CLI/API capability keeps forecast origin, target period and entity distinct. It reviews supplied predictions; it does not fit models or certify that a prediction existed at its declared origin. The public browser supports this mode and the original example.

## Run an original example

Install the current repository package, then run:

```sh
forecast-review --review examples/rolling-origin/request.json --output /tmp/new-origin-review
```

Use a new output directory. Open report.html without the application. All example rows are independently invented. Schema 1 requests retain their existing target-period workflow.

The example has January and February forecast origins and horizons 1 and 2. Three actual target periods support four forecast keys: March is predicted from two different origins. Neither forecast is a duplicate of the other. Actual input rows remain three; repeated references do not inflate the input inventory.

| Horizon | A MAE | B MAE | Common forecast keys |
|---|---:|---:|---:|
| 1 | 1 | 1.5 | 2 |
| 2 | 2 | 1 | 2 |

A leads at horizon 1, B at horizon 2. Aggregate A MAE is 1.5, RMSE sqrt(2.5), bias 0. Aggregate B MAE is 1.25, RMSE sqrt(1.75), bias 0.75. These aggregates give every forecast key equal weight; overlapping targets are not independent observations. All common metrics remain absent until accept_common_sample is explicitly true.

## Declare the universe before comparing

- schema_version is 2. scope uses origin_start, origin_end, frequency and entities. The expected universe is the inclusive origin range × selected horizons × exact entity IDs, limited to 5,000 forecast keys.
- contract uses target, unit, transformation and horizons (a nonempty list of distinct positive integer periods). The list is normalized into ascending order. Each prediction/baseline source declares the same fields plus frequency. Actual source contracts declare target, unit, transformation and frequency without a forecast horizon.
- Actual mapping uses date (target period), value and optional entity. Prediction and baseline mappings additionally require origin; horizon may name a column or be null to derive the distance from origin to target. All mapped columns must be distinct.
- Monthly and quarterly horizons use calendar periods. Daily horizons use calendar days, including weekends and holidays. Horizon columns must agree with the derived distance. Targets at or before the origin, invalid dates, out-of-scope origins and unselected horizons are retained as diagnostics and excluded.
- Actual uniqueness is target/entity. Prediction uniqueness is origin/target/entity. All copies of a duplicate key are rejected; no first-row selection or averaging occurs. A missing or duplicate actual affects every forecast referencing that actual key.
- Common keys require a valid actual and every candidate and supplied baseline. Segments retain target-period meaning. Per-horizon metrics appear before aggregate metrics in the report. Source contracts and explicit sample acceptance remain necessary.

## Evidence and limits

The original regression fixtures cover horizon-dependent ranking, sample-coverage ranking reversal, overlapping targets, actual and forecast duplicates, malformed and non-forward origins, declared-horizon mismatch, leap days, year/quarter boundaries, exact entity IDs, baseline definition conflicts, stale fingerprints and report CSV identities. A read-only independent review also compared 100 fixed-seed missingness combinations against a separate set-intersection and Decimal MAE oracle.

An invalid-origin diagnostic originally overstated outside-scope row counts. It was corrected so an unparseable key is not asserted to be outside an otherwise valid universe; the malformed row remains visible. Neither this correction nor test success establishes real forecasting skill.

Origin labels do not establish creation timestamps, training-data vintages, release calendars, revision policies or independence. No significance test treating overlapping errors as independent is supplied. Input hashes detect changes, not authenticity. Software acceptance and external human adoption remain separate.

The bundle includes horizon-metrics.csv, every expected forecast key with origin and horizon, every original mapped row, exclusions, contracts and fingerprints. Existing schema 1 CSV column positions are unchanged; schema 2 identity fields are appended.

## Browser task and verified release

Open [Forecast Review](https://forecast-review-zheyuliu.mystic-pear-2111.chatgpt.site/) and select **Try the rolling-origin example**. Inspect the four forecast keys and their shared actual rows, accept the common sample, then view results. Horizon 1 favors A; horizon 2 favors B. Change the chart horizon to inspect one lead time at a time. Download the full package and open report.html offline.

For your own files, choose **Compare forecast origins and horizons** before mapping. Select each forecast's origin, target and numeric value columns; a horizon column is optional. Enter the originally expected origin range and comma-separated horizons. Confirm source definitions only when they actually match. Changing inputs invalidates previous exports and requires a fresh common-sample decision. Schema 1 examples and experiment transfers still use the single-target mode.

Runtime d72ef926bd91a5fb2fcd4137d218dcf47adf85e1 passed [GitHub checks 37042264709](https://github.com/zheyuliu328/forecast-review-workbench/actions/runs/37042264709): 150 tests on Python 3.10/3.12/3.14, normal installed execution outside the checkout, dependency audit, local application browser workflows and static browser workflows. The static task includes desktop/narrow layout, both chart horizons, malformed external horizon file, corrected external file, stale exports, mode switching and ZIP contents; no file uploads or external requests occurred.

The production deployment was exercised on 2026-10-03 HKT: load example → inspect origins → accept four common keys → compare both horizons → switch chart to horizon 2 → download ZIP. The downloaded results and every manifest digest were checked. Publication IDs are in publication.json. These are agent-operated software acceptance checks, not external human adoption.
