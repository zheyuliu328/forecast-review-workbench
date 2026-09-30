# Guided forecast review release — 2026-09-30

Forecast comparison remains the default page. Training and reconciliation move to Other tasks. A five-step guide describes files, mappings/data checks, explicit common-sample acceptance, results and report export without replacing the existing state machine.

Common Chinese date/value aliases are suggested only when exactly one matching column exists. Existing valid manual mappings remain. The user still declares complete expected periods, units, horizon and entities; these are not guessed from available rows.

Results and offline reports juxtapose own-sample diagnostics and accepted common-sample MAE. The invented example has 12 expected, 7 common, 5 excluded months: A's own MAE 1.555556 versus B's 4.3 becomes A 2 versus B 1 on shared records. This demonstrates a coverage trap, not predictive skill. Report-generation status no longer asserts that a browser saved a file; a persistent save link is offered, and revoked when inputs or review evidence change.

## Verification and release

- 126 Python checks passed against current source; formatting, lint and vendored-kernel provenance passed.
- CI 36662353160 succeeded at 6ab818bccd7dc3f380b5623aac66b415a8f2afbc, including Python 3.10/3.12/3.14, package installation, dependency audit and actual browser workflows.
- Browser checks include external CSV/XLSX, explicit sample acceptance, independent exported-row recomputation, correctly structured five-column comparison rows, stale saved-report-link removal, cancellation, desktop and 390px layouts; no uploads or external requests during the tested public flow.
- Local interactive test additionally loaded newly invented Chinese-header CSV/XLSX: 3 records, MAE 8/3, RMSE sqrt(8), bias 4/3. Unit conflict blocked comparison; input changes hid results and disabled export. Existing fabricated coverage example was also observed in the new comparison table.
- Local IAB download events were intermittent. Download proof is the actual saved and independently verified Chromium CI bundle, not the local status message.
- Sites source: 6ab818bccd7dc3f380b5623aac66b415a8f2afbc.
- Saved version: appgprj_6aaa9988f594819186c04f6c14871488~appgver_5eacb47e0200819192778944450ed275.
- Deployment: appgdep_6abc7be1ea18819182eaaa569cdc5449, succeeded, existing public audience preserved.

No numerical engine, file contracts, accounts, server upload service or private data were added. Common-sample comparison still cannot establish source authenticity, leakage-free training, future skill or model approval. Human first-use/repeat-use and the owner's independent explanation remain unverified.

[Chinese walkthrough, English introduction and five questions](WALKTHROUGH.md).
