/* Exercise actual request capacity with deliberately slow source inspection. */
"use strict";
const {chromium} = require("playwright");
const {spawn} = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

(async () => {
  const output = path.resolve(process.env.LOADER_TEST_OUTPUT || "outputs/browser-loaders");
  fs.mkdirSync(output, {recursive: true});
  const env = {...process.env}; delete env.PYTHONPATH; delete env.PYTHONHOME;
  const code = `import time
from forecast_review_workbench import server as application
original = application.inspect_table
def deliberately_slow(*args, **kwargs):
    time.sleep(0.25)
    return original(*args, **kwargs)
application.inspect_table = deliberately_slow
server = application.WorkbenchServer(0)
print(server.url, flush=True)
server.serve_forever()
`;
  const server = spawn(process.env.TEST_PYTHON || "python3", ["-u", "-c", code], {cwd: output, env});
  let browser, page;
  const apiErrors = [], browserErrors = [], external = [];
  try {
    const url = await new Promise((resolve, reject) => {
      let text = "";
      const timer = setTimeout(() => reject(new Error("Slow-inspection test server did not start")), 20000);
      server.on("error", reject);
      server.stdout.on("data", data => {
        text += data;
        const match = text.match(/http:\/\/127\.0\.0\.1:\d+/);
        if (match) { clearTimeout(timer); resolve(match[0]); }
      });
      server.on("exit", code => { clearTimeout(timer); reject(new Error("Test server exited: " + code)); });
    });
    browser = await chromium.launch({headless: true, ...(process.env.TEST_CHROME_PATH ? {executablePath: process.env.TEST_CHROME_PATH} : {})});
    const context = await browser.newContext();
    await context.route("**/*", route => {
      if (route.request().url().startsWith(url + "/")) return route.continue();
      external.push(route.request().url()); return route.abort();
    });
    page = await context.newPage();
    page.setDefaultTimeout(20000);
    page.on("pageerror", e => browserErrors.push(e.message));
    page.on("response", r => { if (r.status() >= 400) apiErrors.push([r.url(), r.status()]); });
    await page.goto(url);
    await page.locator("#example-button").click();
    await page.waitForFunction(() => {
      const node = document.getElementById("accept-common-sample");
      return node && !node.disabled;
    });
    assert.equal(await page.locator("#error").isVisible(), false);

    const sample = await (await context.request.get(url + "/api/example")).json();
    const templates = sample.candidates;
    sample.candidates = Array.from({length: 5}, (_, index) => ({
      ...templates[index % templates.length], id: "candidate-" + index, name: "Transferred candidate " + index
    }));
    await page.evaluate(request => sessionStorage.setItem("frw.import.request", JSON.stringify(request)), sample);
    await page.goto(url);
    await page.waitForFunction(() => {
      const node = document.getElementById("accept-common-sample");
      return node && !node.disabled;
    });
    assert.equal(await page.locator("#error").isVisible(), false);
    assert.equal(await page.locator(".source-card").count(), 7);
    assert.equal(await page.locator("#accept-common-sample").isChecked(), false);

    await page.goto(url + "/reconcile");
    await page.locator("#example-button").click();
    await page.waitForFunction(() => {
      const value = document.getElementById("right-totals-value");
      const button = document.getElementById("reconcile-button");
      return value && value.value === "Amount" && !value.disabled && button && !button.disabled;
    });
    await page.locator("#additive").check();
    const response = page.waitForResponse(r => r.url().endsWith("/api/reconcile"));
    await page.locator("#reconcile-button").click();
    const result = await (await response).json();
    assert.equal(result.summary.expected, 3);
    assert.equal(result.summary.breach, 2);
    assert.equal(result.summary.reported_totals_attention, 1);
    assert.deepEqual(apiErrors, []); assert.deepEqual(browserErrors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.join(output, "loader-result.json"), JSON.stringify({
      status: "pass", inspectionDelaySeconds: 0.25, serverRequestCapacity: 2,
      scenarios: ["four-source forecast example", "seven-source maximum transfer", "four-source financial example"],
      apiErrors, browserErrors, externalRequests: external
    }, null, 2));
    console.log("SLOW_SOURCE_LOADERS_PASS " + output);
  } catch (error) {
    fs.writeFileSync(path.join(output, "failure.json"), JSON.stringify({error: error.message, apiErrors, browserErrors, external}, null, 2));
    if (page) { await page.screenshot({path: path.join(output, "failure.png"), fullPage: true}).catch(() => {}); }
    throw error;
  } finally {
    if (browser) await browser.close(); server.kill("SIGTERM");
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
