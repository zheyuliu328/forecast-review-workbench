# Human acceptance — Forecast Review Workbench

**Status: pending.** This is a runnable acceptance kit, not a completed trial. Use only invented files. The walkthrough provides the explanation and five technical follow-ups; read it after the unassisted task, not before, when assessing first-use discoverability.

## Unassisted first-use task

1. Open the public tool without installation. Run the invented coverage example and identify 12 expected, 7 common and 5 excluded months.
2. Explain why A looks better on its own records but B is better on shared records. Name the excluded months and the limited scope of the conclusion.
3. Select `examples/actual.csv`, `candidate-a.csv`, `candidate-b.csv` and optional `baseline.csv`. Map columns, declare the 2024 monthly range and consistent target/unit/horizon, then explicitly accept the common sample.
4. Introduce an incompatible unit declaration. Confirm comparison is blocked; restore the unit and complete the review. Change an input after results and confirm stale conclusions cannot be exported.
5. Download the ZIP, extract it and open `report.html` offline. Find scope, input hashes, excluded keys, metrics and limitations.
6. Repeat at a narrow phone-sized viewport. Record horizontal table scrolling or any blocking control.

## Blank trial record

- Participant (pseudonym):
- Date, browser, device and viewport:
- Tasks completed without prompting:
- Time to first useful result and to exported report:
- Assistance required and exact confusing wording:
- Failed input, visible message, recovery steps:
- Offline report understood without the website: yes / no / not assessed
- Repeat-use task completed: yes / no / not assessed
- Blocking issue and evidence:
- Overall status: pending / passed within recorded scope / needs repair

## Owner explanation — pending

Give the approximately three-minute English introduction in `WALKTHROUGH.md` without reading, then answer its five technical follow-ups. For each answer, record correct / incomplete / incorrect and the missing reasoning. Demonstrate one fresh invented input and explain the result and limits. Do not mark this gate passed from a generated script or automated browser test.

## Claim boundary

Verified implementation and reproducible test evidence can be described as project work. Human adoption, unaided understanding and production use require their own recorded evidence. No application is submitted by this checklist.

## Published extensions: participant task card

**Status: pending.** Give the participant only this card and the public URL. Hide the observer rubric below until completion. Record hints separately from independent success. Use only the built-in invented examples or the original invented files in this repository.

1. Run the rolling-origin example. Explain why a target month can have more than one forecast, and determine whether the same candidate is better at both horizons. Switch the displayed horizon and identify what remains fixed.
2. Run the hidden-deterioration example, inspect the available records and accept the common sample. Compare the overall result with the Small entity. Explain why the overall result alone is insufficient to choose a candidate.
3. Filter the group table to Small and download the review package. Close the website, extract the ZIP and inspect group-metrics.csv. Determine whether the filter changed the evaluated sample or removed other entities from the export.
4. Use the report to identify the source files, common observations and limitations. Explain what a matching file hash proves and what it cannot prove.
5. Repeat the group-filter and export task on a narrow screen. Record confusing wording, inaccessible controls, time and assistance.

## Observer rubric for the published extensions

| Task | Observable evidence | Interpretation needed |
|---|---|---|
| Rolling origins | Four forecast keys, three actual target keys; horizon 1 MAE A=1/B=1.5; horizon 2 A=2/B=1 | Forecast origin and horizon distinguish legitimate repeated targets. Declared origin labels do not prove training or issuance history. |
| Hidden deterioration | Four common keys; pooled A MAE=26 versus baseline=50.5, about 48.51% gain; Small A gain=-100%, B gain=+50% | Large-scale entities can dominate pooled errors. A negative gain means deterioration; these tiny samples do not establish future skill. |
| Filtered export | Small view shows one of two groups; downloaded group-metrics.csv retains six entity/model rows, including Large | View filtering neither reselects the accepted global common sample nor limits the exported evidence. |
| Offline interpretation | Participant finds declarations, excluded/common rows and file digests | Digests identify bytes, not authenticity. config.json is metadata, not a replay request containing original source bytes. |
| Narrow screen | Comparison and export completed, or an actionable recorded blocker | Completion after hints must remain recorded as assisted. |

The worked independent checker in examples/entity-horizon/verify_export.py is optional follow-up after the unassisted task. It checks consistency of this one invented exported fixture; it does not authenticate sources or validate arbitrary models. The interval and probability task cards below extend this kit. Probability browser deployment is pending; do not record a public trial before its publication receipt confirms release.

## Interval task card — public workflow, human trial pending

Give the participant the public /intervals/ URL and the invented files in examples/interval-review. Keep the observer answers hidden until the task ends.

1. Load the example and determine whether the candidate with widest intervals is more useful simply because every outcome lies inside them.
2. Select the original files yourself, confirm mappings and source definitions, inspect planned keys and explicitly accept the shared sample.
3. In a copy of one candidate file, reverse one pair of bounds. Identify the rejected row and explain its effect on every candidate. Replace it with the original file and recover the review.
4. Export the bundle, close the page and recompute one candidate's mean interval score from evaluation-rows.csv. Find the declared nominal coverage, source information and limitations in the report.
5. Repeat the comparison and download at a narrow viewport. Record completion time, hints and blockers in the blank trial record above.

Observer answers: four common keys; A/B coverage 1 and widths/scores 1/20; C width 0.5, coverage 0.25 and score 4.25. Wider containment is not evidence of calibration. A reversed bound excludes its key globally; restoring the file requires a new acceptance. Do not mark a human pass from automated execution.

## Probability task card — local implementation, public release pending

Use /probabilities on the local tool until publication.json records a verified public release. Public trial status remains pending. Use only the invented event-probability files; do not introduce personal or customer records.

1. Load the example at January 3. Identify which planned observation cannot yet be evaluated and why.
2. Accept the shared sample, compare A with the baseline, then change the cutoff to January 4. Check that old scores and acceptance disappear before accepting the new sample.
3. Explain the infinite score. Identify the precise probability/outcome combination; do not remove it or change the scoring rule to obtain a finite answer.
4. Select your own copies of the invented files. Introduce an out-of-range probability, locate its source row, and replace the file to recover. Remove a baseline key and inspect the resulting shared sample before accepting it.
5. Download the report bundle and locate input bytes, source hashes, cutoff, pending/excluded keys and score status. Recompute results from request.json with the native probability CLI into a fresh directory. Repeat import and export at a narrow viewport.

Observer answers: January 3 has two common keys and A Brier 0.0625, log loss ln(4/3); January 4 has three keys and A Brier 0.375, infinite log loss and one impossible event. The baseline has Brier 0.25 and log loss ln(2). Out-of-range probabilities are invalid; missing baseline keys are excluded for all candidates. A changed cutoff changes the evaluated sample and cannot establish model deterioration by itself. Native replay compares results, not a byte-identical reconstruction of the whole browser ZIP.

For both cards, owner explanation and unassisted human completion are still pending. Record actual participants, assistance and failures before changing either status.
