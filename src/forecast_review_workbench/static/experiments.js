"use strict";

(function () {
  const U = window.WorkbenchUI, $ = function (id) { return document.getElementById(id); };
  const state = {
    title: "月度回归实验", source_note: "",
    source: U.source("training", "月度历史数据"),
    spec: {horizon: 1, development_end: "", n_splits: 3, validation_months: 12, min_train: 36, target: {name: "", unit: "", transformation: "none"}},
    result: null, request: null, dirty: true, revision: 0, busy: false, revealedInSession: false, editing: true,
    modelIds: [], baselineId: "baseline-mean", revealAccepted: false
  };
  state.source.mapping = {date: null, target: null, features: [{column: null, name: "", lag: 1, release_delay: 0}]};
  let sourceCard, inputFlow;

  function invalidate() {
    state.editing = true;
    state.revision += 1; state.dirty = true; state.request = null; state.revealAccepted = false; state.modelIds = [];
    U.clearMessages(); update();
  }
  function update() {
    if (inputFlow) inputFlow.update(state.busy || state.source.loading);
    $("experiment-form").classList.toggle("hidden", Boolean(state.result && !state.dirty && !state.editing));
    $("edit-experiment-inputs").disabled = state.busy;
    $("experiment-fields").disabled = state.busy;
    $("example-button").disabled = state.busy || state.source.loading;
    $("prepare-button").disabled = state.busy || state.source.loading;
    $("prepare-button").textContent = state.busy ? "正在运行实验…" : "运行开发期实验 →";
    $("add-feature").disabled = state.busy || state.source.mapping.features.length >= 5;
    $("feature-count").textContent = state.source.mapping.features.length + " / 5";
    $("experiment-export").disabled = state.busy || state.dirty || !state.result;
    $("experiment-results").classList.toggle("hidden", !state.result || state.dirty || state.editing);
    $("stale-result").replaceChildren();
    if (state.result && state.dirty) $("stale-result").appendChild(U.el("div", {className: "stale-banner"}, U.el("p", {}, "Your inputs changed. Previous results and any holdout selection are out of date. Run development again before reviewing or exporting.")));
    const reveal = $("reveal-holdout"), acceptance = $("reveal-acceptance"), transfer = $("transfer-review");
    if (acceptance) acceptance.disabled = state.busy || state.dirty;
    if (reveal) reveal.disabled = state.busy || state.dirty || !state.revealAccepted;
    if (transfer) transfer.disabled = state.busy || state.dirty || state.modelIds.length < 1 || state.modelIds.length > 5;
    $("transfer-panel").querySelectorAll("input, select, button").forEach(function (control) {
      if (control.id !== "transfer-review") control.disabled = state.busy || state.dirty;
    });
  }
  function mapping(item, disabled) {
    return U.el("div", {className: "mapping-grid"}, [
      U.field("月份列", U.select(U.columns(item), item.mapping.date, function (event) { item.mapping.date = event.target.value || null; invalidate(); }, {id: "training-date", disabled: disabled || !item.headers.length}), "选择数据对应的月份；月份应连续且唯一。"),
      U.field("实际值列", U.select(U.columns(item), item.mapping.target, function (event) { item.mapping.target = event.target.value || null; invalidate(); }, {id: "training-target", disabled: disabled || !item.headers.length}), "工具按输入值的尺度拟合。")
    ]);
  }
  function mountSource() {
    sourceCard = U.fileCard($("training-source"), state.source, {
      letter: "T", caption: "同一张月度表中的实际值和特征", changed: invalidate, updated: renderFeatures, mapping: mapping,
      reset: function (item) { item.mapping.date = null; item.mapping.target = null; item.mapping.features.forEach(function (feature) { feature.column = null; }); renderFeatures(); },
      inspected: function (item) {
        ["date", "target"].forEach(function (key) { if (!item.headers.includes(item.mapping[key])) item.mapping[key] = null; });
        if (!item.mapping.date) item.mapping.date = item.headers.find(function (name) { return /^(month|date|period)$/i.test(name); }) || null;
        if (!item.mapping.target) item.mapping.target = item.headers.find(function (name) { return /^(target|actual|observed|value)$/i.test(name); }) || null;
        item.mapping.features.forEach(function (feature) { if (!item.headers.includes(feature.column)) feature.column = null; });
        renderFeatures();
      }
    });
  }
  function renderFeatures() {
    $("feature-rows").replaceChildren.apply($("feature-rows"), state.source.mapping.features.map(function (feature, index) {
      const name = U.el("input", {id: "feature-name-" + index, value: feature.name, maxlength: 80, placeholder: "e.g. Activity index", oninput: function (event) { feature.name = event.target.value; invalidate(); }});
      return U.el("div", {className: "feature-row"}, [
        U.field("特征 " + (index + 1) + " 列", U.select(U.columns(state.source), feature.column, function (event) {
          feature.column = event.target.value || null;
          if (!feature.name.trim()) { feature.name = event.target.value; name.value = feature.name; }
          invalidate();
        }, {id: "feature-column-" + index, disabled: state.source.loading || !state.source.headers.length})),
        U.field("显示名称", name),
        U.field("滞后月数", U.el("input", {id: "feature-lag-" + index, type: "number", min: 0, step: 1, value: feature.lag, oninput: function (event) { feature.lag = Number(event.target.value); invalidate(); }})),
        U.field("公布延迟（月）", U.el("input", {id: "feature-delay-" + index, type: "number", min: 0, step: 1, value: feature.release_delay, oninput: function (event) { feature.release_delay = Number(event.target.value); invalidate(); }})),
        U.button("×", function () { state.source.mapping.features.splice(index, 1); invalidate(); renderFeatures(); }, {className: "icon-button", disabled: state.source.mapping.features.length <= 1, "aria-label": "Remove feature " + (index + 1)})
      ]);
    }));
    update();
  }
  function syncInputs() {
    $("experiment-title").value = state.title; $("source-note").value = state.source_note;
    [["horizon", "horizon"], ["development-end", "development_end"], ["n-splits", "n_splits"], ["validation-months", "validation_months"], ["min-train", "min_train"]].forEach(function (pair) { $(pair[0]).value = state.spec[pair[1]]; });
    ["name", "unit", "transformation"].forEach(function (key) { $("target-" + key).value = state.spec.target[key]; });
    mountSource(); renderFeatures(); update();
  }
  function buildRequest() {
    U.requireSource(state.source);
    if (!state.source.mapping.date || !state.source.mapping.target) throw new Error("Map the observation month and observed target columns.");
    if (!state.spec.target.name.trim() || !state.spec.target.unit.trim() || !state.spec.target.transformation.trim()) throw new Error("Complete the target name, unit and transformation declaration.");
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(state.spec.development_end.trim())) throw new Error("Set the development end as YYYY-MM.");
    ["horizon", "n_splits", "validation_months", "min_train"].forEach(function (key) { if (!Number.isInteger(state.spec[key]) || state.spec[key] < 1) throw new Error("Use positive whole months or counts for the experiment settings."); });
    const names = new Set();
    state.source.mapping.features.forEach(function (feature, index) {
      if (!feature.column || !feature.name.trim()) throw new Error("Choose a column and name for feature " + (index + 1) + ".");
      if (names.has(feature.name.trim())) throw new Error("Give each feature a distinct name.");
      names.add(feature.name.trim());
      if (!Number.isInteger(feature.lag) || !Number.isInteger(feature.release_delay) || feature.release_delay < 0 || feature.lag < state.spec.horizon + feature.release_delay) {
        throw new Error(feature.name + ": lag must be a whole number at least horizon + release delay (" + (state.spec.horizon + feature.release_delay) + " months).");
      }
    });
    return {
      schema_version: 1, title: state.title.trim() || "月度回归实验", file: state.source.file, sheet: state.source.sheet, header_row: state.source.header_row,
      mapping: {date: state.source.mapping.date, target: state.source.mapping.target, features: state.source.mapping.features.map(function (feature) { return {column: feature.column, name: feature.name.trim(), lag: feature.lag, release_delay: feature.release_delay}; })},
      spec: Object.assign({}, state.spec, {development_end: state.spec.development_end.trim(), target: {name: state.spec.target.name.trim(), unit: state.spec.target.unit.trim(), transformation: state.spec.target.transformation.trim()}}),
      source_note: state.source_note
    };
  }
  async function prepare() {
    if (state.busy) return;
    U.clearMessages();
    let request;
    try { request = buildRequest(); } catch (error) { U.message(error.message, true); return; }
    const revision = state.revision; state.busy = true; update();
    try {
      const result = await U.api("/api/experiments/prepare", request);
      if (revision !== state.revision) throw new Error("The inputs changed. Run the updated development experiment.");
      state.result = result; state.request = request; state.dirty = false; state.revealAccepted = false; state.modelIds = []; state.editing = false;
      renderResult();
      U.message("Development experiment complete. Holdout scores and predictions remain hidden until you explicitly reveal them.", false);
      $("experiment-results").scrollIntoView({behavior: "smooth", block: "start"});
    } catch (error) { U.message(error.message, true); }
    finally { state.busy = false; update(); }
  }
  function metricCells(metrics) { return [U.cell(metrics ? metrics.n : null, true), U.cell(metrics ? metrics.mae : null, true), U.cell(metrics ? metrics.rmse : null, true), U.cell(metrics ? metrics.bias : null, true)]; }
  function candidateName(candidate) {
    const selected = candidate.id === state.result.selected_on_development;
    return U.el("td", {className: "candidate-name"}, [candidate.name, U.el("small", {}, candidate.role === "baseline" ? "BASELINE" : selected ? "SELECTED ON DEVELOPMENT" : "OLS CANDIDATE")]);
  }
  function metricsTable(stage) {
    return U.table(["Candidate", "Features", "Status", "Rows", "MAE", "RMSE", "Bias", "Failure / limitation"], (state.result.candidates || []).map(function (candidate) {
      const metrics = candidate[stage];
      return U.el("tr", {className: candidate.id === state.result.selected_on_development ? "selected-candidate" : null}, [
        candidateName(candidate), U.el("td", {className: "candidate-features"}, U.text(candidate.features)),
        U.el("td", {className: "status-cell"}, U.badge(candidate.status !== "ok" ? "Failed" : stage === "holdout" && !metrics ? "No holdout score" : "Fitted", candidate.status === "ok" && (stage !== "holdout" || metrics) ? "success" : "warning")),
        metricCells(metrics), U.el("td", {className: "candidate-reason"}, candidate.reason || (stage === "holdout" ? candidate.holdout_reason || (!metrics ? "No usable holdout result." : "—") : "—"))
      ]);
    }));
  }
  function renderResult() {
    const result = state.result, coverage = result.coverage || {}, development = coverage.development || {}, holdout = coverage.holdout || {};
    $("development-context").textContent = state.request.spec.target.name + " · " + state.request.spec.target.unit + " · development through " + state.request.spec.development_end + ". Selection uses pooled development MAE.";
    $("experiment-coverage").replaceChildren(
      U.stat("Original rows", coverage.raw, "All nonempty selected rows"),
      U.stat("Usable rows", coverage.usable, U.text(coverage.excluded) + " excluded across all periods", true),
      U.stat("Development", development.usable, U.text(development.validation_usable) + " validation rows · " + U.text(development.excluded) + " excluded"),
      U.stat("Holdout", holdout.usable, U.text(holdout.excluded) + " excluded from " + U.text(holdout.raw) + " later rows")
    );
    const chosen = (result.candidates || []).find(function (candidate) { return candidate.id === result.selected_on_development; });
    $("selection-summary").replaceChildren(
      U.el("div", {className: "panel-heading"}, [U.el("div", {}, [U.el("h3", {}, chosen ? "Development selection: " + chosen.name : "No successful OLS candidate selected"), U.el("p", {className: "muted compact"}, chosen ? "The lowest pooled development MAE among successful OLS candidates determines this choice. Baselines stay visible; the holdout cannot change this selection." : "Inspect candidate failures and row exclusions before proceeding.")]), U.badge("Development selection locked", chosen ? "success" : "warning")]),
      U.el("div", {className: "protocol-strip"}, [
        U.el("div", {}, [U.el("strong", {}, "Training stays earlier"), U.el("p", {}, "Each validation block uses only information available by its first prediction origin.")]),
        U.el("div", {}, [U.el("strong", {}, "Coefficients stay fixed"), U.el("p", {}, "Holdout forecasts update available lagged features, with frozen fitted coefficients.")]),
        U.el("div", {}, [U.el("strong", {}, "No inverse conversion"), U.el("p", {}, "Metrics use the supplied target space. Transformation is a declaration.")])
      ])
    );
    $("candidate-table").replaceChildren(metricsTable("development"));
    renderHoldout(); renderTransfer(); renderDetails();
    $("experiment-fingerprint").textContent = "Current run: " + result.fingerprint + " · Development selection: " + result.selection_fingerprint;
    update();
  }
  function renderHoldout() {
    const host = $("holdout-panel"); host.replaceChildren();
    if (state.result.stage === "holdout") {
      host.appendChild(U.el("div", {className: "panel"}, [
        U.el("div", {className: "panel-heading"}, [U.el("div", {}, [U.el("h3", {}, "Holdout evidence · revealed"), U.el("p", {className: "muted compact"}, "The development choice remains fixed. These later observations test that choice; they do not select a new winner.")]), U.badge("Holdout revealed", "warning")]),
        metricsTable("holdout")
      ])); return;
    }
    const acceptance = U.el("input", {id: "reveal-acceptance", type: "checkbox", checked: state.revealAccepted, onchange: function (event) { state.revealAccepted = event.target.checked; update(); }});
    host.appendChild(U.el("div", {className: "holdout-lock"}, [
      U.el("h3", {}, "The holdout is still set aside."),
      U.el("p", {}, "Review development coverage, attempted candidates and time splits before opening later results. Once seen, that evidence is no longer unseen data for subsequent tuning."),
      state.revealedInSession ? U.el("div", {className: "extension-alert"}, "You already revealed a holdout earlier in this session. Editing and rerunning does not restore unseen evidence; interpret further tuning as exploratory.") : null,
      U.el("label", {className: "check-label"}, [acceptance, U.el("span", {}, "I have reviewed the development evidence and understand the selected candidate is fixed before holdout results are shown.")]),
      U.button("Reveal holdout results →", revealHoldout, {id: "reveal-holdout", className: "button button-primary", disabled: !state.revealAccepted})
    ]));
  }
  async function revealHoldout() {
    if (state.busy || state.dirty || !state.revealAccepted || state.result.stage !== "development") return;
    const revision = state.revision; state.busy = true; U.clearMessages(); update();
    try {
      const result = await U.api("/api/experiments/reveal", {request: state.request, fingerprint: state.result.fingerprint});
      if (revision !== state.revision) throw new Error("The experiment changed while revealing results. Run the current settings again.");
      state.result = result; state.revealedInSession = true;
      const selected = (result.candidates || []).find(function (candidate) { return candidate.id === result.selected_on_development && candidate.status === "ok" && candidate.holdout; });
      state.modelIds = selected ? [selected.id] : [];
      renderResult(); U.message("Holdout results revealed. The development selection is unchanged.", false);
    } catch (error) { U.message(error.message, true); }
    finally { state.busy = false; update(); }
  }
  function renderTransfer() {
    const host = $("transfer-panel"); host.replaceChildren();
    if (state.result.stage !== "holdout") return;
    const candidates = (state.result.candidates || []).filter(function (candidate) { return candidate.role === "candidate" && candidate.status === "ok" && candidate.holdout; });
    const baselines = (state.result.candidates || []).filter(function (candidate) { return candidate.role === "baseline" && candidate.status === "ok" && candidate.holdout; });
    if (!baselines.some(function (candidate) { return candidate.id === state.baselineId; })) state.baselineId = baselines.length ? baselines[0].id : "";
    host.appendChild(U.el("div", {className: "panel transfer-panel"}, [
      U.el("h3", {}, "Continue in forecast review"),
      U.el("p", {className: "muted compact"}, "Choose one to five candidates and one baseline with usable holdout predictions. All attempted models remain in the experiment tables above."),
      U.el("div", {className: "transfer-models"}, candidates.map(function (candidate) {
        return U.el("label", {className: "check-label"}, [
          U.el("input", {type: "checkbox", value: candidate.id, checked: state.modelIds.includes(candidate.id), onchange: function (event) {
            if (event.target.checked && state.modelIds.length >= 5) { event.target.checked = false; U.message("Choose at most five candidates for forecast review.", true); return; }
            state.modelIds = event.target.checked ? state.modelIds.concat(candidate.id) : state.modelIds.filter(function (id) { return id !== candidate.id; });
            U.clearMessages(); update();
          }}),
          U.el("span", {}, [candidate.name, U.el("small", {}, candidate.id === state.result.selected_on_development ? "Selected on development" : U.text(candidate.features))])
        ]);
      })),
      U.field("Baseline for forecast review", U.select(baselines.map(function (candidate) { return {value: candidate.id, label: candidate.name}; }), state.baselineId, function (event) { state.baselineId = event.target.value; }, {id: "transfer-baseline"})),
      U.el("div", {className: "action-bar"}, [U.el("div", {}, [U.el("strong", {}, "Inspect the generated forecasts."), U.el("p", {}, "Transfer keeps the evidence separate from your review judgement.")]), U.button("Open selected forecasts →", transfer, {id: "transfer-review", className: "button button-primary"})])
    ]));
  }
  async function transfer() {
    if (state.busy || state.dirty || state.result.stage !== "holdout") return;
    if (!state.modelIds.length || state.modelIds.length > 5 || !state.baselineId) { U.message("Select one to five successful candidates and one baseline.", true); return; }
    const revision = state.revision; state.busy = true; U.clearMessages(); update();
    try {
      const data = await U.api("/api/experiments/transfer", {request: state.request, fingerprint: state.result.fingerprint, model_ids: state.modelIds.slice(), baseline_id: state.baselineId});
      if (revision !== state.revision) throw new Error("The experiment changed. Prepare the current settings before transferring.");
      data.request.accept_common_sample = false;
      try { sessionStorage.setItem("frw.import.request", JSON.stringify(data.request)); }
      catch (_error) { throw new Error("The browser could not keep the transfer in this tab. Download the experiment ZIP, then open its forecast files in Forecast review."); }
      window.location.assign("/");
    } catch (error) { U.message(error.message, true); }
    finally { state.busy = false; update(); }
  }
  function renderDetails() {
    const result = state.result;
    const protocol = U.el("dl", {className: "extension-kv"});
    Object.entries(result.protocol || {}).forEach(function (pair) { protocol.append(U.el("dt", {}, pair[0].replaceAll("_", " ")), U.el("dd", {}, U.text(pair[1]))); });
    $("experiment-protocol").replaceChildren(protocol, U.el("p", {className: "extension-help"}, "A time split in software cannot establish that a person has never inspected these observations. Sources and release delays are supplied declarations."));
    U.pagedTable($("fold-table"), result.folds || [], [
      {label: "Model", key: "model_id"}, {label: "Fold", key: "fold"}, {label: "Cutoff", key: "training_cutoff"}, {label: "Training periods", key: "train_periods"}, {label: "Validation periods", key: "validation_periods"},
      {label: "Status", key: "status"}, {label: "Reason", key: "reason"}, {label: "Development metrics", render: function (row) { return U.cell(row.development || row.metrics); }}
    ], {searchLabel: "Search fold details"});
    const fits = $("fit-details"); fits.replaceChildren();
    (result.candidates || []).forEach(function (candidate) {
      const kv = U.el("dl", {className: "extension-kv"});
      Object.entries(candidate.fit || {}).forEach(function (pair) { kv.append(U.el("dt", {}, pair[0].replaceAll("_", " ")), U.el("dd", {}, U.text(pair[1]))); });
      fits.appendChild(U.el("details", {className: "extension-details"}, [U.el("summary", {}, candidate.name + " · fit details"), kv]));
    });
    const originalRows = new Map((result.source_rows || []).map(function (row) { return [row.period, row]; }));
    const inputRows = (result.input_rows || []).map(function (row) { return Object.assign({}, row, {row: (originalRows.get(row.period) || {}).row, raw: (originalRows.get(row.period) || {}).raw}); });
    U.pagedTable($("experiment-input-rows"), inputRows, [
      {label: "Original row", key: "row"}, {label: "Period", key: "period"}, {label: "Split", key: "split"}, {label: "Status", key: "status"}, {label: "Reasons", key: "reasons"},
      {label: "Raw selected cells", key: "raw"}, {label: "Target", key: "target", numeric: true}, {label: "Raw features", key: "features"}, {label: "Lagged features", key: "lagged_features"}, {label: "Feature source months", key: "feature_source_periods"}
    ], {searchLabel: "Search original rows or reasons"});
    U.pagedTable($("experiment-predictions"), result.predictions || [], [
      {label: "Model", key: "model_id"}, {label: "Period", key: "period"}, {label: "Split", key: "split"}, {label: "Actual", render: function (row) { return U.cell(row.actual === undefined ? row.target : row.actual, true); }},
      {label: "Prediction", key: "prediction", numeric: true}, {label: "Error", render: function (row) { return U.cell(row.residual === undefined ? row.error : row.residual, true); }},
      {label: "Origin", key: "origin"}, {label: "Training cutoff", key: "training_cutoff"}
    ], {searchLabel: "Search prediction records"});
  }
  async function exportExperiment() {
    if (state.busy || state.dirty || !state.result) return;
    const revision = state.revision; state.busy = true; U.clearMessages(); update();
    try {
      await U.download("/api/experiments/export", {request: state.request, fingerprint: state.result.fingerprint, stage: state.result.stage}, state.title, function () { return revision === state.revision; });
      U.message("Experiment ZIP downloaded for the current " + state.result.stage + " stage.", false);
    } catch (error) { U.message(error.message, true); }
    finally { state.busy = false; update(); }
  }
  async function loadExample() {
    if (state.busy || state.source.loading) return;
    state.busy = true; U.clearMessages(); update();
    try {
      const request = await U.api("/api/experiments/example");
      state.title = request.title; state.spec = request.spec; state.source_note = request.source_note || "";
      state.source = U.restoreSource("training", "月度历史数据", request);
      invalidate(); syncInputs(); await sourceCard.inspect();
      U.message("已载入虚构历史数据。确认日期和实际值列后，进入下一步检查特征与时间设置。", false);
    } catch (error) { U.message(error.message, true); }
    finally { state.busy = false; update(); }
  }
  $("experiment-form").addEventListener("submit", function (event) { event.preventDefault(); if (inputFlow.current() === "files") inputFlow.next(); else prepare(); });
  $("edit-experiment-inputs").addEventListener("click", function () { state.editing = true; update(); inputFlow.show("settings", true); });
  $("experiment-title").addEventListener("input", function (event) { state.title = event.target.value; invalidate(); });
  $("source-note").addEventListener("input", function (event) { state.source_note = event.target.value; invalidate(); });
  ["name", "unit", "transformation"].forEach(function (key) { $("target-" + key).addEventListener("input", function (event) { state.spec.target[key] = event.target.value; invalidate(); }); });
  [["horizon", "horizon"], ["development-end", "development_end"], ["n-splits", "n_splits"], ["validation-months", "validation_months"], ["min-train", "min_train"]].forEach(function (pair) {
    $(pair[0]).addEventListener("input", function (event) { state.spec[pair[1]] = pair[1] === "development_end" ? event.target.value : Number(event.target.value); invalidate(); });
  });
  $("add-feature").addEventListener("click", function () { if (state.source.mapping.features.length < 5) { state.source.mapping.features.push({column: null, name: "", lag: state.spec.horizon, release_delay: 0}); invalidate(); renderFeatures(); } });
  $("example-button").addEventListener("click", loadExample);
  $("experiment-export").addEventListener("click", exportExperiment);
  inputFlow = U.setupFlow({formId: "experiment-form", validateFiles: function () {
    U.requireSource(state.source);
    if (!state.source.mapping.date || !state.source.mapping.target) throw new Error("请先确认月份列和实际值列。");
  }, summary: function () { return state.source.file ? state.source.file.name + " · " + U.text(state.source.row_count) + " 个非空行。请按预先约定确认时间设置。" : "请先选择月度历史表。"; }});
  syncInputs();
})();
