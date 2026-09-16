# Verification record

## Browser release work — 2026-09-16

See [0.3 public browser release](WEB_RELEASE.md). The dated 0.2 records below remain historical evidence, not a fresh re-run of those versions.


Release 0.2.0, 2026-09-09. This record describes software checks on invented fixtures. It does not establish predictive skill, source authenticity, model approval or adoption by users.

## Current extension checks

The current Python suite has **126 passing tests, no skips**: the existing 89 checks plus 37 extension checks. The separately published Model Risk Lab producer has **133 passing tests**, including 43 kernel and 16 CLI tests. Versioned public-kernel bytes and the retained license are checked offline. Normal wheel installs exercise both new CLI workflows outside the checkout.

A separate read-only agent checked 84 assertions across producer timing, exact reconciliation, source-row and stage binding, HTTP/ZIP exports and the top-level reported-total alert. Four integration findings were corrected and reverified: static asset routes, physical source-row lineage, explicit provenance for non-preselected transferred candidates, and reported-total attention when individual rows pass. The final kernel received the 28 numerical assertions again after its overflow-handling change. The installed producer CLI also passed seven independent scenarios containing 21 assertions. Assertions are not claimed as distinct user scenarios.

[The extension browser check](../tests/browser-extensions.cjs) uses independently invented real CSV/XLSX files through the file pickers, including multiple worksheets and header row 3. It verifies 180 observations, all 15 OLS candidates plus two baselines, retained constant-feature failures, explicit holdout reveal, unchanged selection, transfer to the original reviewer without automatic sample acceptance, and both stage exports. It separately checks offsetting row breaches, absent rows, unit conflicts, each side's reported totals, stale opinions and export editing locks. A final case has passing individual rows but three failing reported-total checks, which must remain visible at the top. Four downloaded ZIPs are independently recomputed and every original input hash is preserved.

## Original review checks retained

A subsequent Linux browser run exposed an import-capacity race: loading four files simultaneously could exceed the server's two-request bound. A local reproduction with 250ms inspection delays returned two HTTP 429 responses. Example and transfer loaders now inspect files sequentially. [The slow-inspection browser check](../tests/browser-loaders.cjs) retains the real server limit and tests four-source forecast and financial examples plus the seven-source maximum transfer; no automatic common-sample acceptance is introduced. This is an additional CI-discovered finding, separate from the earlier four review findings.

The [0.1.0 machine record](local-verification-0.1.0.json) is retained as a dated historical snapshot. The [current record](local-verification.json) binds version 0.2.0 source hashes and installed browser evidence. Both new offline reports were separately opened at desktop and 390-pixel widths with no external requests, page errors or document overflow. CSV/JSON retain complete precision; the readable candidate report rounds score display only.

The original 0.1 workflow contributes **89 passing tests, no skips**, covering parsing, decimal calculations, explicit expected coverage, incompatible definitions, duplicate/invalid/outside-scope rows, baseline edge cases, empty segments, input fingerprint changes, manual-note binding, HTML/CSV output, local HTTP access and installed command-line execution from outside the checkout. Ruff lint and formatting are checked separately.

An independent read-only review completed **60 counterexample checks**: 28 engine checks, five Excel-input checks, seven direct-export checks and 20 HTTP/export checks. It used different hand-calculated fixtures. It identified a negative-number CSV escaping issue and a missing page request token; both were corrected and independently reverified.

The real browser acceptance script is [tests/browser-smoke.cjs](../tests/browser-smoke.cjs). It opens an isolated browser, uses actual file-selection controls and allows only the local application's requests. It does not call the built-in example for its primary fixture:

1. Select two differently arranged CSV files and a two-sheet XLSX, selecting its `Forecasts` sheet and header row 3.
2. Set five expected periods, confirm mappings, inspect two exclusions, and accept the three common periods.
3. Verify candidate A's MAE 2, RMSE `sqrt(14/3)` and bias 0, and candidate B's MAE `7/3` and bias 1.
4. Add a manual opinion, download the ZIP, recompute residuals directly from the CSV, and check original-file and exported-file hashes.
5. Change and restore a source note; the previous opinion remains stale until explicitly reconsidered. Conflicting units block comparison metrics and plots.
6. Check the three application stages and offline report at a 390-pixel viewport for page overflow. Capture desktop and narrow screenshots. The application makes no external requests during the tested flow.

The test also verifies gaps break chart lines in the separate twelve-period example, and locks note editing while the download is being prepared. These two integration cases were added after an independent review found misleading gap connections and a potential mismatch between an edited opinion and an in-progress export.

## Repeat the checks

```sh
python -m pip install '.[dev]'
python -m pytest -q
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python tools/check_vendor.py
python -m build --wheel
python -m pip install --force-reinstall dist/*.whl
npm ci
npx playwright install chromium
npm run test:browser
```

Browser checks start the installed `forecast-review` command on a fresh local port from the output directory. The recorded macOS run uses a temporary output directory outside the checkout. Node/Playwright are development dependencies only. Set `TEST_CHROME_PATH` to an installed Chrome executable if using that browser instead of Playwright's download. `TEST_PYTHON` and `FORECAST_REVIEW_BIN` can select an isolated environment. Screenshots, fixtures, ZIP and machine-readable results are written to ignored `outputs/browser-check/` and `outputs/browser-extensions/`, or `BROWSER_TEST_OUTPUT`. Extension checks choose a new suffixed destination if their output already exists.

The [CI workflow](../.github/workflows/ci.yml) runs Python 3.10, 3.12 and 3.14 on Linux, normal wheel installation, the browser workflow and the runtime-dependency audit. Its actual status is visible in [GitHub Actions](https://github.com/zheyuliu328/forecast-review-workbench/actions); a workflow definition alone is not evidence that a run passed.

## Practical limits

Local GUI checks use isolated Chrome on macOS. Narrow-view testing simulates viewport size; it does not establish operation on a physical phone. External requests were blocked for the tested browser workflow; this is not an operating-system-wide disconnected-network test. Independent agent checks and automated file selection do not substitute for an independent human usability trial; no such trial has been performed.

Version 0.2 adds the specified monthly OLS producer and additive reconciliation protocol. It does not recalculate Excel formulas, convert units, invert transformations, reconstruct supplied forecasts' training histories or implement nonlinear margin aggregation. Information availability remains caller-declared. Independent human usability testing and repeat use on real tasks remain open; software checks do not establish predictive skill or business approval.
