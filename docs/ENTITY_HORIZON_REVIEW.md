# Entity and horizon review

The native CLI/API and offline reports now expose `group_results` for both request schemas. The public browser also provides entity search, horizon filtering and pagination; version 5 was deployed and exercised on 2026-10-03. Input formats and existing aggregate metrics are unchanged.

## Complete an original task

Install this checkout normally (`python -m pip install .`), then run from any directory:

```sh
forecast-review --review /path/to/checkout/examples/entity-horizon/request.json --output /tmp/new-group-review
```

Choose a new output directory. The original invented CSV files are beside request.json. They represent two forecast origins, horizon 1 and two entities, with four common forecast keys. There are no trained models or real business observations.

| Entity | Actual | Baseline | Candidate A | Candidate B |
|---|---:|---:|---:|---:|
| Large | 1000 | 1100 | 1050 | 1075 |
| Small | 10 | 11 | 12 | 10.5 |

The same values repeat at both origins. A has pooled MAE 26 versus baseline 50.5: about 48.51% improvement. Yet Small has A MAE 2 versus baseline 1, a **100% deterioration**. B has pooled MAE 37.75 but improves Small by 50%. Pooled errors are in the declared unit; differing entity scales can dominate them. No automatic winner or model adoption decision follows.

## Read and reproduce the output

- Open report.html: the group table previews at most 100 groups, retaining expected/common/excluded counts and baseline explanations.
- Read group-metrics.csv for every entity, horizon and model. It retains reported precision; the HTML uses seven significant digits.
- Read results.json for the same groups and evaluation-rows.csv for the exact common observations. Every original mapped row remains in the bundle.
- Recalculate each group's MAE, RMSE and bias only on the already accepted global common keys. Baseline gain is `(baseline error - candidate error) / baseline error * 100`, separately for MAE and RMSE. The ratio is computed from unrounded internal errors, then reported to 40 significant digits. Recomputing the ratio from already rounded MAE/RMSE strings may lose tiny differences. This is not MASE or a training-period scaled error.

Groups are slices of the fixed global intersection, never newly selected model-specific samples. A missing baseline excludes that key for every candidate. Explicitly expected groups with no common rows remain visible. An absent baseline produces no relative gain; a zero baseline error produces an undefined gain and a reason, never infinity or a fabricated zero. Without accepted compatible definitions and common observations, group metrics remain absent.

## Limits

Each forecast key has equal weight in the existing aggregate. There is no default average of entity gains, cross-entity normalization or significance test. Overlapping target dates, related entities and post-hoc group selection can invalidate simple independence assumptions. Origin labels do not prove creation time or training vintage. A group with two common keys is a tiny descriptive example, not evidence of reliable forecast skill.

All fixtures are independently invented. Numerical checks, installed-package execution and automated/browser report review are software evidence, not external human adoption.

## Public browser task

Select **Try the hidden deterioration example**, explicitly accept the four common keys and open the results. Compare A's pooled gain of about 48.51% with the Small entity's -100% gain. Search for Small in the group table; this filters only the view. Download the review package and confirm group-metrics.csv still contains all six entity/model rows. The public release check verified these results and every exported manifest file digest.
