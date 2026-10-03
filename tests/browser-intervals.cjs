/* Execute the supplied-interval task in the self-hosted worker and loopback app. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const {spawn, execFileSync} = require("node:child_process"), {chromium} = require("playwright");
(async () => {
  const python = process.env.TEST_PYTHON || "python3";
  const local = process.argv.includes("--local");
  fs.mkdirSync("outputs", {recursive:true});
  const output = fs.mkdtempSync(path.resolve("outputs/browser-intervals-"));
  const script = local ? ["-u", "-c", "from forecast_review_workbench.server import WorkbenchServer; s=WorkbenchServer(0); print('http://127.0.0.1:'+str(s.server_port),flush=True); s.serve_forever()"] : ["-u","-m","http.server","0","--bind","127.0.0.1","--directory",path.resolve("out")];
  const server = spawn(python,script); let browser;
  try {
    const url = await new Promise((resolve,reject) => {const t=setTimeout(()=>reject(Error("Server timeout")),20000);server.stdout.on("data",d=>{const m=String(d).match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(t);resolve(m[0]);}});server.on("error",reject);});
    browser=await chromium.launch({headless:true}); const context=await browser.newContext({acceptDownloads:true,viewport:{width:1280,height:900}});
    const external=[], errors=[], uploads=[];
    context.on("request",r=>{if(!r.url().startsWith(url+"/")&&!r.url().startsWith("blob:"))external.push(r.url());if(r.method()!=="GET")uploads.push(r.url());});
    const page=await context.newPage();page.setDefaultTimeout(90000);page.on("pageerror",e=>errors.push(e.message));
    await page.goto(url+"/intervals");
    const ready=()=>page.waitForFunction(()=>!document.querySelector("#example-button").disabled);
    await page.locator("#example-button").click();await ready();
    assert.match(await page.locator("#notice").innerText(),/Invented example loaded/);
    await page.locator("#check-sample").click();await ready();
    assert.match(await page.locator("#sample-summary").innerText(),/4/);assert(await page.locator("#scores").isHidden());
    await page.locator("#accept-common").check();await ready();
    assert(await page.locator("#scores").isVisible());
    const table=await page.locator("#metrics tbody tr").allTextContents();assert.equal(table.length,3);assert.match(table[2],/4.25/);
    const promise=page.waitForEvent("download");await page.locator("#export").click();const d=await promise;const zip=path.join(output,"example.zip");await d.saveAs(zip);await ready();
    const verification=execFileSync(python,["-c",`import sys,json,zipfile,hashlib
from forecast_review_workbench.intervals import review_intervals
with zipfile.ZipFile(sys.argv[1]) as z:
 r=json.loads(z.read('results.json')); q=json.loads(z.read('request.json')); m=json.loads(z.read('manifest.json'))
 assert r==review_intervals(q)
 for name,h in m['files_sha256'].items(): assert hashlib.sha256(z.read(name)).hexdigest()==h
 assert [r['metrics'][s]['mean_interval_score'] for s in ('A','B','C')]==['1','20','4.25']
 assert r['common']==4
 print(json.dumps({'common':r['common'],'native_equal':True,'manifest_valid':True}))`,zip],{encoding:"utf8"});
    await page.locator("#B-definition-nominal_coverage").fill("0.95");assert(await page.locator("#sample").isHidden());assert(await page.locator("#export").isDisabled());assert(!await page.locator("#accept-common").isChecked());
    await page.locator("#check-sample").click();await ready();assert.match(await page.locator("#conflicts").innerText(),/nominal coverage/);assert(await page.locator("#accept-common").isDisabled());
    await page.locator("#B-definition-nominal_coverage").fill("0.8");
    const bad=path.join(output,"bad.csv"), good=path.join(output,"good.csv");
    fs.writeFileSync(bad,"Origin,Target,Lower,Upper\n2024-01-01,2024-01-02,2,1\n2024-01-01,2024-01-03,0.5,1.5\n2024-01-01,2024-01-04,1.5,2.5\n2024-01-01,2024-01-05,2.5,3.5\n");
    fs.writeFileSync(good,fs.readFileSync(bad,"utf8").replace(",2,1\n",",-0.5,0.5\n"));
    await page.locator("#A-file").setInputFiles(bad);await ready();await page.locator("#check-sample").click();await ready();
    assert.match(await page.locator("#exclusions").innerText(),/2024-01-02/);await page.locator("#accept-common").check();await ready();assert.equal(await page.locator("#metrics tbody tr").first().locator("td").nth(1).innerText(),"3");
    await page.locator("#A-file").setInputFiles(good);await ready();await page.locator("#check-sample").click();await ready();await page.locator("#accept-common").check();await ready();assert.equal(await page.locator("#metrics tbody tr").first().locator("td").nth(1).innerText(),"4");
    // A user-owned workbook: non-first worksheet and a header below title rows.
    const xlsx=path.join(output,"own.xlsx");execFileSync(python,["-c","from openpyxl import Workbook; import sys; w=Workbook(); w.active.title='Notes'; w.active.append(['Invented test']); s=w.create_sheet('Bounds'); s.append(['Invented bounds']); s.append([]); s.append(['Origin','Target','Lower','Upper']); [s.append(['2024-01-01','2024-01-%02d'%(i+2),i-.5,i+.5]) for i in range(4)]; w.save(sys.argv[1])",xlsx]);
    await page.locator("#A-file").setInputFiles(xlsx);await ready();
    const sheetDetails=page.locator("#A-sheet").locator("xpath=ancestor::details[1]"); if(!await sheetDetails.evaluate(n=>n.open))await sheetDetails.locator("summary").click();
    await page.locator("#A-sheet").selectOption("Bounds");await ready();
    const details=page.locator("#A-header-row").locator("xpath=ancestor::details[1]");if(!await details.evaluate(n=>n.open))await details.locator("summary").click();
    await page.locator("#A-header-row").fill("3");await page.locator("#A-header-row").press("Tab");await ready();
    await page.locator("#check-sample").click();await ready();await page.locator("#accept-common").check();await ready();assert.equal(await page.locator("#metrics tbody tr").first().locator("td").nth(4).innerText(),"1");
    await page.screenshot({path:path.join(output,"desktop.png"),fullPage:true});await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"narrow overflow");await page.screenshot({path:path.join(output,"narrow.png"),fullPage:true});
    // Delay one real inspection to check that remounting actions are locked.
    await page.evaluate(() => {const host=window.FrwBrowser || window; const key=window.FrwBrowser ? "request" : "fetch"; const original=host[key].bind(host);window.__holdInspection=null;host[key]=async (...args)=>{if(args[0]==="/api/inspect"){await new Promise(resolve=>window.__holdInspection=resolve);host[key]=original;}return original(...args);};});
    await page.locator("#A-file").setInputFiles(good);await page.waitForFunction(()=>Boolean(window.__holdInspection));
    assert(await page.locator("#copy-contract").isDisabled());assert(await page.getByRole("button",{name:"Remove Interval B",exact:true}).isDisabled());
    await page.evaluate(()=>window.__holdInspection());await ready();assert(await page.locator("#A-target").isEnabled());
    // A fresh own-file task cannot inherit the example's provenance declarations.
    await page.reload();const actual=path.join(output,"own-actual.csv");fs.writeFileSync(actual,"Target,Actual\n2024-01-02,0\n2024-01-03,1\n2024-01-04,2\n2024-01-05,3\n");
    for(const [id,file] of [["actual",actual],["A",good],["B",good]]){await page.locator("#"+id+"-file").setInputFiles(file);await ready();}
    await page.locator("#common-target").fill("Invented cash flow");await page.locator("#common-unit").fill("USD");await page.locator("#copy-contract").click();
    await page.locator("#expected-keys").fill([2,3,4,5].map(i=>"2024-01-01\t2024-01-0"+i+"\t").join("\n"));
    await page.locator("#check-sample").click();await ready();assert.match(await page.locator("#error").innerText(),/Actual observations: describe the source/);
    for(const id of ["actual","A","B"])await page.locator("#"+id+"-note").fill("Original invented acceptance inputs; no fitted model.");
    await page.locator("#check-sample").click();await ready();await page.locator("#accept-common").check();await ready();assert.equal(await page.locator("#metrics tbody tr").first().locator("td").nth(1).innerText(),"4");
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);if(!local)assert.deepEqual(uploads,[]);
    fs.writeFileSync(path.join(output,"verification.json"),JSON.stringify({mode:local?"loopback":"worker",...JSON.parse(verification),errors,external,uploads},null,2));console.log(output);
  } finally {if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exit(1);});
