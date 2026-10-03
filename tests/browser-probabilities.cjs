/* Execute the event-probability task in the self-hosted worker and loopback app. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const {spawn, execFileSync} = require("node:child_process"), {chromium} = require("playwright");
(async () => {
  const python = process.env.TEST_PYTHON || "python3";
  const local = process.argv.includes("--local");
  fs.mkdirSync("outputs", {recursive:true});
  const output = fs.mkdtempSync(path.resolve("outputs/browser-probabilities-"));
  const script = local ? ["-u", "-c", "from forecast_review_workbench.server import WorkbenchServer; s=WorkbenchServer(0); print('http://127.0.0.1:'+str(s.server_port),flush=True); s.serve_forever()"] : ["-u","-m","http.server","0","--bind","127.0.0.1","--directory",path.resolve("out")];
  const server = spawn(python,script); let browser;
  try {
    const url = await new Promise((resolve,reject) => {const t=setTimeout(()=>reject(Error("Server timeout")),20000);server.stdout.on("data",d=>{const m=String(d).match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(t);resolve(m[0]);}});server.on("error",reject);});
    browser=await chromium.launch({headless:true}); const context=await browser.newContext({acceptDownloads:true,viewport:{width:1280,height:900}});
    const external=[], errors=[], uploads=[];
    context.on("request",r=>{if(!r.url().startsWith(url+"/")&&!r.url().startsWith("blob:"))external.push(r.url());if(r.method()!=="GET")uploads.push(r.url());});
    const page=await context.newPage();page.setDefaultTimeout(90000);page.on("pageerror",e=>errors.push(e.message));
    await page.goto(url+"/probabilities");
    const ready=()=>page.waitForFunction(()=>!document.querySelector("#example-button").disabled);
    if(!local){await page.locator("#example-button").click();await page.locator("#runtime-cancel").click();await ready();assert(await page.locator("#export").isDisabled());}
    await page.locator("#example-button").click();await ready();assert.match(await page.locator("#notice").innerText(),/Invented example loaded/);
    async function accept(){await page.locator("#check-sample").click();await ready();assert(await page.locator("#scores").isHidden());await page.locator("#accept-common").check();await ready();}
    await accept();assert.equal(await page.locator("#exclusions tbody tr").count(),3);assert.match(await page.locator("#exclusions").innerText(),/pending/);assert.match(await page.locator("#metrics").innerText(),/0.0625/);
    await page.locator("#edit-inputs").click();await page.locator("#evaluation-as-of").fill("2025-01-04");assert(await page.locator("#export").isDisabled());assert(!await page.locator("#accept-common").isChecked());await accept();assert.match(await page.locator("#metrics").innerText(),/Infinite/);assert.match(await page.locator("#metrics").innerText(),/0.375/);
    const pending=page.waitForEvent("download");await page.locator("#export").click();const d=await pending;const zip=path.join(output,"later.zip");await d.saveAs(zip);await ready();
    const verification=execFileSync(python,["-c",`import sys,json,zipfile,hashlib
from forecast_review_workbench.probabilities import review_probabilities
with zipfile.ZipFile(sys.argv[1]) as z:
 q=json.loads(z.read('request.json')); r=json.loads(z.read('results.json')); m=json.loads(z.read('manifest.json'))
 assert r==review_probabilities(q)
 for name,h in m['files_sha256'].items(): assert hashlib.sha256(z.read(name)).hexdigest()==h
 assert r['common']==3 and r['metrics']['a']['brier']=='0.375' and r['metrics']['a']['log_loss_status']=='infinite'
 assert b'Infinite' in z.read('report.html')
 print(json.dumps({'native_equal':True,'manifest_valid':True,'common':3}))`,zip],{encoding:"utf8"});
    // Missing baseline key excludes it for everyone; conflicting definitions block acceptance.
    await page.locator("#edit-inputs").click();await page.locator("#baseline-event").fill("Different event");await page.locator("#check-sample").click();await ready();assert(await page.locator("#accept-common").isDisabled());assert.match(await page.locator("#conflicts").innerText(),/differs/);
    await page.locator("#edit-inputs").click();await page.locator("#copy-contract").click();
    const missing=path.join(output,"missing-baseline.csv");fs.writeFileSync(missing,"Origin,Probability\n2025-01-01,0.5\n2025-01-02,0.5\n");await page.locator("#baseline-file").setInputFiles(missing);await ready();await accept();assert.equal(await page.locator("#metrics tbody tr").first().locator("td").nth(2).innerText(),"2");
    await page.screenshot({path:path.join(output,"desktop.png"),fullPage:true});await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(output,"narrow.png"),fullPage:true});
    // Fresh own files, blank pending label and Excel non-first sheet/header3.
    await page.reload();const labels=path.join(output,"own-labels.csv"), probs=path.join(output,"own.xlsx");fs.writeFileSync(labels,"Origin,Label,Available\n2025-01-01,0,2025-01-02\n2025-01-02,1,2025-01-03\n2025-01-03,,2025-01-04\n");
    execFileSync(python,["-c","from openpyxl import Workbook;import sys;w=Workbook();w.active.title='Notes';w.active.append(['Invented task']);s=w.create_sheet('Probabilities');s.append(['Original invented probabilities']);s.append([]);s.append(['Origin','Probability']);s.append(['2025-01-01',.2]);s.append(['2025-01-02',.8]);s.append(['2025-01-03',0]);w.save(sys.argv[1])",probs]);
    await page.locator("#labels-file").setInputFiles(labels);await ready();await page.locator("#a-file").setInputFiles(probs);await ready();
    for(const [id,value] of [["a-sheet","Probabilities"],["a-header-row","3"]]){const detail=page.locator("#"+id).locator("xpath=ancestor::details[1]");if(!await detail.evaluate(n=>n.open))await detail.locator("summary").click();if(id.endsWith("sheet"))await page.locator("#"+id).selectOption(value);else{await page.locator("#"+id).fill(value);await page.locator("#"+id).press("Tab");}await ready();}
    await page.locator("#event-definition").fill("Invented binary event from a fixed observation window");await page.locator("#evaluation-as-of").fill("2025-01-03");await page.locator("#expected-keys").fill("2025-01-01\n2025-01-02\n2025-01-03");await page.locator("#copy-contract").click();await page.locator("#check-sample").click();await ready();assert.match(await page.locator("#error").innerText(),/describe the source/);
    for(const id of ["labels","a"])await page.locator("#"+id+"-note").fill("Original invented acceptance inputs");await accept();assert.match(await page.locator("#metrics").innerText(),/0.04/);assert.match(await page.locator("#exclusions").innerText(),/pending/);
    await page.locator("#edit-inputs").click();await page.locator("#evaluation-as-of").fill("2025-01-04");await accept();assert.equal(await page.locator("#metrics tbody tr").first().locator("td").nth(2).innerText(),"2");await page.getByText("Inspect every original input row",{exact:true}).click();assert.match(await page.locator("#input-rows").innerText(),/invalid/);
    const good=path.join(output,"completed-labels.csv");fs.writeFileSync(good,fs.readFileSync(labels,"utf8").replace("2025-01-03,,","2025-01-03,1,"));await page.locator("#edit-inputs").click();await page.locator("#labels-file").setInputFiles(good);await ready();await accept();assert.match(await page.locator("#metrics").innerText(),/0.36/);assert.match(await page.locator("#metrics").innerText(),/Infinite/);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);if(!local)assert.deepEqual(uploads,[]);
    fs.writeFileSync(path.join(output,"verification.json"),JSON.stringify({mode:local?"loopback":"worker",...JSON.parse(verification),errors,external,uploads},null,2));console.log(output);
  }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exit(1);});
