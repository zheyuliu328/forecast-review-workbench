"use strict";
(function () {
  const U = window.WorkbenchUI, $ = id => document.getElementById(id);
  const definitions = [["target", "Target quantity"], ["unit", "Value unit"], ["transformation", "Transformation"], ["nominal_coverage", "Nominal central coverage (fraction)"]];
  const common = {target: "", unit: "", transformation: "none", nominal_coverage: "0.8"};
  let sources = [], cards = [], revision = 0, busy = false, result = null, request = null, nextId = 1;
  function fresh(id, name, actual) { const item = U.source(id, name); item.actual = actual; item.contract = {...common}; if (actual) delete item.contract.nominal_coverage; item.source_note = ""; return item; }
  function invalidate() { revision++; result = null; request = null; $("accept-common").checked = false; $("sample").hidden = true; U.clearMessages(); update(); }
  function update() {
    const loading = sources.some(s => s.loading);
    $("interval-fields").disabled = busy || loading;
    $("example-button").disabled = busy || loading;
    $("check-sample").disabled = busy || loading;
    $("add-candidate").disabled = busy || loading || sources.length >= 6;
    $("accept-common").disabled = busy || loading || !result || !result.common || result.contract_errors.length > 0;
    $("export").disabled = busy || loading || !result || !result.comparison_ready;
  }
  function contractFields(contract, prefix, actual) {
    return U.el("div", {className: "form-grid"}, definitions.filter(x => !actual || x[0] !== "nominal_coverage").map(([key, label]) =>
      U.field(label, U.el("input", {id: prefix + "-" + key, value: contract[key] || "", oninput: e => {contract[key] = e.target.value; invalidate();}}))));
  }
  function mount() {
    $("sources").replaceChildren(); cards = [];
    sources.forEach(item => {
      const host = U.el("div", {className: "panel"}); $("sources").append(host);
      cards.push(U.fileCard(host, item, {
        changed: invalidate, updated: update,
        inspected: s => {
          const patterns = {origin: /^(origin|forecast[_ ]?origin|cutoff)$/i, target: /^(target|target[_ ]?date|date)$/i, entity: /^(entity|series|entity[_ ]?id)$/i, actual: /^(actual|observed|value)$/i, lower: /^(lower|lower[_ ]?bound)$/i, upper: /^(upper|upper[_ ]?bound)$/i};
          Object.entries(patterns).forEach(([key, re]) => {if (!s.headers.includes(s.mapping[key])) s.mapping[key] = s.headers.find(h => re.test(h)) || null;});
        },
        mapping: (s, disabled) => U.el("div", {className: "form-grid"}, (s.actual ? ["target", "actual", "entity"] : ["origin", "target", "lower", "upper", "entity"]).map(key =>
          U.field(key === "entity" ? "Entity (optional)" : key[0].toUpperCase() + key.slice(1), U.select(U.columns(s, key === "entity" ? "Single series" : "Select a column"), s.mapping[key], e => {s.mapping[key] = e.target.value || null; invalidate();}, {id: s.id + "-" + key, disabled}))))
      }));
      const details = U.el("details", {className: "panel", open: true}, [U.el("summary", {}, item.name + " definitions"), contractFields(item.contract, item.id + "-definition", item.actual),
        U.field("Source note (required)", U.el("input", {id: item.id + "-note", value: item.source_note, placeholder: "Where did these values come from?", oninput: e => {item.source_note = e.target.value; invalidate();}}))]);
      if (!item.actual) details.append(U.button("Remove " + item.name, () => {item.epoch++; sources = sources.filter(s => s !== item); invalidate(); mount();}, {disabled: sources.length <= 2}));
      $("sources").append(details);
    }); update();
  }
  function buildRequest(accepted) {
    if (sources.length < 2) throw new Error("Select actuals and at least one interval file.");
    const rows = $("expected-keys").value.split(/\r?\n/).filter(line => line !== "");
    if (!rows.length || rows.length > 5000) throw new Error("Expected schedule: supply 1 to 5,000 tab-separated rows.");
    const expected = rows.map((line, i) => {const parts = line.split("\t"); if (parts.length < 2 || parts.length > 3) throw new Error("Expected schedule line " + (i+1) + ": use origin, target and optional entity, separated by tabs."); return {origin: parts[0], target: parts[1], entity: parts[2] || ""};});
    const payloads = sources.map(s => {
      U.requireSource(s);
      if (!s.source_note.trim()) throw new Error(s.name + ": describe the source of these values in the source note.");
      const keys = s.actual ? ["target", "actual", "entity"] : ["origin", "target", "lower", "upper", "entity"];
      const mapping = Object.fromEntries(keys.map(k => {if (k !== "entity" && !s.mapping[k]) throw new Error(s.name + ": select the " + k + " column."); return [k, s.mapping[k] || null];}));
      return {id: s.id, file: s.file, sheet: s.sheet, header_row: s.header_row, mapping, contract: {...s.contract}, source_note: s.source_note};
    });
    return {task: "interval_review", schema_version: 1, title: $("title").value, contract: {...common}, expected_keys: expected, actual: payloads[0], candidates: payloads.slice(1), accept_common_sample: accepted};
  }
  function render() {
    $("sample").hidden = false;
    $("sample-summary").replaceChildren(U.stat("Expected", result.expected, "Planned forecast keys"), U.stat("Eligible shared keys", result.common, "Same sample across all candidates"), U.stat("Excluded", result.excluded, "Retained below and in exports"));
    $("conflicts").replaceChildren(...result.contract_errors.map(x => U.el("p", {className: "notice notice-error"}, x)));
    U.pagedTable($("exclusions"), result.evaluation_rows.filter(r => !r.included), [{key:"origin",label:"Origin"},{key:"target",label:"Target"},{key:"entity",label:"Entity"},{key:"states",label:"Source status"}]);
    U.pagedTable($("input-rows"), result.input_rows, [{key:"source",label:"Source"},{key:"row",label:"Original row"},{key:"status",label:"Status"},{key:"reason",label:"Reason"},{key:"raw",label:"Original cells"}]);
    $("scores").hidden = !result.comparison_ready;
    $("accept-common").checked = result.accepted_common_sample;
    $("score-context").textContent = "Nominal coverage: " + result.contract.nominal_coverage + "; unit: " + result.contract.unit + "; transformation: " + result.contract.transformation + ".";
    const keys = ["n","empirical_interval_coverage","mean_width","mean_interval_score","lower_misses","upper_misses"];
    $("metrics").replaceChildren(U.table(["Candidate", "Common n", "Observed containment", "Mean width", "Mean interval score", "Lower misses", "Upper misses"], Object.entries(result.metrics).map(([id,m]) => U.el("tr", {}, [U.cell(id), ...keys.map(k => U.cell(m ? m[k] : "Not scored"))]))));
    U.pagedTable($("groups"), result.group_results.flatMap(g => Object.entries(g.metrics).map(([candidate,m]) => ({...g, candidate, ...(m || {})}))), [{key:"entity",label:"Entity"},{key:"horizon_days",label:"Horizon days"},{key:"common",label:"Shared n"},{key:"candidate",label:"Candidate"},{key:"empirical_interval_coverage",label:"Containment"},{key:"mean_width",label:"Width"},{key:"mean_interval_score",label:"Score"}]);
  }
  async function run(accepted) {
    if (busy) return;
    U.clearMessages(); result = null; request = null; if (!accepted) $("sample").hidden = true; $("scores").hidden = true;
    const current = revision; busy = true; update();
    try {const req = buildRequest(accepted); const res = await U.api("/api/intervals/review", req); if (revision !== current) return; request = req; result = res; render();}
    catch(e) {if (revision === current) {$("sample").hidden = true; $("accept-common").checked = false; U.message(e.message, true);}}
    finally {busy = false; update();}
  }
  $("interval-form").addEventListener("submit", e => {e.preventDefault(); run(false);});
  $("accept-common").addEventListener("change", e => run(e.target.checked));
  ["expected-keys", "title"].forEach(id => $(id).addEventListener("input", invalidate));
  $("common-contract").append(contractFields(common, "common", false));
  $("copy-contract").addEventListener("click", () => {sources.forEach(s => {s.contract = {...common}; if(s.actual) delete s.contract.nominal_coverage;}); invalidate(); mount();});
  $("add-candidate").addEventListener("click", () => {const id = "candidate-" + nextId++; sources.push(fresh(id, id, false)); invalidate(); mount();});
  $("example-button").addEventListener("click", async () => {
    invalidate(); busy = true; update(); const current = revision;
    try {
      const req = await U.api("/api/intervals/example"); if (revision !== current) return;
      sources.forEach(s => s.epoch++);
      Object.assign(common, req.contract); $("common-contract").replaceChildren(contractFields(common, "common", false));
      sources = [req.actual, ...req.candidates].map((entry, i) => Object.assign(U.restoreSource(entry.id, i ? "Interval " + entry.id : "Actual observations", entry), {actual: i === 0, contract: {...entry.contract}, source_note: entry.source_note || ""}));
      $("expected-keys").value = req.expected_keys.map(k => [k.origin,k.target,k.entity].join("\t")).join("\n"); $("title").value = req.title;
      mount(); for (const card of cards) await card.inspect(true);
      U.message("Invented example loaded. A and B contain all four observations, but B is much wider. C misses three. Check the sample before comparing.");
    } catch(e) {U.message(e.message,true);} finally {busy = false; update();}
  });
  $("export").addEventListener("click", async () => {
    if (!result || !result.comparison_ready || busy) return;
    const current = revision; busy = true; update();
    try {await U.download("/api/intervals/export", {request, fingerprint: result.fingerprint}, "prediction-interval-review", () => revision === current && Boolean(result));}
    catch(e) {U.message(e.message,true);} finally {busy = false; update();}
  });
  sources = [fresh("actual", "Actual observations", true), fresh("A", "Interval A", false), fresh("B", "Interval B", false)]; mount();
})();
