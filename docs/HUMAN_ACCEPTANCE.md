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

The worked independent checker in examples/entity-horizon/verify_export.py is optional follow-up after the unassisted task. It checks consistency of this one invented exported fixture; it does not authenticate sources or validate arbitrary models. The native binary-event probability task remains separate from the public browser and is not part of this browser acceptance card.
