/* Real file-selection acceptance test against the installed local application. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {spawn, execFileSync} = require("node:child_process");
const {chromium} = require("playwright");

(async () => {
  const output = path.resolve(process.env.BROWSER_TEST_OUTPUT || "outputs/browser-check");
  fs.mkdirSync(output, {recursive: true});
  const python = process.env.TEST_PYTHON || "python3";
  execFileSync(python, [path.join(__dirname, "make_browser_fixtures.py"), output]);
  const files = ["actual.csv", "candidate-a.csv", "candidate-b.xlsx"];
  const digest = name => crypto.createHash("sha256").update(fs.readFileSync(path.join(output, name))).digest("hex");
  const inputHashes = Object.fromEntries(files.map(name => [name, digest(name)]));
  let server;
  let browser;
  try {
    let url = process.env.BROWSER_TEST_URL;
    if (!url) {
      server = spawn(process.env.FORECAST_REVIEW_BIN || "forecast-review", ["--port", "0", "--no-browser"], {cwd: output});
      url = await new Promise((resolve, reject) => {
        let text = "";
        const timeout = setTimeout(() => reject(new Error("Installed server did not start")), 20000);
        server.on("error", reject);
        server.stdout.on("data", data => {
          text += data;
          const match = text.match(/http:\/\/127\.0\.0\.1:\d+/);
          if (match) { clearTimeout(timeout); resolve(match[0]); }
        });
        server.on("exit", code => reject(new Error("Server exited: " + code)));
      });
    }
    browser = await chromium.launch({headless: true, ...(process.env.TEST_CHROME_PATH ? {executablePath: process.env.TEST_CHROME_PATH} : {})});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: true});
    const external = [], errors = [], apiErrors = [];
    let exportGate = null;
    await context.route("**/*", async route => {
      const target = route.request().url();
      if (target.endsWith("/api/export") && exportGate) await exportGate;
      if (target.startsWith(url + "/") || target.startsWith("blob:") || target.startsWith("file:")) return route.continue();
      external.push(target); return route.abort();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => { if (response.url().includes("/api/") && response.status() >= 400) apiErrors.push([response.url(), response.status()]); });
    await page.goto(url);
    assert.equal(await page.locator("#review-file-step").isVisible(), true, "File selection must be the first step");
    assert.equal(await page.locator("#review-settings-step").isVisible(), false, "Settings must not overwhelm the initial file step");
    async function openDetailsFor(selector) {
      const details = page.locator(selector).locator("xpath=ancestor::details[1]");
      if (await details.count() && !await details.evaluate(node => node.open)) await details.locator("summary").first().click();
    }
    async function ready(selector) {
      await page.waitForFunction(selector => {
        const node = document.querySelector(selector);
        return node && !node.disabled;
      }, selector);
    }
    await page.locator("#add-candidate").click();
    async function upload(id, name, date, value, sheet, header) {
      await Promise.all([
        page.waitForResponse(response => response.url().endsWith("/api/inspect")),
        page.locator("#" + id + "-file").setInputFiles(path.join(output, name))
      ]);
      await ready("#" + id + "-header-row");
      if (sheet) {
        await openDetailsFor("#" + id + "-sheet");
        await Promise.all([
          page.waitForResponse(response => response.url().endsWith("/api/inspect")),
          page.locator("#" + id + "-sheet").selectOption(sheet)
        ]);
        await ready("#" + id + "-header-row");
        await openDetailsFor("#" + id + "-header-row");
        await page.locator("#" + id + "-header-row").fill(String(header));
        await Promise.all([
          page.waitForResponse(response => response.url().endsWith("/api/inspect")),
          page.locator("#" + id + "-header-row").press("Tab")
        ]);
        await ready("#" + id + "-header-row");
      }
      await page.locator("#" + id + "-date").selectOption(date);
      await page.locator("#" + id + "-value").selectOption(value);
    }
    await upload("actual", "actual.csv", "report_month", "realised_units");
    await upload("model-a", "candidate-a.csv", "for_month", "estimate_units");
    await upload("candidate-2", "candidate-b.xlsx", "evaluation_month", "output", "Forecasts", 3);
    await page.screenshot({path: path.join(output, "files-desktop.png"), fullPage: true});
    await page.locator("#setup-next").click();
    assert.equal(await page.locator("#review-file-step").isVisible(), false);
    assert.equal(await page.locator("#review-settings-step").isVisible(), true);
    await openDetailsFor("#review-title");
    await page.locator("#review-title").fill("Independent five-period review");
    await page.locator("#target").fill("Illustrative demand");
    await page.locator("#unit").fill("units");
    await page.locator("#scope-start").fill("2025-01");
    await page.locator("#scope-end").fill("2025-05");
    await page.locator("#copy-definition").click();
    await page.screenshot({path: path.join(output, "inputs-desktop.png"), fullPage: true});
    const first = page.waitForResponse(response => response.url().endsWith("/api/review"));
    await page.locator("#run-review").click();
    const pending = await (await first).json();
    assert.equal(pending.summary.expected, 5);
    assert.equal(pending.summary.common, 3);
    assert.equal(pending.summary.excluded, 2);
    assert.equal(pending.comparison_ready, false);
    assert(pending.models.every(model => model.metrics === null));
    await page.screenshot({path: path.join(output, "coverage-desktop.png"), fullPage: true});
    async function accept() {
      const [response] = await Promise.all([
        page.waitForResponse(item => item.url().endsWith("/api/review")),
        page.locator("#accept-common-sample").click()
      ]);
      const result = await response.json();
      await page.locator("#go-review").click();
      return result;
    }
    const result = await accept();
    console.log("Real CSV/XLSX selection, mappings and accepted sample completed.");
    assert.equal(result.comparison_ready, true);
    const a = result.models.find(model => model.id === "model-a");
    const b = result.models.find(model => model.id === "candidate-2");
    assert.equal(Number(a.metrics.mae), 2);
    assert.equal(Number(a.metrics.bias), 0);
    assert(Math.abs(Number(a.metrics.rmse) - Math.sqrt(14 / 3)) < 1e-12);
    assert(Math.abs(Number(b.metrics.mae) - 7 / 3) < 1e-12);
    assert.equal(Number(b.metrics.bias), 1);
    assert.equal(a.vs_baseline, null);
    assert.equal(await page.locator("#chart-panel svg").count() > 0, true);
    await page.locator("#note-decision-model-a").selectOption("needs_evidence");
    await page.locator("#note-text-model-a").fill("Three shared periods support this comparison; obtain the missing fifth-month prediction before judging full-scope performance.");
    await page.screenshot({path: path.join(output, "review-desktop.png"), fullPage: true});
    const downloadReady = page.waitForEvent("download");
    let releaseExport;
    exportGate = new Promise(resolve => { releaseExport = resolve; });
    await page.locator("#export-review").click();
    assert.equal(await page.locator("#note-text-model-a").isDisabled(), true, "Notes must be locked while their export is being prepared");
    assert.equal(await page.locator("#note-decision-model-a").isDisabled(), true);
    releaseExport();
    exportGate = null;
    const download = await downloadReady;
    const zipPath = path.join(output, "real-file-review.zip");
    await download.saveAs(zipPath);
    assert.equal(await download.failure(), null);
    execFileSync(python, [path.join(__dirname, "verify_browser_export.py"), zipPath, output]);
    // Returning to the exact original setting still requires reconsidering old notes.
    await page.locator("#step-inputs").click();
    await openDetailsFor("#actual-source-note");
    await page.locator("#actual-source-note").fill("Temporary revised provenance");
    await page.locator("#actual-source-note").fill("");
    await page.locator("#run-review").click();
    await page.waitForFunction(() => !document.getElementById("accept-common-sample").disabled);
    await accept();
    assert.equal(await page.locator("#note-text-model-a").isDisabled(), true);
    await page.locator("#export-review").click();
    await page.locator("#error").filter({hasText: "earlier run"}).waitFor({state: "visible"});
    await page.getByRole("button", {name: "Rechecked · use for this run"}).click();
    assert.equal(await page.locator("#note-text-model-a").isEnabled(), true);
    assert.equal(await page.locator("#error").isVisible(), false, "Resolved stale-note errors must disappear");
    await page.setViewportSize({width: 390, height: 844});
    for (const stage of ["inputs", "coverage", "review"]) {
      await page.locator("#step-" + stage).click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, stage + " overflows narrow viewport");
      await page.screenshot({path: path.join(output, stage + "-mobile.png"), fullPage: true});
      if (stage === "inputs") {
        await page.locator("#setup-back").click();
        assert.equal(await page.locator("#review-file-step").isVisible(), true);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "File step overflows narrow viewport");
        await page.screenshot({path: path.join(output, "files-mobile.png"), fullPage: true});
        await page.locator("#setup-next").click();
      }
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.locator("#step-inputs").click();
    await page.locator("#unit").fill("different unit");
    const blockedResponse = page.waitForResponse(response => response.url().endsWith("/api/review"));
    await page.locator("#run-review").click();
    const blocked = await (await blockedResponse).json();
    assert(blocked.contract_errors.length > 0);
    assert(blocked.models.every(model => model.metrics === null && model.available_metrics === null));
    assert.equal(await page.locator("#accept-common-sample").isDisabled(), true);
    await page.locator("#step-review").click();
    assert.equal(await page.locator("#chart-panel").count(), 0);
    assert.equal(await page.locator("#note-text-model-a").count(), 0);
    const report = await context.newPage();
    await report.goto("file://" + path.join(output, "unpacked", "report.html"));
    assert.equal(await report.locator("script").count(), 0);
    await report.screenshot({path: path.join(output, "report-desktop.png"), fullPage: true});
    await report.setViewportSize({width: 390, height: 844});
    assert.equal(await report.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "Offline report overflows");
    await report.screenshot({path: path.join(output, "report-mobile.png"), fullPage: true});
    await page.goto(url);
    await page.locator("#example-button").click();
    await page.waitForFunction(() => {
      const control = document.getElementById("accept-common-sample");
      return control && !control.disabled;
    });
    const example = await accept();
    assert.equal(example.summary.expected, 12);
    assert.equal(example.summary.common, 7);
    const paths = await page.locator("#chart-panel svg path").evaluateAll(nodes => nodes.map(node => node.getAttribute("d")));
    assert(paths.length >= 3);
    assert(paths.every(d => (d.match(/M/g) || []).length === 2), "Chart must break across the two excluded interior periods");
    await page.locator("#panel-review").scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(output, "example-review.png"), fullPage: true});
    await page.locator("#results-content").screenshot({path: path.join(output, "workbench-preview.png")});
    assert.deepEqual(Object.fromEntries(files.map(name => [name, digest(name)])), inputHashes);
    assert.deepEqual(external, [], "Application attempted external requests");
    assert.deepEqual(errors, [], "Uncaught browser errors");
    assert.deepEqual(apiErrors, [], "Unexpected failed API calls");
    fs.writeFileSync(path.join(output, "browser-result.json"), JSON.stringify({status: "pass", browser: browser.version(), expected: 5, common: 3, excluded: 2, inputHashes, requestFingerprint: result.fingerprint, fileSelection: "two CSV files and a two-sheet XLSX with header row 3", desktop: "1440x1000", mobile: "390x844", staleNotes: "blocked until explicit reconsideration even after settings restored", incompatibleUnits: "metrics and plot blocked", sourceFilesUnchanged: true, externalRequests: external, browserErrors: errors, humanUsabilityTrial: "not performed"}, null, 2) + "\n");
    console.log("BROWSER_ACCEPTANCE_PASS " + path.join(output, "browser-result.json"));
  } finally {
    if (browser) await browser.close();
    if (server) server.kill("SIGTERM");
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
