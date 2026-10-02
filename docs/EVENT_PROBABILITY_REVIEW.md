# Frozen binary-event probability review

This optional native task reviews caller-supplied probabilities for one explicitly declared binary event. It does not fit a model, choose a classification threshold or force an observation-based event into a calendar forecast horizon. The existing numeric-forecast schemas and browser workflow are unchanged. There is no public browser entry for this task yet.

## Complete an original task

Install the package normally and choose fresh output directories:

```sh
python -m forecast_review_workbench.probabilities examples/event-probability/request.json --output /tmp/new-event-review
python -m forecast_review_workbench.probabilities examples/event-probability/later-cutoff.json --output /tmp/new-later-review
```

The first request declares three expected origin keys, with evaluation cutoff January 3. Two labels are observable. Candidate A assigns probabilities 0.25 and 0.75 to labels 0 and 1: Brier 0.0625 and log loss ln(4/3), compared with constant-baseline Brier 0.25 and log loss ln(2). The third key remains pending. All inputs are independently invented.

At the January 4 cutoff, the third label becomes observable. A assigned probability zero to an event that occurred. All three common keys remain included: Brier becomes 0.375, log loss is explicitly infinite with one impossible event. This is represented as JSON null with `log_loss_status: infinite`, not a missing observation. Probabilities are never clipped and failed endpoints are never dropped to improve the average. The two cutoffs have different samples; score changes do not isolate model improvement or deterioration.

Open report.html offline. It explains the equally weighted scoring formulas and units, identifies each source's role, filename, sheet, header row and original SHA-256, and lists the first 100 invalid or duplicate input rows with original row numbers and reasons. Pending or missing observations are shown separately from input errors. Keep results.json with its complete mapped rows, exclusion states, source hashes and declared contract. request.json retains the exact input bytes as base64 so the run can be repeated without original file paths. Existing output directories are refused.

## Input contract

A request has task `binary_event_review`, schema_version 1, exact `event_definition`, ISO `evaluation_as_of`, 1–5000 explicit `expected_keys` (origin and entity), one `labels` source, 1–5 `candidates`, optional `baseline`, and boolean `accept_common_sample`.

Every source needs a unique ID, matching event definition, source note, file and mapping. CSV and XLSX intake reuse the existing bounded table reader. The CLI accepts file objects containing only `path`, relative to the request; the Python API takes `name` and `content_base64`. Excel multi-sheet inputs require an explicit sheet. Formula, error and boolean values in mapped cells are rejected; unmapped original cells remain in row diagnostics.

- Labels map `origin`, `entity`, `label` and `available` to column names.
- Candidate/baseline sources map `origin`, `entity` and `probability`.
- Only `entity` may map to null, representing a single series with the empty entity ID.
- Label values must be 0 or 1. Blank labels are permitted only when the declared availability is after the cutoff.
- Probabilities are finite decimal ratios in [0,1], not percentages. Parsing and score arithmetic retain high precision before final 40-significant-digit reporting.
- Availability must follow origin at calendar-day resolution; same-day/intraday tasks are unsupported.

All duplicate key occurrences are excluded. Missing, invalid, pending, not-yet-issued and outside-scope rows remain explicit. The common sample is the intersection of valid rows across labels, every candidate and the supplied baseline, within the declared expected keys. A missing baseline row excludes that key for all candidates. No score is exposed until this sample is explicitly accepted and event definitions agree.

## Interpretation limits

Expected keys must come from a declared universe; using surviving prediction keys cannot reveal dates absent from every source. Origin and availability dates are declarations, not proof of when forecasts were created or of historical market-data authenticity. Event descriptions must identify the positive class, observation window and label rule consistently; this tool does not certify label construction. Overlapping events are not independent trials. This is a descriptive software review, not a significance test, trading strategy, model approval or external user study.
