/* Independent real-file acceptance of development, holdout and reconciliation. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {spawn, execFileSync} = require("node:child_process");
const {chromium} = require("playwright");

(async () => {
  const destination = path.resolve(process.env.BROWSER_TEST_OUTPUT || "outputs/browser-extensions");
  const output = fs.existsSync(destination) && fs.readdirSync(destination).length
    ? fs.mkdtempSync(destination + "-") : destination;
  fs.mkdirSync(output, {recursive: true});
  const python = process.env.TEST_PYTHON || "python3";
  const fixtureScript = path.join(__dirname, "make_extension_fixtures.py");
  execFileSync(python, [fixtureScript, output]);
  const expected = JSON.parse(fs.readFileSync(path.join(output, "fixture-expectations.json"), "utf8"));
  const digest = name => crypto.createHash("sha256").update(fs.readFileSync(path.join(output, name))).digest("hex");
  const inputHashes = Object.fromEntries(expected.files.map(name => [name, digest(name)]));
  let server, browser, page, exportGate, releaseGate;
  const external = [], browserErrors = [], apiErrors = [], apiRequests = [];
  const downloaded = [];
  try {
    let url = process.env.BROWSER_TEST_URL;
    if (!url) {
      server = spawn(process.env.FORECAST_REVIEW_BIN || "forecast-review", ["--port", "0", "--no-browser"], {cwd: output});
      url = await new Promise((resolve, reject) => {
        let text = "";
        const timer = setTimeout(() => reject(new Error("Installed application did not start")), 20000);
        server.on("error", error => { clearTimeout(timer); reject(error); });
        server.stdout.on("data", data => {
          text += data;
          const match = text.match(/http:\/\/127\.0\.0\.1:\d+/);
          if (match) { clearTimeout(timer); resolve(match[0]); }
        });
        server.on("exit", code => { clearTimeout(timer); reject(new Error("Application exited: " + code)); });
      });
    }
    assert(["127.0.0.1", "localhost", "[::1]"].includes(new URL(url).hostname), "Test target must be local");
    browser = await chromium.launch({headless: true, ...(process.env.TEST_CHROME_PATH ? {executablePath: process.env.TEST_CHROME_PATH} : {})});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: true});
    await context.route("**/*", async route => {
      const target = route.request().url();
      if (!target.startsWith(url + "/") && !target.startsWith("blob:")) {
        external.push(target); return route.abort();
      }
      if (exportGate && target.endsWith(exportGate.endpoint)) await exportGate.promise;
      return route.continue();
    });
    for (const asset of ["experiments.js", "reconcile.js", "extension-common.js", "extensions.css"]) {
      const response = await context.request.get(url + "/static/" + asset);
      assert.equal(response.status(), 200, "Missing extension asset " + asset);
    }
    page = await context.newPage();
    page.setDefaultTimeout(20000);
    page.on("pageerror", error => browserErrors.push(error.message));
    page.on("request", request => { if (request.url().includes("/api/")) apiRequests.push(new URL(request.url()).pathname); });
    page.on("response", response => { if (response.url().includes("/api/") && response.status() >= 400) apiErrors.push([response.url(), response.status()]); });
    async function postAction(endpoint, action) {
      const [response] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith(endpoint) && response.request().method() === "POST"),
        action()
      ]);
      const data = await response.json();
      assert.equal(response.status(), 200, data.error || endpoint + " failed");
      return data;
    }
    async function ready(selector) {
      await page.waitForFunction(selector => {
        const node = document.querySelector(selector);
        return node && !node.disabled && !node.closest("fieldset:disabled");
      }, selector);
    }
    async function upload(id, filename, sheet, header = 1) {
      await postAction("/api/inspect", () => page.locator("#" + id + "-file").setInputFiles(path.join(output, filename)));
      await ready("#" + id + "-header-row");
      if (sheet) {
        await postAction("/api/inspect", () => page.locator("#" + id + "-sheet").selectOption(sheet));
        await ready("#" + id + "-header-row");
      }
      if (header !== 1) {
        await page.locator("#" + id + "-header-row").fill(String(header));
        await postAction("/api/inspect", () => page.locator("#" + id + "-header-row").press("Tab"));
        await ready("#" + id + "-header-row");
      }
    }
    async function screenshot(name, mobile = false) {
      await page.setViewportSize(mobile ? {width: 390, height: 844} : {width: 1440, height: 1000});
      await page.waitForTimeout(160);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, name + " causes page overflow");
      await page.screenshot({path: path.join(output, name + ".png"), fullPage: true});
    }
    async function download(selector, endpoint, name, kind, lockCheck) {
      await ready(selector);
      const pending = page.waitForEvent("download");
      exportGate = {endpoint, promise: new Promise(resolve => { releaseGate = resolve; })};
      try {
        await page.locator(selector).click();
        if (lockCheck) await lockCheck();
      } finally {
        releaseGate(); releaseGate = null; exportGate = null;
      }
      const item = await pending;
      const file = path.join(output, name);
      await item.saveAs(file);
      assert.equal(await item.failure(), null);
      await ready(selector);
      const verification = execFileSync(python, [fixtureScript, "--verify", file, "--kind", kind], {encoding: "utf8"});
      downloaded.push(JSON.parse(verification));
    }
    function close(actual, expected, label) {
      assert(Math.abs(Number(actual) - Number(expected)) < 1e-10, label + ": " + actual + " != " + expected);
    }
    function validateExperiment(result, stage) {
      assert.equal(result.stage, stage);
      assert.equal(result.coverage.raw, 180);
      assert.equal(result.candidates.filter(candidate => candidate.role === "candidate").length, 15);
      assert.equal(result.candidates.filter(candidate => candidate.role === "baseline").length, 2);
      assert(result.candidates.some(candidate => candidate.status === "failed" && candidate.reason), "Failed constant-feature candidates must remain visible");
      assert(result.selected_on_development);
      if (stage === "development") {
        assert(result.candidates.every(candidate => candidate.holdout === null));
        assert(result.predictions.every(row => row.split !== "holdout"), "Prepare leaked holdout predictions");
      }
      for (const candidate of result.candidates) {
        for (const split of ["development", "holdout"]) {
          const metrics = candidate[split];
          const predictions = result.predictions.filter(row => row.model_id === candidate.id && row.split === split);
          if (!metrics) { assert.equal(predictions.length, 0); continue; }
          const errors = predictions.map(row => Number(row.prediction) - Number(row.actual));
          assert.equal(errors.length, metrics.n);
          close(metrics.mae, errors.reduce((sum, error) => sum + Math.abs(error), 0) / errors.length, "Independent MAE");
          close(metrics.rmse, Math.sqrt(errors.reduce((sum, error) => sum + error * error, 0) / errors.length), "Independent RMSE");
          close(metrics.bias, errors.reduce((sum, error) => sum + error, 0) / errors.length, "Independent bias");
        }
      }
    }
    async function mapTraining() {
      await ready("#training-date");
      await page.locator("#training-date").selectOption("Observation month");
      await page.locator("#training-target").selectOption("Observed units");
      while (await page.locator(".feature-row").count() < 5) await page.locator("#add-feature").click();
      for (let index = 0; index < 5; index += 1) {
        await page.locator("#feature-column-" + index).selectOption(expected.training.feature_columns[index]);
        await page.locator("#feature-name-" + index).fill(expected.training.feature_columns[index]);
        await page.locator("#feature-lag-" + index).fill(String(expected.training.lags[index]));
        await page.locator("#feature-delay-" + index).fill(String(expected.training.release_delays[index]));
      }
    }
    await page.goto(url + "/experiments");
    assert.equal(await page.locator(".workbench-nav a").count(), 3);
    await page.locator("#experiment-title").fill("Independent 180-month experiment");
    await page.locator("#target-name").fill("Invented demand");
    await page.locator("#target-unit").fill("units");
    await page.locator("#development-end").fill("2021-12");
    await page.locator("#source-note").fill("Independently generated arithmetic fixture; no external data.");
    await upload("training", "training-history.csv");
    await mapTraining();
    const csvDevelopment = await postAction("/api/experiments/prepare", () => page.locator("#prepare-button").click());
    validateExperiment(csvDevelopment, "development");
    await page.locator("#experiment-results").waitFor({state: "visible"});
    await ready("#prepare-button");
    assert.equal(await page.locator("#candidate-table tbody tr").count(), 17);
    console.log("CSV development: 15 OLS candidates and two baselines, with failures retained.");
    await upload("training", "training-history.xlsx", "Monthly history", 3);
    await mapTraining();
    assert.equal(await page.locator("#experiment-results").isVisible(), false, "Replacing files must invalidate old results");
    await screenshot("experiments-inputs-desktop");
    await screenshot("experiments-inputs-mobile", true);
    await page.setViewportSize({width: 1440, height: 1000});
    const development = await postAction("/api/experiments/prepare", () => page.locator("#prepare-button").click());
    validateExperiment(development, "development");
    assert.equal(development.selected_on_development, csvDevelopment.selected_on_development);
    assert.notEqual(development.fingerprint, csvDevelopment.fingerprint, "Different source bytes must have different fingerprints");
    for (const model of development.candidates) {
      const csvModel = csvDevelopment.candidates.find(candidate => candidate.id === model.id);
      if (model.development) close(model.development.mae, csvModel.development.mae, "CSV/XLSX equivalent values");
    }
    await page.locator("#experiment-results").waitFor({state: "visible"});
    await ready("#prepare-button");
    assert.equal(await page.locator("#reveal-holdout").isDisabled(), true);
    assert.equal(apiRequests.filter(endpoint => endpoint === "/api/experiments/reveal").length, 0);
    fs.writeFileSync(path.join(output, "development-result.json"), JSON.stringify(development, null, 2) + "\n");
    await screenshot("experiments-development-desktop");
    await screenshot("experiments-development-mobile", true);
    await download("#experiment-export", "/api/experiments/export", "development-evidence.zip", "development", async () => {
      assert.equal(await page.locator("#experiment-title").isDisabled(), true);
      assert.equal(await page.locator("#reveal-acceptance").isDisabled(), true);
    });
    await page.locator("#reveal-acceptance").check();
    const holdout = await postAction("/api/experiments/reveal", () => page.locator("#reveal-holdout").click());
    validateExperiment(holdout, "holdout");
    assert.equal(holdout.selected_on_development, development.selected_on_development);
    assert.equal(holdout.selection_fingerprint, development.selection_fingerprint);
    assert.notEqual(holdout.fingerprint, development.fingerprint);
    await ready("#experiment-export");
    await page.locator("#transfer-review").waitFor({state: "visible"});
    fs.writeFileSync(path.join(output, "holdout-result.json"), JSON.stringify(holdout, null, 2) + "\n");
    await screenshot("experiments-holdout-desktop");
    await screenshot("experiments-holdout-mobile", true);
    await download("#experiment-export", "/api/experiments/export", "holdout-evidence.zip", "holdout");
    assert.equal(await page.locator(".transfer-models input:checked").count(), 1);
    assert.equal(await page.locator(".transfer-models input:checked").inputValue(), holdout.selected_on_development);
    const pendingImport = page.waitForResponse(response => response.url().endsWith("/api/review") && response.request().method() === "POST");
    await page.locator("#transfer-review").click();
    const imported = await (await pendingImport).json();
    assert.equal(imported.comparison_ready, false);
    assert.equal(imported.accepted_common_sample, false);
    assert(imported.models.every(model => model.metrics === null));
    assert.equal(await page.evaluate(() => sessionStorage.getItem("frw.import.request")), null);
    await ready("#accept-common-sample");
    assert.equal(await page.locator("#accept-common-sample").isChecked(), false);
    const accepted = await postAction("/api/review", () => page.locator("#accept-common-sample").click());
    assert.equal(accepted.comparison_ready, true);
    await ready("#go-review");
    await page.locator("#go-review").click();
    await screenshot("transferred-review-desktop");
    await screenshot("transferred-review-mobile", true);
    await download("#export-review", "/api/export", "transferred-review.zip", "review");
    console.log("XLSX header row 3, explicit holdout, ZIP recomputation and non-accepting review transfer passed.");

    const mapping = {record_id: "Record code", date: "As of", measure: "Metric", risk_type: "Risk class", tenor: "Maturity", currency: "CCY", unit: "Value unit", value: "Amount"};
    async function mapFinancial(id, totals = false) {
      await ready("#" + id + "-value");
      for (const [field, column] of Object.entries(mapping)) {
        if (!totals || field !== "record_id") await page.locator("#" + id + "-" + field).selectOption(column);
      }
    }
    await page.goto(url + "/reconcile");
    await page.locator("#reconcile-title").fill("Independent offsets and units review");
    await upload("left", "reference.csv"); await mapFinancial("left");
    await upload("right", "challenger.xlsx", "Challenger values", 3); await mapFinancial("right");
    await page.locator("#left-totals-enabled").check();
    await page.locator("#right-totals-enabled").check();
    await upload("left-totals", "reference-totals.csv"); await mapFinancial("left-totals", true);
    await upload("right-totals", "challenger-totals.xlsx", "Reported totals", 3); await mapFinancial("right-totals", true);
    assert.equal(await page.locator("#additive").isChecked(), false);
    await page.locator("#reconcile-button").click();
    await page.locator("#error").filter({hasText: "explicit confirmation"}).waitFor({state: "visible"});
    await page.locator("#additive").check();
    await screenshot("reconcile-inputs-desktop");
    await screenshot("reconcile-inputs-mobile", true);
    await page.setViewportSize({width: 1440, height: 1000});
    const reconciliation = await postAction("/api/reconcile", () => page.locator("#reconcile-button").click());
    for (const key of ["expected", "left_rows", "right_rows", "pass", "breach", "missing_right", "definition_conflict"]) {
      assert.equal(reconciliation.summary[key], expected.reconciliation[key], "Reconciliation " + key);
    }
    const offsets = reconciliation.groups.find(group => group.dimensions.measure === "PV" && group.dimensions.tenor === "5Y");
    assert.equal(Number(offsets.difference), 0); assert.equal(offsets.offsetting_breaches, true);
    assert.notEqual(offsets.status, "pass");
    await page.locator("#reconcile-results").waitFor({state: "visible"});
    await ready("#reconcile-export");
    const firstRecord = page.locator("#record-table tbody tr").filter({has: page.getByText("001", {exact: true})});
    await firstRecord.getByRole("button", {name: "Add / view note"}).click();
    await page.locator("#reconcile-decision-0").selectOption("needs_evidence");
    await page.locator("#reconcile-text-0").fill("The +10 difference offsets record 002 but remains unexplained. Obtain the underlying valuation inputs.");
    await screenshot("reconcile-records-desktop");
    await screenshot("reconcile-records-mobile", true);
    await download("#reconcile-export", "/api/reconcile/export", "reconciliation-evidence.zip", "reconcile", async () => {
      assert.equal(await page.locator("#reconcile-text-0").isDisabled(), true);
      assert.equal(await page.locator("#reconcile-decision-0").isDisabled(), true);
      assert.equal(await page.locator("#record-table [data-note-action]").first().isDisabled(), true);
    });
    assert.equal(await page.locator("#reconcile-text-0").isEnabled(), true);
    // Even restoring the exact same tolerance requires explicit reconsideration.
    await page.locator("#absolute-tolerance").fill("0.02");
    await page.locator("#absolute-tolerance").fill("0.01");
    assert.equal(await page.locator("#reconcile-results").isVisible(), false);
    const rerun = await postAction("/api/reconcile", () => page.locator("#reconcile-button").click());
    assert.equal(rerun.fingerprint, reconciliation.fingerprint);
    await ready("#reconcile-export");
    assert.equal(await page.locator("#reconcile-text-0").isDisabled(), true);
    await page.locator("#reconcile-export").click();
    await page.locator("#error").filter({hasText: "earlier inputs"}).waitFor({state: "visible"});
    await page.getByRole("button", {name: "Rechecked · use for this run"}).click();
    assert.equal(await page.locator("#reconcile-text-0").isEnabled(), true);
    assert.equal(await page.locator("#error").isVisible(), false);
    for (const view of ["groups", "totals"]) {
      await page.locator('[data-view="' + view + '"]').click();
      await screenshot("reconcile-" + view + "-desktop");
      await screenshot("reconcile-" + view + "-mobile", true);
    }
    fs.writeFileSync(path.join(output, "reconciliation-result.json"), JSON.stringify(reconciliation, null, 2) + "\n");
    console.log("Record offsets, definition conflict, reported totals, note locking and stale-note reconsideration passed.");

    // A separate fully matching detail case must still announce wrong reported totals.
    await page.goto(url + "/reconcile");
    await upload("left", "totals-focus-reference.csv"); await mapFinancial("left");
    await upload("right", "totals-focus-challenger.csv"); await mapFinancial("right");
    await page.locator("#left-totals-enabled").check();
    await page.locator("#right-totals-enabled").check();
    await upload("left-totals", "totals-focus-left.csv"); await mapFinancial("left-totals", true);
    await upload("right-totals", "totals-focus-right.csv"); await mapFinancial("right-totals", true);
    await page.locator("#additive").check();
    const totalsOnly = await postAction("/api/reconcile", () => page.locator("#reconcile-button").click());
    assert.equal(totalsOnly.summary.expected, 2);
    assert.equal(totalsOnly.summary.pass, 2);
    assert.equal(totalsOnly.summary.group_attention, 0);
    assert.equal(totalsOnly.summary.reported_totals_attention, 3);
    await page.locator("#reconcile-warnings").filter({hasText: "3 reported-total checks need attention"}).waitFor({state: "visible"});
    await screenshot("totals-attention-desktop");
    await screenshot("totals-attention-mobile", true);
    await page.getByRole("button", {name: "Inspect reported totals"}).click();
    assert.equal(await page.locator("#view-totals").isVisible(), true);
    fs.writeFileSync(path.join(output, "totals-attention-result.json"), JSON.stringify(totalsOnly, null, 2) + "\n");

    assert.deepEqual(Object.fromEntries(expected.files.map(name => [name, digest(name)])), inputHashes, "Original fixture bytes changed");
    assert.deepEqual(external, [], "Unexpected non-local requests");
    assert.deepEqual(browserErrors, [], "Uncaught browser errors");
    assert.deepEqual(apiErrors, [], "Unexpected failed API calls");
    const report = {
      status: "pass", browser: browser.version(), url, inputHashes, downloaded,
      experiment: {rows: 180, candidates: 15, baselines: 2, failedCandidatesRetained: true,
        developmentSelection: development.selected_on_development, selectionFingerprint: development.selection_fingerprint,
        holdoutExplicitlyRevealed: true, transferAcceptanceInitiallyFalse: true},
      reconciliation: {expected: 5, offsettingNetZeroStillAttention: true, incompatibleUnitsBlocked: true,
        independentReportedTotals: true, exportNotesLocked: true, restoredSettingsKeepNotesStale: true,
        reportedTotalsAlertWithoutRowIssues: 3},
      desktop: "1440x1000", mobile: "390x844", sourceFilesUnchanged: true,
      externalRequests: external, browserErrors, apiErrors, humanUsabilityTrial: "not performed"
    };
    fs.writeFileSync(path.join(output, "browser-extensions-result.json"), JSON.stringify(report, null, 2) + "\n");
    console.log("BROWSER_EXTENSIONS_PASS " + path.join(output, "browser-extensions-result.json"));
  } catch (error) {
    if (page && !page.isClosed()) {
      await page.screenshot({path: path.join(output, "failure.png"), fullPage: true}).catch(() => {});
      fs.writeFileSync(path.join(output, "failure.json"), JSON.stringify({message: error.message, stack: error.stack, external, browserErrors, apiErrors, apiRequests}, null, 2) + "\n");
    }
    throw error;
  } finally {
    if (releaseGate) releaseGate();
    if (browser) await browser.close();
    if (server) server.kill("SIGTERM");
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
