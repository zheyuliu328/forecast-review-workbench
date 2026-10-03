# Understand and demonstrate Forecast Review Workbench

## Guided demonstration: compare the same observations

The tool identifies comparable records when targets, units and horizons agree, then compares forecast errors on those records. An imported prediction file cannot establish leakage-free training.

1. Select **Try an example** and inspect coverage. There are 12 expected months: A covers 9 and B covers 10; only 7 are shared.
2. Inspect each model's own sample. A has MAE about 1.5556 and B about 4.3. These are different months, so this is not a fair ranking.
3. Explicitly accept the common sample and view results. On the same 7 months, A has MAE 2 and B has MAE 1. The ranking reverses. Excluded months are April, May, October, November and December 2024; the conclusion does not cover them.
4. Download the review bundle and open report.html after extraction. Inspect definitions, metrics, source information and exclusion reasons. CSV/JSON support independent recomputation. The example uses invented forecasts, not training performance.
5. For your own files, select actuals and predictions, check date/value mappings, and declare the full expected period, target, unit and horizon. Do not shrink the expected period to observed coverage: this can hide months absent from every file. Common column aliases are suggested only when unambiguous; multiple matches require a manual choice.

Optional monthly OLS experiments fit preprocessing within each training window, select models on development data and explicitly reveal the holdout. Comparing imported forecasts and validating their training history are different tasks.

## English introduction — about three minutes at a measured pace

Forecast Review Workbench addresses a common problem in comparing prediction files: models may appear to have different accuracy simply because they cover different observations. I built a browser-local workflow that makes the expected scope, missing records and accepted common sample explicit before presenting a comparison.

The main task starts with actual values and one to five prediction files, with an optional baseline. The user selects CSV or Excel files, confirms the date and value columns, and declares the target, unit, horizon and full expected period. The tool suggests unambiguous common column names, but it does not guess the complete expected scope from the supplied data. That would hide records absent from every file.

The example makes this concrete. There are twelve expected months. Candidate A covers nine and candidate B covers ten, but only seven are shared. On their own samples, A has an MAE of about 1.56 and B about 4.30. On the same seven months, A has an MAE of two and B one. The apparent ranking reverses. These are invented predictions designed to demonstrate a coverage trap, not model-training results.

The review keeps all excluded periods visible. The user must accept a nonempty common sample before comparison metrics appear. MAE, RMSE and signed bias then use identical keys. Changing inputs or definitions invalidates the old acceptance and review notes. A downloaded evidence bundle includes a readable offline report, row diagnostics, declarations and source fingerprints, allowing someone else to recompute the results.

The repository also contains monthly regression experiments and additive financial reconciliation, but these are secondary workflows. The experiment workflow fits preprocessing within each training window and selects candidates on development data before explicitly revealing holdout performance. I reused and attributed the numerical kernel from my own public Model Risk Lab rather than claiming an independently written second engine.

The main limitation is that software can check declared definitions and supplied records, but it cannot authenticate the source or reconstruct an arbitrary prediction file's training history. A smaller common-sample error does not resolve missing coverage, prove future performance, or approve a model. External human adoption has not been verified. The project's value is making comparison assumptions and evidence inspectable rather than producing a flattering model ranking.

## Five technical follow-ups

1. **Why not compare each file's full sample?** Different periods/entities have different difficulty. Use the same valid expected keys; keep own-sample metrics diagnostic only.
2. **Does common-sample comparison remove selection bias?** No. Missingness may be systematic. Report excluded keys and limit the conclusion to the intersection.
3. **How is leakage addressed in training?** Preprocessing is fitted on training windows and selection uses development data. Information-release lags remain caller declarations; arbitrary imported forecasts cannot prove leakage-free training.
4. **Why keep a baseline?** It checks whether complexity improves error on the same sample. Percentage improvement is undefined when the baseline error is zero.
5. **What do hashes prove?** They help identify changes in selected source content and exports, not authenticity, causality, predictive skill or model approval.

## Personal understanding gate — pending

Reproduce the ranking reversal in your own words, explain why excluded months still matter, then give the English introduction and answer the five follow-ups. This personal assessment remains pending; generated materials are not proof of understanding.

## Explain the rolling-origin extension

A target month can have several forecasts issued at different origins. Comparing them under a target-only key either rejects legitimate records as duplicates or conflates different lead times. The tool identifies forecasts by origin, target and entity, while actuals remain unique by target and entity. It constructs expected keys from a declared origin range and horizons, then intersects valid keys across every candidate and baseline.

The invented two-horizon example has four forecast keys but only three actual target periods. A has smaller MAE one period ahead; B has smaller MAE two periods ahead. The report leads with separate horizons, and the chart displays one horizon and entity at a time. Aggregates weight forecast keys equally and do not imply independent errors.

Owner explanation remains pending: explain why March can appear twice in predictions but once in actuals; why origin labels cannot prove absence of leakage; and why the aggregate winner need not win at every horizon. Do not claim these points are personally mastered until the owner can answer them.

## Explain supplied intervals: coverage alone can reward useless width

Open the published interval workflow and load its invented example. All candidates declare central 80% intervals over four shared keys. Inspect the planned keys before accepting them. A and B both contain every outcome, but A has mean width and interval score 1, while B has width and score 20. C has width 0.5, misses three outcomes and has score 4.25. Coverage alone hides B's lack of precision; width alone hides C's misses.

For nominal coverage 0.8, the interval score is width plus ten times the distance of an outcome outside its bounds. Endpoints count as contained. Width and score are in the target unit; coverage is a ratio. Four outcomes cannot establish calibration, and repeated origins or overlapping horizons are not independent evidence. The tool reviews supplied intervals; it does not estimate or calibrate them.

Download the bundle and use evaluation-rows.csv to recompute the average score. Explain why reversed bounds exclude a key for every candidate rather than being automatically swapped. Explain why a smaller score on the accepted sample does not establish future superiority. These explanations remain an owner-assessment task, not a recorded pass.

## Explain event probabilities: an unavailable label is not a correct forecast

The browser implementation is available locally at /probabilities; its public deployment is pending. Check publication.json before describing it as live. The installed commands and invented inputs are documented in EVENT_PROBABILITY_REVIEW.md.

With cutoff January 3, two of three planned labels are observable. A's probabilities 0.25 and 0.75 against outcomes 0 and 1 give Brier score 0.0625 and log loss ln(4/3); the constant 0.5 baseline gives 0.25 and ln(2). The remaining label is pending, not an error-free prediction.

Change the cutoff to January 4 and explicitly accept the new sample. The third realised outcome is 1 but A assigned probability 0. Brier becomes 0.375; log loss is infinite, with one impossible event. The implementation does not clip the probability or remove that observation. JSON represents this with a null numeric value plus an explicit infinite status, rather than silently treating it as missing. The sample changed; this comparison does not isolate a change in model quality.

Use the frozen request in the downloaded bundle to recompute results with the native probability command. This reproduces calculation results, not every file of the browser ZIP. The request includes original file bytes and should be handled like those files. Explain why declared availability dates cannot prove historical issuance and why a missing baseline row removes that key from every candidate's comparison. Owner explanation remains pending.
