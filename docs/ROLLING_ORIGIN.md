# Rolling-origin review (schema 2)

This native CLI/API capability keeps forecast origin, target period and entity distinct. It reviews supplied predictions; it does not fit models or certify that a prediction existed at its declared origin. Browser entry and deployed UI support are the next delivery stage and are not claimed here.

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
