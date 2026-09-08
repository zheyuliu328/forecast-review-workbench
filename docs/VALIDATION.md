# Verification record

Release candidate 0.1.0, 2026-09-08. This record describes software checks on invented fixtures. It does not establish predictive skill, source authenticity, model approval or adoption by users.

## Automated checks

The Python suite has **89 passing tests, no skips**, covering parsing, decimal calculations, explicit expected coverage, incompatible definitions, duplicate/invalid/outside-scope rows, baseline edge cases, empty segments, input fingerprint changes, manual-note binding, HTML/CSV output, local HTTP access and installed command-line execution from outside the checkout. Ruff lint and formatting are checked separately.

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
python -m ruff check src tests
python -m ruff format --check src tests
python -m build --wheel
python -m pip install --force-reinstall dist/*.whl
npm ci
npx playwright install chromium
npm run test:browser
```

Browser checks start the installed `forecast-review` command on a fresh local port from the output directory. The recorded macOS run uses a temporary output directory outside the checkout. Node/Playwright are development dependencies only. Set `TEST_CHROME_PATH` to an installed Chrome executable if using that browser instead of Playwright's download. `TEST_PYTHON` and `FORECAST_REVIEW_BIN` can select an isolated environment. Screenshots, fixtures, ZIP and machine-readable results are written to ignored `outputs/browser-check/`, or `BROWSER_TEST_OUTPUT`.

The [CI workflow](../.github/workflows/ci.yml) runs Python 3.10, 3.12 and 3.14 on Linux, normal wheel installation, the browser workflow and the runtime-dependency audit. Its actual status is visible in [GitHub Actions](https://github.com/zheyuliu328/forecast-review-workbench/actions); a workflow definition alone is not evidence that a run passed.

## Practical limits

Local GUI checks use isolated Chrome on macOS. Narrow-view testing simulates viewport size; it does not establish operation on a physical phone. External requests were blocked for the tested browser workflow; this is not an operating-system-wide disconnected-network test. Independent agent checks and automated file selection do not substitute for an independent human usability trial; no such trial has been performed.

The first release does not train models or fit baselines, recalculate Excel formulas, convert units, invert transformations, reconstruct training history or prove freedom from leakage. The results describe supplied prediction files on the disclosed common sample. Existing projects' deferred training/automation features remain outside this release.
