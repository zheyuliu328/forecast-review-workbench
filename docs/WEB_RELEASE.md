# Public browser release — 0.3.0

Release work dated 2026-09-16. [Website](https://forecast-review-zheyuliu.mystic-pear-2111.chatgpt.site) · [Tool states](https://forecast-review-zheyuliu.mystic-pear-2111.chatgpt.site/tools.html).

The three existing workflows run through their original Python functions in a serial Pyodide Worker. Selected files and results are not posted to a server. The bridge serves only allowlisted actions; a missing bridge fails closed rather than reverting to HTTP. Cancel terminates the Worker and stops an in-progress multi-file example. The optional desktop server and CLI remain available.

First use downloads approximately 17 MB of self-hosted runtime assets. Pyodide 314.0.6 provides NumPy 2.4.6; pure Python wheels are hash-pinned. The build uses an explicit source/output allowlist and includes dependency licenses. Each ZIP records the browser build and dependency provenance. Browser and desktop experiment fingerprints can differ because NumPy version is part of the contract.

Each file retains the 10 MiB, 10,000-row and 100-column input limits. Combined requests are bounded to 40 MiB and operations time out after two minutes. Experiment-to-review transfer temporarily uses same-tab session storage, deleted after reading. Experiment/reconciliation ZIPs include full selected source snapshots; forecast-review ZIPs include mapped values, diagnostics and input hashes. Refresh clears ordinary page state. No analytics or input-upload endpoint is added.

Common-sample acceptance, definition conflicts, explicit holdout reveal, fixed development selection, additive grouping, stale-result invalidation and source-bound manual opinions remain part of the original workflow. UI simplification does not grant business or model approval.

## Verification scope

- Existing 126 Python tests passed locally on 2026-09-16. The normal package installation was also refreshed.
- tests/browser-web.cjs exercises actual CSV and multi-sheet Excel selection, common-sample decisions, three workflow exports, transfer without automatic acceptance, narrow layouts, cancellation, missing-bridge failure and zero upload/external requests.
- Remote release checks and publication status are recorded with the final release evidence. This document does not substitute for those results.
- No external human adoption study or large-phone performance benchmark has been completed. Other projects' historical test counts are not a fresh all-repository validation.
