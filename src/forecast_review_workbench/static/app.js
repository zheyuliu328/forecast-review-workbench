/* The workbench uses browser-selected file bytes and loopback API requests only. */
"use strict";

(function () {
  const $ = function (id) { return document.getElementById(id); };
  const COLORS = ["#2a7865", "#be7744", "#6277a9", "#92769c", "#9a913e", "#879b91"];
  const PAGE_SIZE = 25;
  const MAX_BYTES = 10 * 1024 * 1024;
  const state = {
    title: "Forecast review", schemaVersion: 1, horizonsText: "1, 2", chartHorizon: 1,
    scope: {start: "", end: "", frequency: "monthly", entities: []},
    contract: {target: "", unit: "", horizon: 1, transformation: "none"},
    actual: null, candidates: [], baseline: null, segments: [],
    result: null, resultRequest: null, dirty: true, revision: 0, busy: false,
    stage: "inputs", notes: {}, chartMode: "trend", chartEntity: "",
    diagnosticTab: "expected", diagnosticSearch: "", diagnosticFilter: "all", diagnosticPage: 1,
    sourceCounter: 1
  };
  let inputFlow;

  function append(parent, child) {
    if (Array.isArray(child)) child.forEach(function (item) { append(parent, item); });
    else if (child !== null && child !== undefined && child !== false) {
      parent.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    }
  }

  function element(tag, attributes, children) {
    const result = document.createElement(tag);
    const attrs = attributes || {};
    Object.keys(attrs).forEach(function (key) {
      const value = attrs[key];
      if (key === "value" || key === "checked") return;
      if (key.indexOf("on") === 0 && typeof value === "function") result.addEventListener(key.slice(2), value);
      else if (key === "className") result.className = value;
      else if (value !== null && value !== undefined && value !== false) result.setAttribute(key, value === true ? "" : String(value));
    });
    append(result, children);
    if (Object.prototype.hasOwnProperty.call(attrs, "value")) result.value = attrs.value === null ? "" : attrs.value;
    if (Object.prototype.hasOwnProperty.call(attrs, "checked")) result.checked = Boolean(attrs.checked);
    return result;
  }

  function button(text, className, action, attrs) {
    return element("button", Object.assign({type: "button", className: className || "button", onclick: action}, attrs || {}), text);
  }

  function field(label, control, help) {
    return element("label", {className: "field"}, [element("span", {}, label), control, help ? element("small", {}, help) : null]);
  }

  function select(options, current, action, attrs) {
    return element("select", Object.assign({value: current === null ? "" : current, onchange: action}, attrs || {}),
      options.map(function (option) {
        const item = typeof option === "string" ? {value: option, label: option} : option;
        return element("option", {value: item.value}, item.label);
      }));
  }

  function textValue(value) { return value === null || value === undefined ? "—" : String(value); }
  function number(value) {
    if (value === null || value === undefined || value === "") return "—";
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return String(value);
    if (parsed === 0) return "0";
    if (Math.abs(parsed) >= 1e9 || Math.abs(parsed) < 0.00001) return parsed.toExponential(4);
    return new Intl.NumberFormat("en", {maximumSignificantDigits: 7}).format(parsed);
  }
  function metricCell(value, attrs) { return element("td", Object.assign({className: "numeric", title: textValue(value)}, attrs || {}), number(value)); }
  function sourceLabel(id) {
    const source = allSources().find(function (entry) { return entry.id === id; });
    return source ? source.name : id;
  }
  function allSources() { return [state.actual].concat(state.candidates, state.baseline ? [state.baseline] : []).filter(Boolean); }
  function horizons(value) { return String(value).split(",").map(function(v) { return /^\s*[1-9][0-9]*\s*$/.test(v) ? Number(v.trim()) : NaN; }); }
  function sharedContract(role) {
    const c = Object.assign({}, state.contract, {frequency: state.scope.frequency});
    if (state.schemaVersion === 2) { delete c.horizon; if (role === "actual") delete c.horizons; else c.horizons = horizons(state.horizonsText); }
    else delete c.horizons;
    return c;
  }
  function makeSource(id, name, role) {
    return {id: id, name: name, role: role, file: null, sheet: null, header_row: 1,
      mapping: {date: null, value: null, entity: null}, contract: sharedContract(role), source_note: "",
      headers: [], sheets: [], preview: [], row_count: null, inspectionError: "", loading: false, epoch: 0, declarationOpen: false};
  }
  state.actual = makeSource("actual", "Actual", "actual");
  state.candidates = [makeSource("model-a", "Forecast A", "candidate")];

  function showMessage(text, isError) {
    const target = isError ? $("error") : $("notice");
    const other = isError ? $("notice") : $("error");
    other.classList.add("hidden");
    target.textContent = text;
    target.classList.toggle("hidden", !text);
    if (isError) target.scrollIntoView({behavior: "smooth", block: "center"});
  }
  function clearMessages() { $("notice").classList.add("hidden"); $("error").classList.add("hidden"); }
  function tokenHeaders() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return {"Content-Type": "application/json", "X-Workbench-Token": meta ? meta.content : ""};
  }
  async function api(url, payload) {
    const browser = window.WorkbenchUI.transport();
    if (browser) return browser.request(url, payload);
    const options = {credentials: "same-origin", headers: tokenHeaders(), method: payload === undefined ? "GET" : "POST"};
    if (payload !== undefined) options.body = JSON.stringify(payload);
    let response;
    try { response = await fetch(url, options); }
    catch (_error) { throw new Error("The local workbench is not responding. Keep the application running and try again."); }
    let data;
    try { data = await response.json(); }
    catch (_error) { throw new Error("The local application returned an unreadable response. Try the review again."); }
    if (!response.ok) throw new Error(data.error || "The request could not be completed.");
    return data;
  }

  function markNotesStale() {
    Object.values(state.notes).forEach(function (note) {
      if (note.text.trim() || note.decision) note.stale = true;
    });
  }
  let exportURL = null;
  function clearExport() {
    if (exportURL) { URL.revokeObjectURL(exportURL); exportURL = null; }
    document.getElementById("save-review-link")?.remove();
  }
  $("notes").addEventListener("input", clearExport);
  $("notes").addEventListener("change", clearExport);
  function invalidate() {
    clearExport();
    state.revision += 1;
    state.dirty = true;
    state.resultRequest = null;
    markNotesStale();
    allSources().forEach(refreshSourcePresentation);
    updateChrome();
  }
  function updateChrome() {
    if (inputFlow) inputFlow.update(state.busy || allSources().some(function (source) { return source.loading; }));
    $("run-review").disabled = state.busy || allSources().some(function (source) { return source.loading; });
    $("run-review").textContent = state.busy ? "Checking files…" : "Check comparable sample →";
    $("example-button").disabled = state.busy;
    $("origin-example-button").disabled = state.busy;
    $("step-coverage").disabled = !state.result;
    $("step-review").disabled = !state.result;
    $("go-review").disabled = !state.result || state.dirty || state.busy || !state.result.comparison_ready;
    $("export-review").disabled = !state.result || state.dirty || state.busy;
    $("add-candidate").disabled = state.candidates.length >= 5 || state.busy;
    $("candidate-count").textContent = state.candidates.length + " / 5";
    const acceptanceCheckbox = $("accept-common-sample");
    if (acceptanceCheckbox && state.result) {
      acceptanceCheckbox.disabled = state.busy || state.dirty || (state.result.contract_errors || []).length > 0 || state.result.summary.common <= 0;
      if (!state.busy) acceptanceCheckbox.checked = !state.dirty && Boolean(state.result.accepted_common_sample);
    }
    ["inputs", "coverage", "review"].forEach(function (stage) {
      const active = state.stage === stage;
      $("panel-" + stage).classList.toggle("hidden", !active);
      $("step-" + stage).classList.toggle("active", active);
      if (active) $("step-" + stage).setAttribute("aria-current", "step");
      else $("step-" + stage).removeAttribute("aria-current");
    });
    ["stale-coverage", "stale-review"].forEach(function (id) {
      const target = $(id);
      target.replaceChildren();
      if (state.result && state.dirty) {
        target.appendChild(element("div", {className: "stale-banner"}, [
          element("p", {}, [element("strong", {}, "Inputs changed."), "The previous common-sample acceptance has expired, and previous notes refer to old results. Check the sample again before viewing or exporting results."]),
          button("Back to inputs", "button button-small", function () { goStage("inputs"); })
        ]));
      }
    });
    if (state.result && state.dirty && state.stage !== "inputs") {
      const accept = $("accept-common-sample");
      if (accept) { accept.checked = false; accept.disabled = true; }
      $("results-content").classList.add("hidden");
      $("notes").classList.add("hidden");
    } else {
      $("results-content").classList.remove("hidden");
      $("notes").classList.remove("hidden");
    }
    $("notes").querySelectorAll("select, textarea, button").forEach(function (control) {
      const card = control.closest(".note-card");
      control.disabled = state.busy || (control.tagName !== "BUTTON" && Boolean(card && card.classList.contains("stale")));
    });
  }
  function goStage(stage) {
    if (stage !== "inputs" && !state.result) return;
    state.stage = stage;
    if (stage === "coverage") renderCoverage();
    if (stage === "review") renderReview();
    updateChrome();
    document.querySelector(".step-nav").scrollIntoView({behavior: "smooth", block: "start"});
  }

  function contractMatches(source) {
    const shared = sharedContract(source.role);
    return Object.keys(shared).every(function (key) { return String(source.contract[key]).trim() === String(shared[key]).trim(); });
  }
  function sourceBadge(source) {
    if (source.loading) return element("span", {className: "tag"}, "Reading…");
    if (!source.file) return element("span", {className: "tag"}, "Awaiting selection");
    if (source.inspectionError) return element("span", {className: "tag tag-warning"}, "Check required");
    if (!source.mapping.date || !source.mapping.value || (state.schemaVersion === 2 && source.role !== "actual" && !source.mapping.origin)) return element("span", {className: "tag tag-warning"}, "Confirm fields");
    return element("span", {className: "tag tag-success"}, "Selected fields · " + (source.row_count === null ? "ready" : source.row_count + " rows"));
  }
  function definitionBadge(source) {
    return element("span", {className: "tag " + (contractMatches(source) ? "tag-success" : "tag-warning")}, contractMatches(source) ? "Matches the review definition" : "Definition needs review");
  }
  function refreshSourcePresentation(source) {
    const badge = $("source-badge-" + source.id);
    if (badge) badge.replaceChildren(sourceBadge(source));
    const definition = $("source-definition-badge-" + source.id);
    if (definition) definition.replaceChildren(definitionBadge(source));
    const name = $("source-name-label-" + source.id);
    if (name) name.textContent = source.name || (source.role === "actual" ? "Observed actuals" : "Forecast");
  }
  function inputForSource(source, key, value, action, attrs) {
    return element("input", Object.assign({id: source.id + "-" + key, value: value, oninput: action}, attrs || {}));
  }

  function renderSource(source, index) {
    const roleNames = {actual: "Observed values", candidate: "Forecast to review", baseline: "Baseline forecast (optional)"};
    const letter = source.role === "actual" ? "Y" : source.role === "baseline" ? "B₀" : String(index + 1).padStart(2, "0");
    const headActions = [element("span", {id: "source-badge-" + source.id}, sourceBadge(source))];
    if (source.role !== "actual") headActions.push(button("×", "icon-button", function () {
      if (source.role === "baseline") state.baseline = null;
      else if (state.candidates.length > 1) state.candidates = state.candidates.filter(function (item) { return item.id !== source.id; });
      else return;
      invalidate(); renderSources();
    }, {"aria-label": "Remove " + source.name, disabled: source.role === "candidate" && state.candidates.length <= 1}));
    const fileInput = element("input", {type: "file", id: source.id + "-file", accept: ".csv,.xlsx",
      "aria-label": "Choose " + source.name + " file",
      onchange: function (event) {
        const file = event.target.files && event.target.files[0];
        if (file) readSelectedFile(source, file);
      }});
    const fileControl = element("div", {className: "file-control"}, [
      element("span", {className: "file-symbol", "aria-hidden": "true"}, "▤"),
      element("div", {}, [
        element("span", {className: "file-name"}, source.file ? source.file.name : "Select a CSV or Excel file"),
        element("span", {className: "file-detail"}, source.file ? "Read locally · Original files unchanged" : "Up to 10 MiB · Values read locally")
      ]),
      element("label", {className: "button file-choose", for: source.id + "-file"}, [source.file ? "Replace file" : "Select files", fileInput])
    ]);
    const sheetOptions = [{value: "", label: source.file && source.file.name.toLowerCase().endsWith(".csv") ? "CSV · no worksheet" : "Select a worksheet"}]
      .concat(source.sheets.map(function (name) { return {value: name, label: name}; }));
    const sheetSelect = select(sheetOptions, source.sheet || "", function (event) {
      source.sheet = event.target.value || null; invalidate(); inspectSource(source);
    }, {id: source.id + "-sheet", disabled: !source.file || source.file.name.toLowerCase().endsWith(".csv") || source.loading});
    const headerInput = inputForSource(source, "header-row", source.header_row, function (event) {
      source.header_row = Number(event.target.value); source.inspectionError = "Header row changed. Read the selected header to update mappings."; invalidate();
    }, {type: "number", min: "1", step: "1", disabled: !source.file || source.loading});
    headerInput.addEventListener("change", function () { if (source.file && Number.isInteger(source.header_row) && source.header_row > 0) inspectSource(source); });
    const body = element("div", {className: "source-body"}, []);
    if (source.role !== "actual" && source.file) {
      const nameField = field("Name in results", inputForSource(source, "name", source.name, function (event) {
        source.name = event.target.value; invalidate();
      }, {maxlength: "80", required: true}));
      nameField.classList.add("source-name-field");
      body.appendChild(nameField);
    }
    body.appendChild(fileControl);
    if (source.file) {
      const isCsv = /\.csv$/i.test(source.file.name);
      const sheetField = field("Worksheet", sheetSelect); sheetField.hidden = isCsv;
      body.appendChild(element("details", {className: "table-options", id: source.id + "-table-options", open: Boolean(source.inspectionError || (!isCsv && !source.sheet))}, [
        element("summary", {}, isCsv ? "Header not in row 1? Adjust the starting row" : "Worksheet and header · " + (source.sheet || "Select a worksheet") + " · Row " + source.header_row + " rows"),
        element("div", {className: "form-grid"}, [sheetField, field("Header row", headerInput)]),
        button("Read header again ↻", "text-button", function () { inspectSource(source); }, {disabled: source.loading})
      ]));
    }
    if (source.inspectionError) body.appendChild(element("div", {className: "source-status error", role: "status"}, source.inspectionError));
    if (source.loading) body.appendChild(element("div", {className: "source-status loading", role: "status"}, "Reading selected table…"));

    const mappingChoices = [{value: "", label: "Select a column"}].concat(source.headers.map(function (name) { return {value: name, label: name}; }));
    const mappings = [
      field("Forecast target date", select(mappingChoices, source.mapping.date, function (event) { source.mapping.date = event.target.value || null; invalidate(); }, {id: source.id + "-date", disabled: !source.headers.length || source.loading}), "Select the forecast target date, not the date the forecast was made."),
      field(source.role === "actual" ? "Actual value column" : "Forecast value column", select(mappingChoices, source.mapping.value, function (event) { source.mapping.value = event.target.value || null; invalidate(); }, {id: source.id + "-value", disabled: !source.headers.length || source.loading})),
      field("Entity ID (optional)", select([{value: "", label: "Single series; no entity ID needed"}].concat(mappingChoices.slice(1)), source.mapping.entity, function (event) { source.mapping.entity = event.target.value || null; invalidate(); }, {id: source.id + "-entity", disabled: !source.headers.length || source.loading}))
    ];
    if (state.schemaVersion === 2 && source.role !== "actual") {
      mappings.push(field("Forecast origin date", select(mappingChoices, source.mapping.origin, function(event) { source.mapping.origin = event.target.value || null; invalidate(); }, {id: source.id + "-origin", disabled: source.loading}), "The period when the forecast was made; labels do not prove actual availability."));
      mappings.push(field("Horizon column (optional)", select([{value:"",label:"Derive from origin and target"}].concat(mappingChoices.slice(1)), source.mapping.horizon, function(event) { source.mapping.horizon = event.target.value || null; invalidate(); }, {id:source.id + "-horizon", disabled:source.loading})));
    }
    if (source.headers.length) {
      body.appendChild(element("p", {className: "mapping-suggestion"}, "Fields were suggested from column names. Check them against the preview; suggestions do not verify their meaning."));
      body.appendChild(element("div", {className: "mapping-grid"}, mappings));
    }
    if (source.preview.length || source.headers.length) {
      const previewTable = table(source.headers, source.preview.slice(0, 5).map(function (row) {
        return element("tr", {}, row.map(function (value) { return element("td", {}, textValue(value)); }));
      }));
      const preview = element("details", {open: true}, [
        element("summary", {}, "Check preview · First " + Math.min(5, source.preview.length) + " rows"),
        element("div", {className: "preview-panel table-wrap"}, previewTable)
      ]);
      body.appendChild(element("div", {className: "source-bottom"}, preview));
    }

    const declaration = element("details", {className: "source-contract", open: source.declarationOpen}, []);
    declaration.addEventListener("toggle", function () { source.declarationOpen = declaration.open; });
    declaration.appendChild(element("summary", {}, [
      element("span", {}, source.name + " · Definitions and provenance"),
      element("span", {id: "source-definition-badge-" + source.id}, definitionBadge(source))
    ]));
    const declarationFields = [];
    [["target", "Target"], ["unit", "Unit"]].concat(state.schemaVersion === 1 ? [["horizon", "Forecast horizon"]] : source.role === "actual" ? [] : [["horizons", "Forecast horizons (comma-separated)"]]).concat([["transformation", "Value transformation"]]).forEach(function (pair) {
      const key = pair[0];
      declarationFields.push(field(pair[1], inputForSource(source, "contract-" + key, source.contract[key], function (event) {
        source.contract[key] = key === "horizon" ? Number(event.target.value) : key === "horizons" ? horizons(event.target.value) : event.target.value; invalidate();
      }, key === "horizon" ? {type: "number", min: "1", step: "1", required: true} : {maxlength: "120", required: true})));
    });
    declarationFields.push(field("Frequency", select(["monthly", "quarterly", "daily"], source.contract.frequency, function (event) {
      source.contract.frequency = event.target.value; invalidate();
    }, {id: source.id + "-contract-frequency"})));
    const provenance = field("Source note (optional)", element("input", {id: source.id + "-source-note", value: source.source_note, placeholder: "e.g. Frozen extract supplied by the forecasting team", maxlength: "1000", oninput: function (event) {
      source.source_note = event.target.value; invalidate();
    }}), "This is your source declaration; it has not been independently verified.");
    provenance.classList.add("full");
    declaration.appendChild(element("div", {className: "source-contract-content"}, [
      element("div", {className: "contract-actions"}, [
        element("p", {}, "Describe the file’s actual meaning; declarations must not conceal differences."),
        button("This file uses the review definition", "text-button", function () { source.contract = sharedContract(source.role); invalidate(); renderSources(); })
      ]),
      element("div", {className: "form-grid"}, declarationFields), provenance
    ]));
    $("source-declarations").appendChild(declaration);
    return element("article", {className: "source-card", "aria-label": roleNames[source.role] + ": " + source.name}, [
      element("div", {className: "source-head"}, [
        element("div", {className: "source-heading"}, [
          element("span", {className: "source-letter " + source.role, "aria-hidden": "true"}, letter),
          element("div", {}, [element("h3", {id: "source-name-label-" + source.id}, source.name || roleNames[source.role]), element("span", {className: "role-caption"}, roleNames[source.role])])
        ]),
        element("div", {className: "source-heading-actions"}, headActions)
      ]), body
    ]);
  }

  function renderSources() {
    $("source-declarations").replaceChildren();
    $("actual-source").replaceChildren(renderSource(state.actual, 0));
    $("candidate-sources").replaceChildren.apply($("candidate-sources"), state.candidates.map(renderSource));
    $("baseline-source").replaceChildren();
    $("baseline-source").classList.toggle("baseline-card-wrapper", Boolean(state.baseline));
    if (state.baseline) $("baseline-source").appendChild(renderSource(state.baseline, 0));
    $("add-baseline").classList.toggle("hidden", Boolean(state.baseline));
    updateChrome();
  }

  async function readSelectedFile(source, file) {
    if (!/\.(csv|xlsx)$/i.test(file.name)) { showMessage("Choose a UTF-8 CSV or .xlsx file. Other file types are not supported.", true); return; }
    if (file.size > MAX_BYTES) { showMessage(file.name + " exceeds the 10 MiB file limit. Create a smaller values-only extract.", true); return; }
    clearMessages();
    source.epoch += 1;
    const epoch = source.epoch;
    source.loading = true; source.file = null; source.headers = []; source.preview = []; source.sheet = null; source.sheets = [];
    source.mapping = {date: null, value: null, entity: null};
    source.inspectionError = "";
    invalidate(); renderSources();
    try {
      const content = await new Promise(function (resolve, reject) {
        const reader = new FileReader();
        reader.onload = function () { resolve(String(reader.result).split(",")[1]); };
        reader.onerror = function () { reject(new Error("The selected file could not be read. Choose it again.")); };
        reader.readAsDataURL(file);
      });
      if (source.epoch !== epoch || !allSources().includes(source)) return;
      source.file = {name: file.name, content_base64: content};
      await inspectSource(source);
    } catch (error) {
      if (source.epoch === epoch) { source.loading = false; source.inspectionError = error.message; renderSources(); }
    }
  }

  function uniqueHeader(headers, matcher) {
    const matches = headers.filter(function (name) { return matcher.test(name); });
    return matches.length === 1 ? matches[0] : null;
  }

  async function inspectSource(source, propagateAbort = false) {
    if (!source.file) return;
    source.epoch += 1;
    const epoch = source.epoch;
    source.loading = true; source.inspectionError = "";
    renderSources();
    try {
      const inspection = await api("/api/inspect", {file: source.file, sheet: source.sheet, header_row: source.header_row});
      if (epoch !== source.epoch || !allSources().includes(source)) return;
      source.headers = inspection.headers || [];
      source.sheets = inspection.sheets || [];
      source.preview = inspection.preview || [];
      source.row_count = inspection.row_count === undefined ? null : inspection.row_count;
      source.inspectionError = inspection.error || "";
      if (inspection.sheet) source.sheet = inspection.sheet;
      ["date", "value", "entity", "origin", "horizon"].forEach(function (key) {
        if (source.mapping[key] && !source.headers.includes(source.mapping[key])) source.mapping[key] = null;
      });
      if (!source.mapping.date) source.mapping.date = uniqueHeader(source.headers, /^(date|period|month|quarter|target|target_period|evaluation_period|target_date|\u65e5\u671f|\u6708\u4efd|\u671f\u95f4|\u5b63\u5ea6|\u76ee\u6807\u65e5\u671f)$/i) || null;
      if (!source.mapping.value) {
        const matcher = source.role === "actual" ? /^(actual|observed|actual_value|target|value|\u5b9e\u9645\u503c|\u5b9e\u9645|\u89c2\u6d4b\u503c|\u6570\u503c)$/i : /^(prediction|predicted|forecast|forecast_value|estimate|value|\u9884\u6d4b\u503c|\u9884\u6d4b|\u4f30\u8ba1\u503c|\u6570\u503c)$/i;
        source.mapping.value = uniqueHeader(source.headers.filter(h => h !== source.mapping.date), matcher) || null;
      }
      if (state.schemaVersion === 2 && source.role !== "actual") {
        if (!source.mapping.origin) source.mapping.origin = uniqueHeader(source.headers, /^(origin|cutoff|forecast_origin|origin_date)$/i) || null;
        if (!source.mapping.horizon) source.mapping.horizon = uniqueHeader(source.headers, /^(horizon|lead|forecast_horizon)$/i) || null;
      }
    } catch (error) {
      if (epoch !== source.epoch) return;
      source.headers = []; source.preview = []; source.inspectionError = error.message;
      if (propagateAbort === true && error.name === "AbortError") throw error;
    } finally {
      if (epoch === source.epoch && allSources().includes(source)) { source.loading = false; renderSources(); }
    }
  }

  function sourcePayload(source) {
    const result = {
      file: source.file, sheet: source.sheet || null, header_row: source.header_row,
      mapping: Object.assign({}, source.mapping),
      contract: {target: String(source.contract.target || "").trim(), unit: String(source.contract.unit || "").trim(),
        horizon: Number(source.contract.horizon), transformation: String(source.contract.transformation || "").trim(),
        frequency: source.contract.frequency},
      source_note: source.source_note
    };
    if (state.schemaVersion === 2) {
      delete result.contract.horizon;
      if (source.role !== "actual") result.contract.horizons = source.contract.horizons;
      else { delete result.mapping.origin; delete result.mapping.horizon; }
    } else { delete result.mapping.origin; delete result.mapping.horizon; }
    if (source.role !== "actual") { result.id = source.id; result.name = source.name.trim(); }
    return result;
  }

  function buildRequest(accept) {
    return {
      schema_version: state.schemaVersion, title: state.title.trim() || "Forecast review",
      scope: Object.assign({frequency: state.scope.frequency, entities: state.scope.entities.slice()}, state.schemaVersion === 2 ? {origin_start:state.scope.start.trim(),origin_end:state.scope.end.trim()} : {start:state.scope.start.trim(),end:state.scope.end.trim()}),
      contract: Object.assign({target:state.contract.target.trim(),unit:state.contract.unit.trim(),transformation:state.contract.transformation.trim()}, state.schemaVersion === 2 ? {horizons:horizons(state.horizonsText)} : {horizon:Number(state.contract.horizon)}),
      actual: sourcePayload(state.actual), candidates: state.candidates.map(sourcePayload),
      baseline: state.baseline ? sourcePayload(state.baseline) : null,
      accept_common_sample: Boolean(accept),
      segments: state.segments.map(function (segment) { return {name: segment.name.trim(), start: segment.start.trim(), end: segment.end.trim()}; })
    };
  }

  function validateForm() {
    if (!state.contract.target.trim() || !state.contract.unit.trim() || !state.contract.transformation.trim()) throw new Error("Enter the comparison target, unit, and input transformation.");
    if (state.schemaVersion === 1 && (!Number.isInteger(Number(state.contract.horizon)) || Number(state.contract.horizon) < 1)) throw new Error("The forecast horizon must be a positive integer.");
    if (state.schemaVersion === 2) {
      const hs = horizons(state.horizonsText);
      if (!hs.length || hs.some(h => !Number.isSafeInteger(h) || h < 1 || h > 5000) || new Set(hs).size !== hs.length) throw new Error("Enter distinct positive integer horizons separated by commas (maximum 5,000).");
    }
    if (!state.scope.start.trim() || !state.scope.end.trim()) throw new Error("Enter the originally expected start and end periods.");
    allSources().forEach(function (source) {
      if (!source.file) throw new Error("Select a file: " + source.name);
      if (source.loading) throw new Error("Wait for loading to complete: " + source.name);
      if (source.inspectionError) throw new Error(source.name + ": " + source.inspectionError);
      if (!source.mapping.date || !source.mapping.value) throw new Error("Confirm the date and value columns: " + source.name);
      if (state.schemaVersion === 2 && source.role !== "actual" && !source.mapping.origin) throw new Error("Choose the forecast origin column: " + source.name);
      if (!source.contract.target.trim() || !source.contract.unit.trim() || !source.contract.transformation.trim()) throw new Error("Complete the file definition: " + source.name + "; if consistent, you can explicitly apply a shared definition.");
      if (!source.name.trim()) throw new Error("Give each forecast a name.");
    });
    const mapped = allSources().filter(function (source) { return Boolean(source.mapping.entity); }).length;
    if (mapped && mapped !== allSources().length) throw new Error("Some files have entity columns selected. Select one in every file to compare the same entities.");
    if (mapped && !state.scope.entities.length) throw new Error("Enter the complete expected entity ID list. Existing files cannot establish the full expected scope.");
    if (!mapped && state.scope.entities.length) throw new Error("An entity list is present. Select an entity column in every file, or clear the list for a single series.");
    state.segments.forEach(function (segment) { if (!segment.name.trim() || !segment.start.trim() || !segment.end.trim()) throw new Error("Complete each segment’s name, start, and end period, or remove incomplete segments."); });
  }

  function validateSelectedFiles() {
    allSources().forEach(function (source) {
      if (!source.file) throw new Error("Select the file for “" + source.name + "”.");
      if (source.loading) throw new Error("Please wait for “" + source.name + "” to finish loading.");
      if (source.inspectionError) throw new Error(source.name + ": " + source.inspectionError);
      if (state.schemaVersion === 2 && source.role !== "actual" && !source.mapping.origin) throw new Error("Choose the forecast origin column: " + source.name);
      if (!source.mapping.date || !source.mapping.value) throw new Error("For “" + source.name + "”: confirm the date and value columns.");
      if (!source.name.trim()) throw new Error("Give each forecast a name.");
    });
    if (allSources().some(function (source) { return Boolean(source.mapping.entity); })) $("entity-scope-options").open = true;
  }

  async function runReview(accept, navigate) {
    if (state.busy) return;
    clearExport();
    clearMessages();
    try { validateForm(); }
    catch (error) { showMessage(error.message, true); return; }
    if (state.result && Boolean(state.result.accepted_common_sample) !== Boolean(accept)) markNotesStale();
    const request = buildRequest(accept);
    const revision = state.revision;
    state.busy = true; updateChrome();
    try {
      const result = await api("/api/review", request);
      if (revision !== state.revision) { showMessage("Inputs changed during this check. Run coverage again to review the current files.", false); return; }
      state.result = result; state.resultRequest = request; state.dirty = false;
      state.diagnosticPage = 1;
      const entities = result.scope.entities || [];
      if (!entities.includes(state.chartEntity)) state.chartEntity = entities[0] || "";
      renderCoverage(); renderReview();
      if (navigate !== false) state.stage = "coverage";
      if (result.comparison_ready && accept) showMessage("The common sample is accepted. Every comparison metric now uses the same " + result.summary.common + (result.schema_version === 2 ? " forecast keys." : " observations."), false);
      else if (!accept) showMessage("Coverage checked. Review the exclusions before accepting the common sample.", false);
    } catch (error) { showMessage(error.message, true); }
    finally {
      state.busy = false; updateChrome();
      if (navigate !== false && state.result && !state.dirty) document.querySelector(".step-nav").scrollIntoView({behavior: "smooth", block: "start"});
    }
  }

  function table(headers, rows, attrs) {
    return element("table", attrs || {}, [
      element("thead", {}, element("tr", {}, headers.map(function (header) {
        return typeof header === "string" ? element("th", {scope: "col"}, header) : element("th", {scope: "col", className: header.numeric ? "numeric" : ""}, header.label);
      }))),
      element("tbody", {}, rows)
    ]);
  }
  function stat(label, value, description, emphasis) {
    return element("div", {className: "stat-card" + (emphasis ? " emphasis" : "")}, [
      element("div", {className: "stat-label"}, label), element("div", {className: "stat-value"}, value),
      element("div", {className: "stat-description"}, description)
    ]);
  }
  function modelNameCell(model) {
    return element("td", {className: "source-cell"}, [model.name, model.role === "baseline" ? element("small", {}, "Baseline") : null]);
  }
  function metricTable(models, key, includeBaselineChange) {
    const headings = ["Forecast", {label: "Records", numeric: true}, {label: "MAE", numeric: true}, {label: "RMSE", numeric: true}, {label: "Bias", numeric: true}];
    if (includeBaselineChange) headings.push({label: "MAE vs baseline", numeric: true}, {label: "RMSE vs baseline", numeric: true});
    return table(headings, models.map(function (model) {
      const m = model[key];
      const cells = [modelNameCell(model), metricCell(m ? m.n : null), metricCell(m ? m.mae : null), metricCell(m ? m.rmse : null), metricCell(m ? m.bias : null)];
      if (includeBaselineChange) ["mae_pct", "rmse_pct"].forEach(function (metric) {
        const value = model.vs_baseline ? model.vs_baseline[metric] : null;
        const reason = model.vs_baseline && model.vs_baseline.reason;
        cells.push(element("td", {className: "numeric " + (Number(value) > 0 ? "improvement-positive" : Number(value) < 0 ? "improvement-negative" : ""), title: reason || (value === null ? "No relative comparison is available." : String(value) + "% improvement")}, value === null || value === undefined ? "—" : (Number(value) > 0 ? "+" : "") + number(value) + "%"));
      });
      return element("tr", {}, cells);
    }));
  }

  function renderCoverage() {
    const result = state.result;
    if (!result) return;
    const summary = result.summary;
    $("coverage-context").textContent = (result.schema_version === 2 ? "Forecast origins " + result.scope.origin_start + " to " + result.scope.origin_end : result.scope.start + " to " + result.scope.end) + " · " + result.scope.frequency + " · " + (result.scope.entities && result.scope.entities.length ? result.scope.entities.length + " explicitly selected entities" : "one series");
    $("coverage-summary").replaceChildren(
      stat("Expected records", summary.expected, result.schema_version === 2 ? "Origin × horizon × entity scope" : "Full period and entity scope", false),
      stat("Common sample", summary.common, "Valid actuals and all forecasts", true),
      stat("Excluded records", summary.excluded, "Missing or invalid in at least one file", false),
      stat("Records outside scope", summary.extra_rows, "Retained but excluded from comparison", false)
    );
    const errors = result.contract_errors || [];
    $("contract-errors").replaceChildren();
    if (errors.length) {
      $("contract-errors").appendChild(element("div", {className: "contract-errors"}, [
        element("h3", {}, "Check each file’s value definitions first"),
        element("p", {}, "The files have conflicting target, unit, or timing definitions. Numerical comparison is blocked; source rows and missing records remain available."),
        element("div", {className: "table-wrap"}, table(["Source", "Definition", "Review requirements", "File declaration"], errors.map(function (error) {
          return element("tr", {}, [element("td", {}, sourceLabel(error.source_id)), element("td", {}, error.field), element("td", {}, textValue(error.expected)), element("td", {}, textValue(error.received))]);
        })))
      ]));
    }
    $("coverage-table").replaceChildren(table(["Forecast", {label: "Valid / expected", numeric: true}, {label: "Missing", numeric: true}, {label: "Duplicate", numeric: true}, {label: "Invalid", numeric: true}, {label: "Outside scope", numeric: true}],
      (result.models || []).map(function (model) {
        const c = model.coverage || {};
        const coverage = element("td", {className: "numeric"}, [
          String(c.valid || 0) + " / " + String(c.expected || summary.expected),
          element("progress", {className: "coverage-progress", max: Math.max(1, Number(c.expected || summary.expected)), value: Number(c.valid || 0), "aria-label": model.name + " valid expected observations"})
        ]);
        return element("tr", {}, [modelNameCell(model), coverage, metricCell(c.missing || 0), metricCell(c.duplicate || 0), metricCell(c.invalid || 0), metricCell(c.outside_scope || 0)]);
      })));
    const canAccept = !state.dirty && !errors.length && summary.common > 0 && !state.busy;
    $("acceptance").classList.toggle("blocked", Boolean(errors.length || !summary.common));
    const acceptanceMessage = errors.length ? "File definitions conflict. Return to Prepare files, correct the definitions, and check again."
      : !summary.common ? "No common sample is available. Check missing records and the full scope, then rerun."
      : "Expected: " + summary.expected + " records, of which " + summary.common + " are comparable; a further " + summary.excluded + " will be excluded from the comparison metrics for every forecast and baseline.";
    $("acceptance").replaceChildren(
      element("div", {className: "acceptance-title"}, [element("span", {className: "acceptance-number", "aria-hidden": "true"}, result.comparison_ready ? "✓" : "→"), result.comparison_ready && !state.dirty ? "Accepted common sample" : "Accept common sample"]),
      element("p", {}, acceptanceMessage),
      element("label", {className: "check-label"}, [
        element("input", {id: "accept-common-sample", type: "checkbox", checked: !state.dirty && result.accepted_common_sample, disabled: !canAccept,
          onchange: function (event) { runReview(event.target.checked, false); }}),
        element("span", {}, "I have reviewed the gaps and accept comparison using these " + summary.common + " common records, with the exclusions listed above.")
      ])
    );
    $("available-panel").classList.toggle("hidden", Boolean(errors.length || state.dirty));
    $("available-metrics").replaceChildren(metricTable(result.models || [], "available_metrics", false));
    $("coverage-next-label").textContent = result.comparison_ready && !state.dirty ? "Common sample accepted. Results are ready to view." : "Accept the common sample before comparing forecast errors.";
    $("coverage-next-help").textContent = "Lower error is only one piece of evidence. Consider missing coverage and the intended use.";
    renderDiagnostics();
    updateChrome();
  }

  function formatReasons(reasons) {
    return (reasons || []).map(function (reason) {
      return element("div", {}, sourceLabel(reason.source_id) + ": " + (reason.detail || reason.code));
    });
  }
  function renderDiagnostics() {
    const result = state.result;
    if (!result) return;
    const host = $("diagnostics-coverage");
    const tabs = [["expected", "Expected records"], ["input", "All source rows"], ["issues", "Issue details"]];
    const tabBar = element("div", {className: "tab-pills", role: "group", "aria-label": "Diagnostics view"}, tabs.map(function (item) {
      return button(item[1], "tab-pill" + (state.diagnosticTab === item[0] ? " active" : ""), function () {
        state.diagnosticTab = item[0]; state.diagnosticPage = 1; renderDiagnostics();
        $("diagnostic-view-" + item[0]).focus();
      }, {id: "diagnostic-view-" + item[0], "aria-pressed": state.diagnosticTab === item[0]});
    }));
    const search = element("input", {className: "search-input", type: "search", placeholder: "Search rows, IDs or issues…", value: state.diagnosticSearch, "aria-label": "Search diagnostics",
      oninput: function (event) { state.diagnosticSearch = event.target.value; state.diagnosticPage = 1; renderDiagnosticRows(); }});
    const filter = select([{value: "all", label: "All expected records"}, {value: "excluded", label: "Excluded records only"}, {value: "included", label: "Common sample only"}], state.diagnosticFilter,
      function (event) { state.diagnosticFilter = event.target.value; state.diagnosticPage = 1; renderDiagnosticRows(); },
      {"aria-label": "Filter expected rows", disabled: state.diagnosticTab !== "expected"});
    host.replaceChildren(element("div", {className: "panel diagnostics-panel"}, [
      element("div", {className: "diagnostic-toolbar"}, [tabBar, element("div", {className: "diagnostic-search"}, [search, filter])]),
      element("div", {className: "table-wrap", id: "diagnostic-data"}),
      element("div", {className: "pagination", id: "diagnostic-pagination"})
    ]));
    renderDiagnosticRows();
  }
  function renderDiagnosticRows() {
    const result = state.result;
    if (!result || !$("diagnostic-data")) return;
    const query = state.diagnosticSearch.toLowerCase();
    let rows = state.diagnosticTab === "expected" ? result.rows || [] : state.diagnosticTab === "input" ? result.input_rows || [] : result.issues || [];
    rows = rows.filter(function (row) {
      if (state.diagnosticTab === "expected" && state.diagnosticFilter === "excluded" && row.included) return false;
      if (state.diagnosticTab === "expected" && state.diagnosticFilter === "included" && !row.included) return false;
      return !query || JSON.stringify(row).toLowerCase().includes(query);
    });
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    state.diagnosticPage = Math.min(pages, Math.max(1, state.diagnosticPage));
    const start = (state.diagnosticPage - 1) * PAGE_SIZE;
    const pageRows = rows.slice(start, start + PAGE_SIZE);
    let headers, body;
    if (state.diagnosticTab === "expected") {
      headers = ["Period / entity", "Sample", {label: "Actual", numeric: true}]
        .concat((result.models || []).map(function (model) { return {label: model.name, numeric: true}; })).concat(["Exclusion reasons / source rows"]);
      body = pageRows.map(function (row) {
        const cells = [
          element("td", {className: "row-period"}, [(result.schema_version === 2 ? row.origin + " → " + row.period + " · h=" + row.horizon : row.period), row.entity ? element("div", {className: "row-entity"}, row.entity) : null]),
          element("td", {}, element("span", {className: "tag " + (row.included ? "tag-success" : "tag-warning")}, row.included ? "Common sample" : "Excluded")),
          metricCell(row.actual)
        ];
        (result.models || []).forEach(function (model) {
          const prediction = row.predictions ? row.predictions[model.id] : null;
          const residual = row.residuals ? row.residuals[model.id] : null;
          cells.push(element("td", {className: "numeric", title: textValue(prediction)}, [
            number(prediction),
            result.comparison_ready && !state.dirty && row.included && residual !== null && residual !== undefined ? element("small", {className: "cell-residual"}, "error " + number(residual)) : null
          ]));
        });
        const references = Object.keys(row.source_rows || {}).map(function (id) { return sourceLabel(id) + ": " + row.source_rows[id].join(", "); }).join(" · ");
        cells.push(element("td", {className: "reasons"}, [formatReasons(row.reasons), references ? element("span", {className: "row-ref"}, references) : null]));
        return element("tr", {}, cells);
      });
    } else if (state.diagnosticTab === "input") {
      headers = ["Source", "Original row", "Original date", "Original entity", "Original value", "Normalized period", "Status"].concat(result.schema_version === 2 ? ["Original origin", "Origin", "Original horizon", "Horizon"] : []);
      body = pageRows.map(function (row) {
        return element("tr", {}, [sourceLabel(row.source_id), row.row, row.raw_date, row.raw_entity, row.raw_value, row.period, row.status].concat(result.schema_version === 2 ? [row.raw_origin,row.origin,row.raw_horizon,row.horizon] : []).map(function (value) {
          return element("td", {}, textValue(value));
        }));
      });
    } else {
      headers = ["Source", "Original row", "Period / entity", "Issue", "Explanation"];
      body = pageRows.map(function (row) { return element("tr", {}, [sourceLabel(row.source_id), row.row, row.period ? row.period + (row.entity ? " · " + row.entity : "") : null, row.code, (result.schema_version === 2 ? "Origin: " + textValue(row.origin) + "; horizon: " + textValue(row.horizon) + ". " : "") + row.detail].map(function (value) { return element("td", {}, textValue(value)); })); });
    }
    $("diagnostic-data").replaceChildren(rows.length ? table(headers, body, {className: "diagnostic-table"}) : element("div", {className: "empty-state"}, "No rows match this view."));
    $("diagnostic-pagination").replaceChildren(
      element("span", {}, rows.length ? (start + 1) + "–" + Math.min(start + PAGE_SIZE, rows.length) + " of " + rows.length + " rows" : "0 rows"),
      element("div", {className: "pagination-controls"}, [
        button("←", "", function () { state.diagnosticPage -= 1; renderDiagnosticRows(); }, {disabled: state.diagnosticPage === 1, "aria-label": "Previous diagnostics page"}),
        element("span", {}, state.diagnosticPage + " / " + pages),
        button("→", "", function () { state.diagnosticPage += 1; renderDiagnosticRows(); }, {disabled: state.diagnosticPage >= pages, "aria-label": "Next diagnostics page"})
      ])
    );
  }

  function renderReview() {
    const result = state.result;
    if (!result) return;
    const ready = result.comparison_ready && !state.dirty && !(result.contract_errors || []).length;
    $("review-context").textContent = result.contract.target + " · " + result.contract.unit + " · " + (ready ? result.summary.common + " accepted common records" : "Common-sample comparison is not yet available") + ". Dates refer to the forecast target period. Declaring a horizon does not shift dates.";
    const content = $("results-content");
    content.replaceChildren();
    if (!ready) {
      content.appendChild(element("div", {className: "pending-review"}, [
        element("h3", {}, "Start with coverage and a common sample"),
        element("p", {}, "No common-sample metrics or comparison plot are shown until the definitions agree and you explicitly accept a nonempty sample."),
        button("Review coverage", "text-button", function () { goStage("coverage"); })
      ]));
    } else {
      if (result.schema_version === 2) {
        content.appendChild(element("section", {className:"panel",id:"horizon-results"}, [
          element("h3", {}, "Compare each forecast horizon"),
          element("p", {}, result.weighting + " " + result.summary.unique_actual_keys + " unique target/entity actual keys support " + result.summary.expected + " expected forecasts. Origin labels do not prove training independence or availability."),
          ...result.horizon_results.map(function(h) {
            const models = result.models.map(m => Object.assign({},m,{horizon_metric:(h.metrics || {})[m.id]}));
            return element("div", {className:"table-wrap"}, [element("h4",{},"Horizon " + h.horizon + " · " + h.common + " common / " + h.expected + " expected; " + h.excluded + " excluded"),metricTable(models,"horizon_metric",false)]);
          })
        ]));
      }
      const comparisonRows = (result.models || []).map(function (model) {
        const available = model.available_metrics || {}, common = model.metrics || {};
        return element('tr', {}, [model.name, String(available.n ?? '—'), number(available.mae), String(common.n ?? '—'), number(common.mae)].map(value=>element('td',{},value)));
      });
      content.appendChild(element('section', {className:'panel', id:'sample-comparison'}, [
        element('h3', {}, 'Different samples can reverse the ranking'),
        element('p', {}, 'The left-hand metrics use different records and are diagnostic only; they cannot rank models. The right-hand metrics use the accepted common sample of ' + result.summary.common + ' records; full scope: ' + result.summary.expected + '; excluded: ' + result.summary.excluded + ' records. Conclusions do not cover excluded records.'),
        element('div', {className:'table-wrap'}, table(['Forecast','Own sample size','Own-sample MAE (not comparable)','Common sample size','Common MAE'], comparisonRows)),
        element('p', {className:'muted'}, 'Lower MAE means lower average absolute error on this common sample. It does not establish better future performance or leakage-free training. Equal sample sizes do not mean identical records; use the explicitly accepted common keys.')
      ]));
      content.appendChild(element("div", {className: "panel"}, [
        element("div", {className: "metric-intro"}, [
          element("div", {}, [element("h3", {}, "4 Compare errors on the same sample"), element("p", {}, "All forecasts below use the accepted common sample of " + result.summary.common + " records, with values measured in " + result.contract.unit + ".")]),
          element("span", {className: "tag tag-success"}, "Accepted common sample")
        ]),
        element("div", {className: "table-wrap"}, metricTable(result.models || [], "metrics", Boolean(state.baseline))),
        element("div", {className: "metric-definitions"}, [
          element("div", {}, [element("strong", {}, "MAE"), "Mean absolute error; lower values indicate smaller errors on this sample."]),
          element("div", {}, [element("strong", {}, "RMSE"), "More sensitive to large errors; not the regression residual standard error."]),
          element("div", {}, [element("strong", {}, "Bias"), "Mean forecast minus actual; positive values indicate average overprediction."])
        ]),
        state.baseline ? element("p", {className: "baseline-note"}, "Relative to baseline: positive percentages indicate lower error; negative percentages indicate deterioration. A zero denominator or undefined comparison is shown as —.") : null
      ]));
      content.appendChild(renderChartPanel());
      if ((result.segments || []).length) {
        content.appendChild(element("div", {className: "panel"}, [
          element("div", {className: "panel-heading"}, [element("div", {}, [element("h3", {}, "Is performance consistent across periods?"), element("p", {className: "muted compact"}, "Each segment uses only accepted common-sample records within that period.")])]),
          element("div", {className: "segment-results"}, result.segments.map(function (segment) {
            const modelRows = (result.models || []).map(function (model) { return Object.assign({}, model, {segment_metric: segment.metrics ? segment.metrics[model.id] : null}); });
            return element("div", {className: "segment-result"}, [
              element("h4", {}, segment.name), element("p", {}, segment.start + " to " + segment.end + " · " + segment.n + " common observations"),
              segment.n ? element("div", {className: "table-wrap"}, metricTable(modelRows, "segment_metric", false)) : element("p", {}, "No accepted observations in this segment; no metrics are reported.")
            ]);
          }))
        ]));
      }
    }
    renderNotes(ready);
    renderMetadata();
    $("export-help").textContent = ready ? "Extract the ZIP and open report.html. It includes common-sample results, source references, row diagnostics, and your review notes." : "You can download a coverage report. It does not include metrics for an accepted common sample.";
    updateChrome();
  }

  function svgElement(tag, attributes, children) {
    const item = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attributes || {}).forEach(function (key) { item.setAttribute(key, String(attributes[key])); });
    append(item, children);
    return item;
  }
  function renderChartPanel() {
    const result = state.result;
    const modes = [["trend", "Forecast trends"], ["error", "Forecast error"]];
    const controls = element("div", {className: "chart-controls"}, [
      element("div", {className: "tab-pills", role: "group", "aria-label": "Chart view"}, modes.map(function (mode) {
        return button(mode[1], "tab-pill" + (state.chartMode === mode[0] ? " active" : ""), function () { state.chartMode = mode[0]; replaceChart(); }, {"aria-pressed": state.chartMode === mode[0]});
      }))
    ]);
    const entities = result.scope.entities && result.scope.entities.length ? result.scope.entities : [""];
    if (entities.length > 1) controls.appendChild(select(entities.map(function (id) { return {value: id, label: id}; }), state.chartEntity, function (event) { state.chartEntity = event.target.value; replaceChart(); }, {"aria-label": "Entity shown in chart"}));
    const panel = element("section", {className: "panel chart-panel", id: "chart-panel", "aria-label": "Accepted common-sample chart"}, [
      element("div", {className: "panel-heading"}, [
        element("div", {}, [element("h3", {}, state.chartMode === "trend" ? "View forecasts and actuals by period" : "View errors over time"), element("p", {className: "muted compact"}, state.chartMode === "trend" ? "Every series uses the same accepted records." : "Error = forecast − actual; zero indicates an exact match.")]), controls
      ])
    ]);
    const entity = entities.includes(state.chartEntity) ? state.chartEntity : entities[0];
    if (result.schema_version === 2) {
      if (!result.contract.horizons.includes(state.chartHorizon)) state.chartHorizon = result.contract.horizons[0];
      controls.appendChild(select(result.contract.horizons.map(h => ({value:String(h),label:"Horizon " + h})),String(state.chartHorizon),function(event) {state.chartHorizon=Number(event.target.value);replaceChart();},{"aria-label":"Forecast horizon shown in chart"}));
    }
    const expectedRows = (result.rows || []).filter(function (row) { return row.entity === entity && (result.schema_version !== 2 || row.horizon === state.chartHorizon); });
    const commonRows = expectedRows.filter(function (row) { return row.included; });
    if (!commonRows.length) { panel.appendChild(element("div", {className: "empty-state"}, "No accepted common observations for this entity.")); return panel; }
    const models = result.models || [];
    const series = state.chartMode === "trend" ? [{id: "actual", name: "Actual", color: "#203430"}] : [];
    models.forEach(function (model, index) { series.push({id: model.id, name: model.name + (model.role === "baseline" ? " · baseline" : ""), color: COLORS[index % COLORS.length], baseline: model.role === "baseline"}); });
    const values = [];
    function valueFor(row, id) {
      return id === "actual" ? Number(row.actual) : Number(state.chartMode === "trend" ? row.predictions[id] : row.residuals[id]);
    }
    commonRows.forEach(function (row) { series.forEach(function (item) { const value = valueFor(row, item.id); if (Number.isFinite(value)) values.push(value); }); });
    if (state.chartMode === "error") values.push(0);
    let low = Math.min.apply(null, values), high = Math.max.apply(null, values);
    if (!values.length || !Number.isFinite(low) || !Number.isFinite(high)) { panel.appendChild(element("p", {className: "muted"}, "These values cannot be plotted at this scale. Exact values remain in the tables and exported review.")); return panel; }
    const padding = high === low ? Math.abs(high) * 0.1 || 1 : (high - low) * 0.12;
    low -= padding; high += padding;
    const W = Math.min(1060, Math.max(320, window.innerWidth - (window.innerWidth <= 760 ? 84 : 116)));
    const compactChart = W < 600;
    const H = compactChart ? 300 : 330, L = compactChart ? 78 : 86, R = compactChart ? 15 : 26, T = 20, B = 44;
    const periodIndex = new Map(expectedRows.map(function (row, index) { return [row.period, index]; }));
    function x(period) { return L + (periodIndex.get(period) || 0) / Math.max(1, expectedRows.length - 1) * (W - L - R); }
    function y(value) { return T + (high - value) / (high - low) * (H - T - B); }
    const svg = svgElement("svg", {class: "chart-svg", viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": (state.chartMode === "trend" ? "Actual and forecast trends" : "Forecast errors") + " on " + commonRows.length + " common observations" + (entity ? " for entity " + entity : "")}, []);
    for (let tick = 0; tick <= 4; tick += 1) {
      const value = low + (high - low) * tick / 4;
      const yy = y(value);
      svg.appendChild(svgElement("line", {x1: L, y1: yy, x2: W - R, y2: yy, stroke: "#e6ecdf", "stroke-width": 1}, []));
      svg.appendChild(svgElement("text", {x: L - 13, y: yy + 4, fill: "#8b9780", "font-size": 11, "font-family": "system-ui,sans-serif", "text-anchor": "end"}, number(value)));
    }
    if (state.chartMode === "error" && low <= 0 && high >= 0) svg.appendChild(svgElement("line", {x1: L, y1: y(0), x2: W - R, y2: y(0), stroke: "#aab5a0", "stroke-dasharray": "4 4"}, []));
    const labels = new Set(compactChart
      ? [0, Math.floor((expectedRows.length - 1) / 2), expectedRows.length - 1]
      : [0, Math.floor((expectedRows.length - 1) / 4), Math.floor((expectedRows.length - 1) / 2), Math.floor((expectedRows.length - 1) * 3 / 4), expectedRows.length - 1]);
    labels.forEach(function (index) {
      const row = expectedRows[index];
      if (row) svg.appendChild(svgElement("text", {x: x(row.period), y: H - 15, fill: "#8b9780", "font-size": 11, "font-family": "system-ui,sans-serif", "text-anchor": index === 0 ? "start" : index === expectedRows.length - 1 ? "end" : "middle"}, row.period));
    });
    series.forEach(function (item) {
      const points = commonRows.map(function (row) { return {row: row, value: valueFor(row, item.id)}; }).filter(function (point) { return Number.isFinite(point.value); });
      const path = points.map(function (point, index) {
        const consecutive = index > 0 && periodIndex.get(point.row.period) === periodIndex.get(points[index - 1].row.period) + 1;
        return (consecutive ? "L" : "M") + x(point.row.period).toFixed(3) + "," + y(point.value).toFixed(3);
      }).join(" ");
      svg.appendChild(svgElement("path", {d: path, fill: "none", stroke: item.color, "stroke-width": item.id === "actual" ? 2.8 : 2, "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": item.baseline ? "6 5" : "none"}, []));
      const stride = Math.max(1, Math.ceil(points.length / 55));
      points.forEach(function (point, index) {
        const atSegmentStart = index === 0 || periodIndex.get(point.row.period) !== periodIndex.get(points[index - 1].row.period) + 1;
        const atSegmentEnd = index === points.length - 1 || periodIndex.get(points[index + 1].row.period) !== periodIndex.get(point.row.period) + 1;
        if (index % stride !== 0 && !atSegmentStart && !atSegmentEnd) return;
        svg.appendChild(svgElement("circle", {cx: x(point.row.period), cy: y(point.value), r: points.length < 25 ? 3.4 : 2, fill: "#fff", stroke: item.color, "stroke-width": 1.7}, svgElement("title", {}, item.name + " · " + point.row.period + ": " + number(point.value))));
      });
    });
    panel.appendChild(element("div", {className: "chart-legend"}, series.map(function (item) {
      return element("span", {className: "legend-item"}, [
        svgElement("svg", {width: 17, height: 6, viewBox: "0 0 17 6", "aria-hidden": "true"}, svgElement("rect", {x: 0, y: 1.5, width: 17, height: 3, rx: 1.5, fill: item.color}, [])),
        item.name
      ]);
    })));
    panel.appendChild(svg);
    panel.appendChild(element("p", {className: "chart-note"}, "Showing " + commonRows.length + (result.schema_version === 2 ? " accepted forecast keys at horizon " + state.chartHorizon : " accepted observations") + (entity ? " for " + entity : "") + ". Each series uses the same dates. Lines break at periods excluded from the common sample. Exact values remain in the row diagnostics."));
    return panel;
  }
  function replaceChart() { const existing = $("chart-panel"); if (existing && state.result && state.result.comparison_ready && !state.dirty) existing.replaceWith(renderChartPanel()); }

  function renderNotes(ready) {
    const host = $("notes");
    host.replaceChildren();
    if (!ready) { host.appendChild(element("p", {className: "notes-disabled-message"}, "Accept the common sample before recording a model assessment. You can still export the coverage review.")); return; }
    const fingerprint = state.result.fingerprint;
    (state.result.models || []).filter(function (model) { return model.role !== "baseline"; }).forEach(function (model) {
      const stored = state.notes[model.id];
      const note = stored || {model_id: model.id, decision: "", text: "", fingerprint: fingerprint};
      const stale = Boolean(stored && (stored.stale || stored.fingerprint !== fingerprint) && (stored.text || stored.decision));
      const card = element("div", {className: "note-card" + (stale ? " stale" : "")}, [element("h3", {}, model.name)]);
      if (stale) {
        card.appendChild(element("div", {className: "note-stale-message"}, "This draft belongs to an earlier review. Recheck it against the current evidence before using it again."));
        card.appendChild(element("div", {className: "note-stale-actions"}, [
          button("Rechecked · use for this run", "text-button", function () { state.notes[model.id] = Object.assign({}, note, {fingerprint: fingerprint, stale: false}); clearMessages(); renderNotes(true); }),
          button("Discard this draft", "text-button danger-button", function () { delete state.notes[model.id]; clearMessages(); renderNotes(true); })
        ]));
      }
      const decision = select([{value: "", label: "Select review judgement"}, {value: "retain", label: "Keep under consideration"}, {value: "needs_evidence", label: "More evidence needed"}, {value: "do_not_adopt", label: "Not recommended for this use"}], note.decision, function (event) {
        state.notes[model.id] = Object.assign({}, note, state.notes[model.id] || {}, {decision: event.target.value, fingerprint: fingerprint, stale: false});
      }, {id: "note-decision-" + model.id, disabled: stale});
      const comments = element("textarea", {id: "note-text-" + model.id, rows: 4, value: note.text, disabled: stale, maxlength: "4000", placeholder: "What evidence supports your judgement? What is missing? What limits its scope?",
        oninput: function (event) { state.notes[model.id] = Object.assign({}, note, state.notes[model.id] || {}, {text: event.target.value, fingerprint: fingerprint, stale: false}); }});
      card.appendChild(field("Reviewer action", decision));
      card.appendChild(field("Evidence and reasoning", comments, "Up to 4,000 characters. Record the reasoning for this review."));
      host.appendChild(card);
    });
  }

  function renderMetadata() {
    const result = state.result;
    const target = $("source-metadata");
    target.replaceChildren();
    const sources = Array.isArray(result.sources) ? result.sources : Object.values(result.sources || {});
    sources.forEach(function (source) {
      const c = source.contract || {};
      const mapping = source.mapping || {};
      target.appendChild(element("div", {className: "source-metadata"}, [
        element("h4", {}, source.name || sourceLabel(source.id)),
        element("p", {}, source.file_name + " · " + (source.sheet || "CSV / single sheet") + " · header row " + source.header_row + " · " + source.rows + " nonempty rows"),
        element("p", {}, "Mapped columns: date = " + textValue(mapping.date) + "; value = " + textValue(mapping.value) + "; entity = " + (mapping.entity || "single series") + (state.schemaVersion === 2 && source.role !== "actual" ? "; origin = " + textValue(mapping.origin) + "; horizon = " + (mapping.horizon || "derived") : "")),
        element("p", {}, "Declared: " + c.target + " · " + c.unit + " · horizon " + (c.horizons || c.horizon || "not applicable to actuals") + " · " + c.frequency + " · transformation " + c.transformation),
        source.source_note ? element("p", {}, "Source note: " + source.source_note) : null,
        element("p", {}, [element("strong", {}, "Source SHA-256: "), element("code", {}, source.sha256)])
      ]));
    });
    const warnings = (result.warnings || []).slice();
    if (!warnings.length) warnings.push("Prediction files do not establish how models were trained or whether evaluation observations were independent of training.");
    target.appendChild(element("ul", {className: "warnings-list"}, warnings.map(function (warning) { return element("li", {}, typeof warning === "string" ? warning : JSON.stringify(warning)); })));
    target.appendChild(element("p", {className: "fingerprint"}, "Current review fingerprint: " + result.fingerprint));
  }

  async function exportReview() {
    if (!state.result || state.dirty || !state.resultRequest || state.busy) return;
    clearMessages();
    const fingerprint = state.result.fingerprint;
    const modelIds = (state.result.models || []).map(function (model) { return model.id; });
    const notes = Object.values(state.notes).filter(function (note) { return modelIds.includes(note.model_id) && (note.text.trim() || note.decision); });
    if (notes.some(function (note) { return note.stale || note.fingerprint !== fingerprint; })) { showMessage("Some reviewer notes belong to an earlier run. Recheck and explicitly reuse them, or discard the old drafts before exporting.", true); return; }
    if (notes.some(function (note) { return !note.decision || !note.text.trim(); })) { showMessage("For each note you keep, choose a reviewer action and add your reasoning. Empty notes can be omitted.", true); return; }
    const request = Object.assign({}, state.resultRequest, {title: state.title.trim() || "Forecast review"});
    const revision = state.revision;
    state.busy = true; updateChrome(); $("export-review").textContent = "Preparing review report…";
    try {
      const exportNotes = notes.map(function (note) { return {model_id: note.model_id, decision: note.decision, text: note.text, fingerprint: note.fingerprint}; });
      const payload = {request: request, fingerprint: fingerprint, notes: exportNotes};
      let blob;
      const browser = window.WorkbenchUI.transport();
      if (browser) blob = await browser.download("/api/export", payload);
      else {
        const response = await fetch("/api/export", {method: "POST", credentials: "same-origin", headers: tokenHeaders(), body: JSON.stringify(payload)});
        if (!response.ok) { const data = await response.json(); throw new Error(data.error || "Unable to export review results."); }
        blob = await response.blob();
      }
      if (revision !== state.revision) throw new Error("Inputs changed while the download was being prepared. Check the updated coverage before exporting.");
      const url = URL.createObjectURL(blob);
      const filename = (state.title.trim() || "forecast-review").replace(/[^a-zA-Z0-9_-]+/g, "-").slice(0, 70) || "forecast-review";
      if (exportURL) URL.revokeObjectURL(exportURL);
      document.getElementById("save-review-link")?.remove();
      exportURL = url;
      const link = element("a", {href: url, download: filename + ".zip", id: "save-review-link", className: "button"}, "Save review ZIP");
      document.querySelector(".export-bar").appendChild(link); link.click();
      showMessage("Review package created. If the download did not start, select Save review ZIP. Extract it and open report.html.", false);
    } catch (error) { showMessage(error.message || "The local application could not prepare the download.", true); }
    finally { state.busy = false; $("export-review").textContent = "Download full review package ↓"; updateChrome(); }
  }

  function renderSegments() {
    $("segments").replaceChildren.apply($("segments"), state.segments.map(function (segment, index) {
      return element("div", {className: "segment-input"}, [
        field("Segment name", element("input", {value: segment.name, placeholder: "e.g. Later period", maxlength: "80", oninput: function (event) { segment.name = event.target.value; invalidate(); }})),
        field("Start", element("input", {value: segment.start, placeholder: state.scope.start || "2024-07", oninput: function (event) { segment.start = event.target.value; invalidate(); }})),
        field("End", element("input", {value: segment.end, placeholder: state.scope.end || "2024-12", oninput: function (event) { segment.end = event.target.value; invalidate(); }})),
        button("×", "icon-button", function () { state.segments.splice(index, 1); invalidate(); renderSegments(); }, {"aria-label": "Remove period segment " + (index + 1)})
      ]);
    }));
  }
  function syncForm() {
    $("review-title").value = state.title;
    ["target", "unit", "horizon", "transformation"].forEach(function (key) { $(key).value = state.contract[key]; });
    $("review-mode").value = String(state.schemaVersion);
    $("horizons").value = state.horizonsText;
    $("single-horizon-field").hidden = state.schemaVersion === 2;
    $("multi-horizon-field").hidden = state.schemaVersion !== 2;
    $("scope-start-label").textContent = state.schemaVersion === 2 ? "First forecast origin" : "Start period";
    $("scope-end-label").textContent = state.schemaVersion === 2 ? "Last forecast origin" : "End period";
    $("frequency").value = state.scope.frequency;
    $("scope-start").value = state.scope.start; $("scope-end").value = state.scope.end;
    $("entities").value = state.scope.entities.join("\n");
    updatePeriodHelp(); renderSources(); renderSegments();
  }
  function updatePeriodHelp() {
    const examples = {monthly: ["2024-01", "2024-12", "Use YYYY-MM; includes the start and end months."], quarterly: ["2024-Q1", "2024-Q4", "Use YYYY-Q1 through YYYY-Q4; includes the start and end quarters."], daily: ["2024-01-01", "2024-12-31", "Use YYYY-MM-DD; includes every calendar day between the endpoints."]};
    const example = examples[state.scope.frequency];
    $("scope-start").placeholder = example[0]; $("scope-end").placeholder = example[1]; $("period-help").textContent = example[2];
  }

  async function applyForecastRequest(request) {
      if (!request || !request.actual || !request.scope || !request.contract || !Array.isArray(request.candidates) || request.candidates.length < 1 || request.candidates.length > 5) {
        throw new Error("The transferred forecast review is incomplete. Return to Training experiments and transfer it again.");
      }
      if (![1,2].includes(request.schema_version)) throw new Error("Choose review schema version 1 or 2.");
      state.schemaVersion = request.schema_version;
      state.horizonsText = (request.contract.horizons || [1,2]).join(", ");
      state.title = request.title || "Invented forecast example";
      state.scope = Object.assign({entities: []}, request.scope);
      if (state.schemaVersion === 2) { state.scope.start = request.scope.origin_start; state.scope.end = request.scope.origin_end; }
      state.contract = Object.assign({}, request.contract);
      function restore(entry, role, defaultId, defaultName) {
        const source = makeSource(entry.id || defaultId, entry.name || defaultName, role);
        ["file", "sheet", "header_row", "mapping", "contract", "source_note"].forEach(function (key) { if (entry[key] !== undefined) source[key] = entry[key]; });
        return source;
      }
      state.actual = restore(request.actual, "actual", "actual", "Observed actuals");
      state.candidates = request.candidates.map(function (entry, index) { return restore(entry, "candidate", "model-" + index, "Candidate " + (index + 1)); });
      state.baseline = request.baseline ? restore(request.baseline, "baseline", "baseline", "Baseline") : null;
      state.segments = (request.segments || []).map(function (segment) { return Object.assign({}, segment); });
      state.chartEntity = state.scope.entities[0] || "";
      invalidate(); state.stage = "inputs"; syncForm();
      // Keep imports within the local server's bounded request capacity.
      for (const source of allSources()) await inspectSource(source, true);
      state.busy = false; updateChrome();
      await runReview(false, true);
  }

  async function loadExample(rolling) {
    if (state.busy) return;
    clearMessages(); state.busy = true; updateChrome();
    try {
      const request = await api(rolling === true ? "/api/origin-example" : "/api/example");
      await applyForecastRequest(request);
      if (state.result && !state.dirty) showMessage(rolling === true ? "Invented rolling-origin example loaded. Four forecasts reference three actual target periods. Accept the common sample to compare each horizon." : "Synthetic example loaded. Forecasts have different missing months. Review the gaps before accepting the common sample. Return to Prepare files to use your own data.", false);
    } catch (error) { showMessage(error.message, true); }
    finally { state.busy = false; updateChrome(); }
  }

  async function importTransferredRequest() {
    let encoded;
    try {
      encoded = sessionStorage.getItem("frw.import.request");
      if (encoded) sessionStorage.removeItem("frw.import.request");
    } catch (_error) { return; }
    if (!encoded) return;
    state.busy = true; updateChrome();
    try {
      const request = JSON.parse(encoded);
      request.accept_common_sample = false;
      await applyForecastRequest(request);
      if (state.result && !state.dirty) showMessage("Generated holdout forecasts imported. Review coverage and explicitly accept the common sample before comparing metrics.", false);
    } catch (error) { showMessage(error.message || "The transferred review could not be opened.", true); }
    finally { state.busy = false; updateChrome(); }
  }

  function bindEvents() {
    document.querySelectorAll("[data-stage]").forEach(function (control) { control.addEventListener("click", function () { goStage(control.dataset.stage); }); });
    document.querySelectorAll("[data-go-inputs]").forEach(function (control) { control.addEventListener("click", function () { goStage("inputs"); }); });
    $("review-form").addEventListener("submit", function (event) { event.preventDefault(); if (inputFlow.current() === "files") inputFlow.next(); else runReview(false, true); });
    $("review-title").addEventListener("input", function (event) { state.title = event.target.value; });
    ["target", "unit", "transformation"].forEach(function (key) { $(key).addEventListener("input", function (event) { state.contract[key] = event.target.value; invalidate(); }); });
    $("review-mode").addEventListener("change", function(event) {
      state.schemaVersion = Number(event.target.value);
      if (state.schemaVersion === 1 && !Number.isInteger(state.contract.horizon)) state.contract.horizon = 1;
      allSources().forEach(function(source) {
        if (state.schemaVersion === 1) { delete source.mapping.origin; delete source.mapping.horizon; }
        else if (source.role !== "actual") {
          source.mapping.origin = uniqueHeader(source.headers,/^(origin|cutoff|forecast_origin|origin_date)$/i) || null;
          source.mapping.horizon = uniqueHeader(source.headers,/^(horizon|lead|forecast_horizon)$/i) || null;
        }
      });
      invalidate(); syncForm(); showMessage("Comparison mode changed. Check the origin fields and confirm each file's definitions before comparing.",false);
    });
    $("horizons").addEventListener("input",function(event) {state.horizonsText=event.target.value;invalidate();});
    $("horizon").addEventListener("input", function (event) { state.contract.horizon = Number(event.target.value); invalidate(); });
    $("frequency").addEventListener("change", function (event) { state.scope.frequency = event.target.value; updatePeriodHelp(); invalidate(); });
    [["scope-start", "start"], ["scope-end", "end"]].forEach(function (item) { $(item[0]).addEventListener("input", function (event) { state.scope[item[1]] = event.target.value; invalidate(); }); });
    $("entities").addEventListener("input", function (event) { state.scope.entities = event.target.value.split(/\r?\n/).filter(function (line) { return line.trim() !== ""; }); invalidate(); });
    $("copy-definition").addEventListener("click", function () { allSources().forEach(function (source) { source.contract = sharedContract(source.role); }); invalidate(); renderSources(); showMessage("Applied to each file following your confirmation. You can still edit individual declarations below.", false); });
    $("add-candidate").addEventListener("click", function () {
      if (state.candidates.length >= 5) return;
      let id;
      do { state.sourceCounter += 1; id = "candidate-" + state.sourceCounter; } while (allSources().some(function (source) { return source.id === id; }));
      state.candidates.push(makeSource(id, "Candidate " + (state.candidates.length + 1), "candidate"));
      invalidate(); renderSources();
    });
    $("add-baseline").addEventListener("click", function () { state.baseline = makeSource("baseline", "Baseline", "baseline"); invalidate(); renderSources(); });
    $("add-segment").addEventListener("click", function () { state.segments.push({name: "", start: "", end: ""}); invalidate(); renderSegments(); });
    $("example-button").addEventListener("click", () => loadExample(false));
    $("origin-example-button").addEventListener("click", () => loadExample(true));
    $("go-review").addEventListener("click", function () { goStage("review"); });
    $("back-coverage").addEventListener("click", function () { goStage("coverage"); });
    $("export-review").addEventListener("click", exportReview);
    let resizeTimer;
    window.addEventListener("resize", function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(replaceChart, 120);
    });
  }
  inputFlow = window.WorkbenchUI.setupFlow({formId: "review-form", validateFiles: validateSelectedFiles, summary: function () {
    return allSources().filter(function (source) { return source.file; }).length + " files selected. Enter the full expected period and define the values in each file.";
  }});
  bindEvents(); syncForm(); updateChrome(); importTransferredRequest();
})();
