# Executable workflow extensions

The public website uses the same calculation and export contracts through a browser-local Worker, with no upload API. The HTTP routes below apply only to the optional installed loopback application. Public requests are capped at 40 MiB; each file retains the 10 MiB / 10,000-row / 100-column bounds. A missing browser transport fails closed. See [browser release and privacy](WEB_RELEASE.md).


The original forecast-file review remains at `/`. `/experiments` prepares regression candidates and explicitly reveals a holdout; `/reconcile` compares financial result rows and their additive totals. All endpoints use the existing loopback access checks and request token. All supplied examples are newly invented.

## Regression browser boundary

Request: `{schema_version:1,title,file:{name,content_base64},sheet,header_row,mapping:{date,target,features:[{column,name,lag,release_delay}]},spec:{horizon,development_end,n_splits,validation_months,min_train,target:{name,unit,transformation}},source_note}`. Defaults are horizon 1, three development folds, 12 validation months per fold and 36 minimum training rows. One to five features become stable `f1` through `f5` IDs. Their values are raw observations for the row's month; the producer applies declared lags. Dates must cover a unique, consecutive monthly calendar. A feature's lag must be at least horizon plus release delay. Targets are assumed observable at period end. Values already occupy the declared target space; no inverse transformation occurs.

`GET /api/experiments/example` returns that request. `POST /api/experiments/prepare` returns a development result. `POST /api/experiments/reveal` accepts `{request,fingerprint}` from development and returns the holdout result. `POST /api/experiments/export` accepts `{request,fingerprint,stage}` and returns an evidence ZIP. `POST /api/experiments/transfer` accepts `{request,fingerprint,model_ids,baseline_id}` from a revealed run and returns `{request:forecastReviewRequest}` for the original reviewer. At most five successful candidates and one of the two baselines can be transferred; all candidates and failures remain in the experiment evidence. Transfer does not accept the common review sample on the user's behalf.

Results include `fingerprint`, `stage` (`development` or `holdout`), `selected_on_development`, `selection_fingerprint`, `data_fingerprint`, `protocol`, `coverage`, `candidates`, `folds`, `input_rows`, and `predictions`. Coverage has integer `raw`, `usable`, `excluded`; `development` and `holdout` each have `raw`, `usable`, `excluded`, and development also has `validation_usable`. Candidate fields are `id,name,role,features,status,reason,development,holdout,fit`; metrics contain `n,mae,rmse,bias`. Baseline IDs are `baseline-mean` and `baseline-persistence`. Each fold records model ID, training cutoff/periods, validation periods, metrics, status/reason and fit diagnostics. Full input rows retain raw and lagged values, source periods, exclusions and split. Prepare emits no holdout predictions or scores.

Model selection uses pooled development MAE among successful OLS candidates only, with stable ID tie-breaking. Baselines remain visible. Scaling and coefficients use training rows only. Each validation block's training target cutoff is no later than its first prediction origin. Holdout coefficients remain fixed, while lagged features and the persistence baseline update with information available at each origin. This is sequential prediction with frozen coefficients, not a one-time multistep forecast. A code-level time split cannot establish that a human has never inspected the supplied data.

## Financial comparison browser boundary

Request: `{schema_version:1,title,left,right,left_totals:null,right_totals:null,absolute_tolerance:'0.01',relative_tolerance:'0.0001',additive:false}`. Each source is `{name,file,sheet,header_row,mapping,defaults}`. Mappable fields are `record_id,date,measure,risk_type,tenor,currency,unit,value`. Row sources require a mapped record ID and value. Date, measure, currency and unit require either a mapped field or a nonempty default declaration; risk type and tenor may be empty. Reported-total sources have the same structure without record ID. Selected formulas, ambiguous identifiers and nonfinite numbers are retained as invalid records; originals are never edited.

`GET /api/reconcile/example` returns an invented request. `POST /api/reconcile` evaluates it. `POST /api/reconcile/export` accepts `{request,fingerprint,notes:[{record_key,decision,text,fingerprint}]}` and returns a ZIP. Decisions are `needs_evidence` or `accepted_difference`, with a nonblank reason. Manual opinions never change machine statuses.

The identity key is `(record_id,date,measure,risk_type,tenor)`; currency and unit are separately checked so a mismatch cannot become a numerical agreement. Numerical pass means `abs(challenger-reference) <= absolute_tolerance + relative_tolerance*abs(reference)`. Relative tolerance is a ratio, not a percentage. Numbers are bounded Decimal values. Coverage is the union of supplied keys, so a record missing from both inputs cannot be discovered without another source.

Result shape:

- `schema_version,title,fingerprint,additive,tolerances,sources,warnings`.
- `summary`: `expected,left_rows,right_rows,comparable,pass,breach,missing_left,missing_right,duplicate,invalid,definition_conflict,groups,group_attention,reported_totals_attention`.
- `rows`: `{record_key,identity:{record_id,date,measure,risk_type,tenor},reference,challenger,reference_currency,challenger_currency,reference_unit,challenger_unit,difference,absolute_difference,allowed_difference,status,reasons:[str],source_rows:{left:[int],right:[int]}}`. `record_key` is a stable string. Status is one of the summary's row statuses; every supplied row remains accounted for. Invalid identity rows have source-specific keys.
- `groups`: `{group_key,dimensions:{date,measure,risk_type,tenor,currency,unit},reference,challenger,reference_rows,challenger_rows,difference,absolute_difference,allowed_difference,status,offsetting_breaches,reasons:[str],record_keys:[str]}`. Only present when `additive` is exactly true. Status `pass` also requires all member row comparisons to pass; net agreement cannot cancel a bad or missing row. Grouping never mixes currency, unit, measure, risk type, tenor or date.
- `reported_totals`: `{side,group_key,dimensions,calculated,reported,difference,absolute_difference,allowed_difference,status,reasons,source_rows}` for every group supplied or expected from raw rows on that side. Duplicates, invalid totals and missing groups remain explicit. This verifies a supplied additive total against its own source rows, independently of the cross-source row comparison.
- `input_rows`: every nonempty row from each selected source, with `source_id,row,raw,values,errors,record_key,group_key`. `sources` retain names, hashes, row counts, mappings/default declarations and sheet/header selection.

A totals file does not imply additivity. If totals are provided without explicit additivity, reject the request. This is a generic additive reconciliation tool; it does not implement nonlinear margin aggregation or a proprietary pricing model.

## Expanded evidence rows and replay

The browser adapter expands kernel predictions into one model/month row with `period,split,fold,model_id,actual,prediction,residual,origin,training_cutoff`. It joins original source `row` and `raw` values back to `input_rows` by unique normalized month, not physical row position. `source` records the file hash and mappings; `source_rows` preserves every mapped physical input row. `producer` records the kernel checksum and NumPy version.

The full fingerprint binds source bytes and declarations, stage, tool/kernel identity and NumPy version. CLI `--experiment` defaults to development; `--reveal-holdout` is an explicit separate evaluation. CLI `--reconcile` exports all checks. Each takes a matching request JSON and `--output` pointing to a new directory. Exported request snapshots can be replayed; nested explicit paths are accepted only by the CLI, never by HTTP.
