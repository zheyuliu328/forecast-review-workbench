# First-release interface

The public website uses the same calculation and export contracts through a browser-local Worker, with no upload API. The HTTP routes below apply only to the optional installed loopback application. Public requests are capped at 40 MiB; each file retains the 10 MiB / 10,000-row / 100-column bounds. A missing browser transport fails closed. See [browser release and privacy](WEB_RELEASE.md).


This is an implementation contract for a local browser tool, not a cloud service. Public data is never fetched at runtime. User-selected file bytes travel only between their browser and a loopback Python process. The process keeps requests in memory; it does not persist inputs. Output is an explicitly downloaded ZIP or a CLI-created new directory.

## Python boundary

`tableio.inspect_table(file, sheet=None, header_row=1) -> dict`

`file` is `{name: str, content_base64: str}`. Accept UTF-8 comma-separated CSV and `.xlsx`. Return `{sheets: [str], sheet: str|null, header_row: int, headers: [str], preview: [[str]], row_count: int, error: str|null}`. For an initially ambiguous Excel sheet, return available sheet names so the UI can select one. Invalid header rows return a useful error and a raw preview where practical. Excel formulas are never evaluated. No file path from a browser is trusted or opened.

`engine.review(payload) -> result`

Malformed structure or unparseable files raise `ValueError` with a user-actionable message. Row-level gaps return a result and stay visible. All output must serialize with `json.dumps(..., allow_nan=False)`.

## Review request

```json
{
  "schema_version": 1,
  "title": "Forecast review",
  "scope": {"start": "2024-01", "end": "2024-12", "frequency": "monthly", "entities": []},
  "contract": {"target": "Revenue", "unit": "USD", "horizon": 1, "transformation": "none"},
  "actual": {
    "file": {"name": "actual.csv", "content_base64": "..."},
    "sheet": null, "header_row": 1,
    "mapping": {"date": "Month", "value": "Actual", "entity": null},
    "contract": {"target": "Revenue", "unit": "USD", "horizon": 1, "transformation": "none", "frequency": "monthly"},
    "source_note": "Optional caller-declared provenance"
  },
  "candidates": [{"id": "model-a", "name": "Model A", "file": {}, "mapping": {}, "contract": {}}],
  "baseline": null,
  "accept_common_sample": false,
  "segments": [{"name": "Later period", "start": "2024-07", "end": "2024-12"}]
}
```

Candidate and optional baseline entries extend the same actual-source fields with `id` and `name`. One to five candidates; baseline IDs and all candidate IDs must be distinct and cannot be `actual`. Contract strings are exact after ordinary form validation. A source contract must include frequency and match the requested definition. Unit, target, horizon, transformation or frequency conflicts block all numerical comparisons. Values must already occupy the declared common target space; no transformation, conversion, training or baseline fitting occurs.

Daily keys use strict ISO `YYYY-MM-DD`. Monthly keys accept `YYYY-MM` or a valid ISO date mapped to its month. Quarterly keys accept `YYYY-Qn`, `YYYY-MM`, or an ISO date mapped to its quarter. Date normalization follows the explicitly selected frequency and is recorded. Excel date cells may supply a date/datetime; arbitrary numeric serials are not inferred. Ranges are inclusive. If any source maps an entity, all must map it and the user must supply an explicit, nonempty list of exact text entity IDs. Otherwise one series is used with entity `""`. The expected universe is the period range crossed with those entities, never inferred solely from surviving data.

Suggested limits: 10 MiB per original file, 10,000 physical data rows and 100 columns per table, 5,000 expected period/entity keys, five candidates and one baseline. Enforce ZIP expanded-size and XML protections before reading Excel. Selected formula cells, non-text entity IDs, missing entity IDs, invalid dates, duplicate keys and non-finite/invalid numbers remain diagnostic records. Do not fill missing values with zero or pair duplicates. Out-of-scope rows are recorded and excluded.

## Result shape

The mapped date is the target/evaluation period. Horizon is a declaration and never shifts dates or proves a forecast-generation timestamp. In the browser, combined JSON is limited to 40 MiB including base64 overhead, independently of the 10 MiB per-file cap. Several large files may therefore require smaller extracts even though each file fits its individual limit.

When no baseline is supplied, `vs_baseline` is null. With a baseline, it is an object with nullable relative metrics and the applicable reason.

Required keys:

- `schema_version`, `fingerprint`, `title`, `scope`, `contract`, `accepted_common_sample`, `comparison_ready`.
- `summary`: `{expected, common, excluded, extra_rows, blocking_issues}`. `common` is the number of expected keys with valid unique actual, every candidate and the optional baseline. `comparison_ready` requires accepted common sample, at least one common row and no contract errors.
- `sources`: source summaries with `id`, `name`, `role`, `file_name`, `sha256`, `mapping`, `contract`, `source_note`, `sheet`, `header_row`, `rows`, `blank_rows_ignored`.
- `models`: one per candidate/baseline, each `{id, name, role, coverage, available_metrics, metrics, vs_baseline}`. `coverage` contains `{expected, valid, missing, duplicate, invalid, outside_scope}`. `available_metrics` uses this source's own valid actual intersection and is prominently labelled non-comparable. `metrics` uses exactly the same common keys for all models and is null until ready. Metric objects contain `n` and decimal string values `mae`, `rmse`, `bias`. Bias is prediction minus actual. Baseline absence gives null relative metrics; zero baseline denominators give null plus reason. `vs_baseline` uses `{mae_pct, rmse_pct, reason}`.
- `rows`: one per expected key, with `period`, `entity`, `actual` (decimal string or null), `predictions` (by model ID), `residuals` (by model ID), `included` (eligible common row), `reasons` (objects with `source_id`, `code`, `detail`), `source_rows` (lists of original one-based row numbers by source ID).
- `input_rows`: every nonempty selected input row with `source_id`, original `row`, `raw_date`, `raw_value`, `raw_entity`, normalized `period`, `entity`, parsed `value`, and `status`. This allows row accounting even for invalid keys and out-of-scope inputs.
- `issues`: row/scope diagnostics with `source_id`, `row` (nullable), `period`, `entity`, `code`, `detail`. Raw values are available in `input_rows`.
- `contract_errors`: objects with `source_id`, `field`, `expected`, `received`.
- `segments`: requested segments, each `{name,start,end,n,metrics}` with per-model metrics restricted to the same common sample within that period range; metrics only when comparison ready.
- `warnings`: concise interpretation limitations.

All sums and errors use sufficient Decimal precision with explicitly bounded numeric input. RMSE is sqrt(mean(squared errors)), not residual standard error. Metrics cannot overflow silently. All candidates retain negative results. No winner/approval is generated automatically.

Fingerprint covers input byte hashes, mappings, contracts, source notes, scope, candidate/baseline IDs, segments and `accept_common_sample`. It excludes freeform title and review notes. Changing these review inputs invalidates old notes. Row reordering can change the input fingerprint while leaving coverage and numerical results invariant.

Any contract conflict blocks all numerical comparisons, including `available_metrics` and row residuals; preserve raw values and structural coverage only, and do not overlay mismatched units on a comparison plot. Baseline improvement percentages are `(baseline - candidate) / baseline * 100`, so positive means improvement. Segment metrics are null until ready, then a dictionary of model IDs to metrics; an empty segment has n=0 and null metrics for every model.

## HTTP endpoints (primary agent)

- `GET /`: local application; static assets under a fixed allowlist. A per-server CSRF token is inserted as `<meta name="csrf-token" content="...">`.
- `POST /api/inspect`: `{file, sheet, header_row}` -> inspection object.
- `POST /api/review`: review request -> result.
- `POST /api/export`: `{request: reviewRequest, fingerprint, notes: [{model_id, decision, text, fingerprint}]}` -> `application/zip`. Allowed decisions: `retain`, `needs_evidence`, `do_not_adopt`. Export recomputes the result and rejects stale fingerprints/notes. Pending coverage can still be exported; it must not contain common-sample metric claims.
- `GET /api/example`: locally constructed example request with 12 expected months, full actual/baseline, A missing 3 months, B missing another 2; seven common months. It is a convenience, not the only input route.

Requests use JSON, `X-Workbench-Token`, same-origin fetch and `credentials: same-origin`. The server accepts loopback Host/Origin only, rejects cross-origin access, bounds request size and does not expose arbitrary files or directories. Errors return `{error: str}` with a non-2xx status.

## UI behavior (UI worker)

Provide a polished English UI with a working Chinese toggle if feasible; English alone is acceptable for the public first release if copy is clear. No external fonts, scripts, trackers or CDN. Inputs: actual table, 1-5 candidate tables, optional baseline; file picker, sheet/header controls, header preview, date/value/entity mapping, and per-source declarations. Show declared scope and contract before review. Support optional segments. Show coverage before enabling the explicit common-sample acceptance checkbox. Changing file bytes, mappings, scope, candidate list, contract or segments clears the accepted sample and marks prior notes stale. Do not silently reuse notes on new results. Show same-sample metrics, baseline comparison, a legible trend/error plot, searchable/paged row diagnostics, source metadata, manual decisions and ZIP download. Render untrusted values with textContent/escaping, never unsanitized innerHTML. The UI can call `/api/example` for a sample but must support real File API uploads. Do not call APIs or shell directly outside this contract.
