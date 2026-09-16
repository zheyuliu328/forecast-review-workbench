/* Static-site acceptance: real files, explicit decisions, exports and no upload fallback. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {spawn, execFileSync} = require("node:child_process");
const {chromium} = require("playwright");

(async () => {
  const python = process.env.TEST_PYTHON || "python3";
  fs.mkdirSync(path.resolve("outputs"),{recursive:true});
  const output = fs.mkdtempSync(path.resolve("outputs/browser-web-") );
  execFileSync(python, [path.join(__dirname, "make_browser_fixtures.py"), output]);
  const server = spawn(python, ["-u", "-m", "http.server", "0", "--bind", "127.0.0.1", "--directory", path.resolve("out")]);
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Static server did not start")), 20000);
      server.stdout.on("data", data => { const m=String(data).match(/http:\/\/127\.0\.0\.1:\d+/); if(m){clearTimeout(timer);resolve(m[0]);} });
      server.on("error", reject);
    });
    browser = await chromium.launch({headless:true});
    const context = await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
    const external=[], uploads=[], errors=[];
    context.on("request", request => {
      const target=request.url();
      if (!target.startsWith(url+"/") && !target.startsWith("blob:")) external.push(target);
      if(request.method()!=="GET" || target.includes("/api/")) uploads.push({url:target,method:request.method()});
    });
    await context.addInitScript(() => {
      window.__calls=[]; window.__started=[];
      Object.defineProperty(window,"FrwBrowser",{configurable:true,set(api){
        const original=api.request.bind(api);
        api.request=async (endpoint,payload)=>{
          window.__started.push(endpoint);
          const pending=original(endpoint,payload);
          if(window.__cancelFirstInspect && endpoint==="/api/inspect") {window.__cancelFirstInspect=false;api.cancel();}
          const result=await pending;
          window.__calls.push({endpoint,result}); return result;
        };
        Object.defineProperty(window,"FrwBrowser",{value:api,writable:true,configurable:true});
      }});
    });
    const page=await context.newPage(); page.setDefaultTimeout(90000);
    page.on("pageerror", error=>errors.push(error.message));
    async function ready(selector){await page.waitForFunction(selector=>{const n=document.querySelector(selector);return n&&!n.disabled&&!n.closest("fieldset:disabled");},selector);}
    async function action(endpoint,perform){
      const count=await page.evaluate(endpoint=>window.__calls.filter(x=>x.endpoint===endpoint).length,endpoint);
      await perform();
      await page.waitForFunction(({endpoint,count})=>window.__calls.filter(x=>x.endpoint===endpoint).length>count,{endpoint,count});
      return page.evaluate(endpoint=>window.__calls.filter(x=>x.endpoint===endpoint).at(-1).result,endpoint);
    }
    async function openDetails(selector){const d=page.locator(selector).locator("xpath=ancestor::details[1]");if(await d.count()&&!await d.evaluate(n=>n.open))await d.locator("summary").first().click();}
    async function screenshot(name){await page.screenshot({path:path.join(output,name+".png"),fullPage:true});await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+" mobile overflow");await page.screenshot({path:path.join(output,name+"-mobile.png"),fullPage:true});await page.setViewportSize({width:1440,height:1000});}
    async function download(selector,name){const pending=page.waitForEvent("download");await page.locator(selector).click();const item=await pending;const destination=path.join(output,name+".zip");await item.saveAs(destination);assert.equal(await item.failure(),null);await ready(selector);return destination;}
    await page.goto(url);
    assert(await page.locator("#review-file-step").isVisible());
    assert(!await page.locator("#review-settings-step").isVisible());
    await screenshot("start");
    await page.locator("#add-candidate").click();
    async function upload(id,filename,date,value,sheet,header){
      await action("/api/inspect",()=>page.locator("#"+id+"-file").setInputFiles(path.join(output,filename)));
      await ready("#"+id+"-header-row");
      if(sheet){await openDetails("#"+id+"-sheet");await action("/api/inspect",()=>page.locator("#"+id+"-sheet").selectOption(sheet));await ready("#"+id+"-header-row");await openDetails("#"+id+"-header-row");await page.locator("#"+id+"-header-row").fill(String(header));await action("/api/inspect",()=>page.locator("#"+id+"-header-row").press("Tab"));await ready("#"+id+"-header-row");}
      await page.locator("#"+id+"-date").selectOption(date);await page.locator("#"+id+"-value").selectOption(value);
    }
    await upload("actual","actual.csv","report_month","realised_units");
    await upload("model-a","candidate-a.csv","for_month","estimate_units");
    await upload("candidate-2","candidate-b.xlsx","evaluation_month","output","Forecasts",3);
    await page.locator("#setup-next").click();
    await openDetails("#review-title");await page.locator("#review-title").fill("Independent five-period review");
    await page.locator("#target").fill("Illustrative demand");await page.locator("#unit").fill("units");
    await page.locator("#scope-start").fill("2025-01");await page.locator("#scope-end").fill("2025-05");await page.locator("#copy-definition").click();
    const pending=await action("/api/review",()=>page.locator("#run-review").click());
    assert.equal(pending.summary.expected,5);assert.equal(pending.summary.common,3);assert.equal(pending.comparison_ready,false);assert(pending.models.every(m=>m.metrics===null));
    await ready("#accept-common-sample");
    const result=await action("/api/review",()=>page.locator("#accept-common-sample").check());
    assert.equal(result.comparison_ready,true);
    assert.equal(Number(result.models.find(m=>m.id==="model-a").metrics.mae),2);
    assert(Math.abs(Number(result.models.find(m=>m.id==="candidate-2").metrics.mae)-7/3)<1e-12);
    await ready("#go-review");await page.locator("#go-review").click();
    await page.locator("#note-decision-model-a").selectOption("needs_evidence");
    await page.locator("#note-text-model-a").fill("Three shared periods support this comparison; obtain the missing fifth-month prediction before judging full-scope performance.");
    await screenshot("review");
    const reviewZip=await download("#export-review","real-file-review");
    execFileSync(python,[path.join(__dirname,"verify_browser_export.py"),reviewZip,output]);
    await page.locator("#step-inputs").click();await page.locator("#unit").fill("different unit");
    assert(await page.locator("#export-review").isDisabled());
    const blocked=await action("/api/review",()=>page.locator("#run-review").click());
    assert(blocked.contract_errors.length>0);assert(blocked.models.every(m=>m.metrics===null));assert(await page.locator("#accept-common-sample").isDisabled());

    await page.goto(url+"/experiments");
    await page.locator("#example-button").click();await ready("#example-button");await page.locator("#setup-next").click();
    const development=await action("/api/experiments/prepare",()=>page.locator("#prepare-button").click());
    assert.equal(development.stage,"development");assert(development.candidates.every(c=>c.holdout===null));assert(development.predictions.every(r=>r.split!=="holdout"));
    await ready("#experiment-export");assert(await page.locator("#reveal-holdout").isDisabled());
    await download("#experiment-export","development");
    await page.locator("#reveal-acceptance").check();
    const holdout=await action("/api/experiments/reveal",()=>page.locator("#reveal-holdout").click());
    assert.equal(holdout.stage,"holdout");assert.equal(holdout.selection_fingerprint,development.selection_fingerprint);assert.equal(holdout.selected_on_development,development.selected_on_development);
    for(const candidate of holdout.candidates){for(const split of ["development","holdout"]){if(!candidate[split])continue;const rows=holdout.predictions.filter(r=>r.model_id===candidate.id&&r.split===split);const mae=rows.reduce((s,r)=>s+Math.abs(Number(r.prediction)-Number(r.actual)),0)/rows.length;assert(Math.abs(mae-Number(candidate[split].mae))<1e-9);}}
    await ready("#experiment-export");await screenshot("experiment");await download("#experiment-export","holdout");
    await page.locator("#transfer-review").click();await page.waitForURL(url+"/");await ready("#accept-common-sample");
    assert.equal(await page.locator("#accept-common-sample").isChecked(),false);
    assert.equal(await page.evaluate(()=>sessionStorage.getItem("frw.import.request")),null);

    await page.goto(url+"/reconcile");await page.locator("#example-button").click();await ready("#example-button");
    await page.locator("#setup-next").click();assert.equal(await page.locator("#additive").isChecked(),false);
    const reconciliation=await action("/api/reconcile",()=>page.locator("#reconcile-button").click());
    await ready("#reconcile-export");await screenshot("reconciliation");await download("#reconcile-export","reconciliation");
    fs.writeFileSync(path.join(output,"reconciliation-result.json"),JSON.stringify(reconciliation));

    // Cancel during the first inspection of a multi-file example. No later source may restart work.
    for(const route of ["/","/reconcile/"]){
      await page.goto(url+route);await page.evaluate(()=>{window.__cancelFirstInspect=true;});
      await page.locator("#example-button").click();await ready("#example-button");
      assert.equal(await page.evaluate(()=>window.__started.filter(x=>x==="/api/inspect").length),1);
      assert(!await page.locator("#runtime-status").isVisible());assert(await page.locator("#error").isVisible());
    }
    // A missing bridge must never fall back to uploading selected bytes to a static origin.
    await page.route("**/browser.js",route=>route.abort());
    for(const route of ["/","/experiments/","/reconcile/"]){
      await page.goto(url+route);await page.locator("#example-button").click();
      await page.locator("#error").filter({hasText:"文件没有上传"}).waitFor();
      const input=route==="/"?"#actual-file":route.includes("experiments")?"#training-file":"#left-file";
      await page.locator(input).setInputFiles(path.join(output,"actual.csv"));
      await page.getByText("浏览器计算组件未能加载。请刷新后重试；文件没有上传。",{exact:true}).first().waitFor();
    }
    assert.deepEqual(uploads,[]);assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
    // Every ZIP's added runtime metadata and existing files must match its manifest.
    execFileSync(python,["-c",`import hashlib,json,pathlib,sys,zipfile
for p in pathlib.Path(sys.argv[1]).glob('*.zip'):
 with zipfile.ZipFile(p) as z:
  m=json.loads(z.read('manifest.json')); files=m.get('files_sha256') or {k:v['sha256'] for k,v in m['files'].items()}
  assert 'browser-build.json' in files
  for name,digest in files.items(): assert hashlib.sha256(z.read(name)).hexdigest()==digest,(p,name)
  assert b'<script' not in z.read('report.html').lower()
print('All browser ZIP manifests and offline reports verified.')`,output]);
    fs.writeFileSync(path.join(output,"browser-web-result.json"),JSON.stringify({status:"pass",review:{expected:5,common:3},workflows:["review","experiment","reconciliation"],uploads:uploads.length,externalRequests:external.length,mobileOverflow:false,missingBridge:"fails closed",cancel:"stops multi-file inspection",humanTrial:"not performed"},null,2)+"\n");
    console.log("PUBLIC_BROWSER_ACCEPTANCE_PASS "+output);
  } finally {if(browser)await browser.close();server.kill("SIGTERM");}
})().catch(error=>{console.error(error);process.exitCode=1;});
