"use strict";

(function () {
  const U = window.WorkbenchUI, $ = function (id) { return document.getElementById(id); };
  const DIMENSIONS = [
    ["record_id", "记录 ID"], ["date", "日期"], ["measure", "指标"], ["risk_type", "风险类型（可选）"],
    ["tenor", "期限（可选）"], ["currency", "币种"], ["unit", "单位"], ["value", "数值"]
  ];
  const state = {
    title: "金融结果对账", absolute_tolerance: "0.01", relative_tolerance: "0.0001", additive: false,
    left: U.source("left", "参考表"), right: U.source("right", "待比较表"),
    left_totals: U.source("left-totals", "参考侧上报总额"), right_totals: U.source("right-totals", "待比较侧上报总额"),
    leftTotalsEnabled: false, rightTotalsEnabled: false,
    result: null, request: null, dirty: true, revision: 0, busy: false, notes: {}, view: "rows", editing: true
  };
  let cards = {}, inputFlow;

  function sources() { return [state.left, state.right].concat(state.leftTotalsEnabled ? [state.left_totals] : [], state.rightTotalsEnabled ? [state.right_totals] : []); }
  function invalidate() {
    state.editing = true;
    state.revision += 1; state.dirty = true; state.request = null;
    Object.values(state.notes).forEach(function (note) { if (note.text.trim() || note.decision) note.stale = true; });
    U.clearMessages(); update();
  }
  function update() {
    const loading = sources().some(function (source) { return source.loading; });
    if (inputFlow) inputFlow.update(state.busy || loading);
    $("reconcile-form").classList.toggle("hidden", Boolean(state.result && !state.dirty && !state.editing));
    $("edit-reconcile-inputs").disabled = state.busy;
    $("reconcile-fields").disabled = state.busy;
    $("example-button").disabled = state.busy || loading;
    $("reconcile-button").disabled = state.busy || loading;
    $("reconcile-button").textContent = state.busy ? "正在对账…" : "开始对账 →";
    $("reconcile-export").disabled = state.busy || state.dirty || !state.result;
    $("reconcile-results").classList.toggle("hidden", !state.result || state.dirty || state.editing);
    $("left-totals-source").classList.toggle("hidden", !state.leftTotalsEnabled);
    $("right-totals-source").classList.toggle("hidden", !state.rightTotalsEnabled);
    $("stale-result").replaceChildren();
    if (state.result && state.dirty) $("stale-result").appendChild(U.el("div", {className: "stale-banner"}, U.el("p", {}, "Inputs changed. Previous results and notes are out of date. Reconcile the current files before using or exporting the evidence.")));
    $("reconcile-notes").querySelectorAll("select, textarea, button").forEach(function (control) {
      const card = control.closest(".note-card");
      control.disabled = state.busy || (control.tagName !== "BUTTON" && Boolean(card && card.classList.contains("stale")));
    });
    $("record-table").querySelectorAll("[data-note-action]").forEach(function (control) { control.disabled = state.busy; });
  }
  function mapping(item, disabled, totals, meaning) {
    const grid = U.el("div", {className: "dimension-grid"}, [
      U.el("span", {className: "dimension-heading"}, "含义"), U.el("span", {className: "dimension-heading"}, "选择列"), U.el("span", {className: "dimension-heading"}, "或填写固定值")
    ]);
    DIMENSIONS.filter(function (pair) {
      if (totals) return pair[0] !== "record_id";
      const core = pair[0] === "record_id" || pair[0] === "value";
      return meaning ? !core : core;
    }).forEach(function (pair) {
      const key = pair[0], required = key === "record_id" || key === "value", optional = key === "risk_type" || key === "tenor";
      const defaultInput = !required ? U.el("input", {
        id: item.id + "-default-" + key, className: "dimension-default", value: item.defaults[key] || "", maxlength: 120,
        disabled: disabled || Boolean(item.mapping[key]), placeholder: optional ? "可留空" : "未选列时须填写",
        "aria-label": item.name + " constant " + pair[1], oninput: function (event) { item.defaults[key] = event.target.value; invalidate(); }
      }) : U.el("span", {className: "no-default"}, "须选择列");
      const mappingSelect = U.select(U.columns(item, required ? "选择列" : optional ? "固定值／留空" : "填写固定值"), item.mapping[key], function (event) {
        item.mapping[key] = event.target.value || null;
        if (!required) defaultInput.disabled = Boolean(item.mapping[key]);
        invalidate();
      }, {id: item.id + "-" + key, className: "dimension-select", disabled: disabled || !item.headers.length, "aria-label": item.name + " " + pair[1] + " column"});
      grid.append(U.el("span", {className: "dimension-label"}, pair[1] + (required ? " *" : "")), mappingSelect, defaultInput);
    });
    return U.el("div", {}, [
      grid,
      U.el("p", {className: "extension-help"}, totals ? "Totals use the same financial dimensions as detailed rows. Every supplied group remains visible." : "Record identity uses ID, date, measure, risk type and tenor. Currency and unit are checked separately before comparing values.")
    ]);
  }
  function mountSources() {
    cards = {};
    [["left", "R", false], ["right", "C", false], ["left_totals", "ΣR", true], ["right_totals", "ΣC", true]].forEach(function (entry) {
      const key = entry[0], item = state[key];
      cards[key] = U.fileCard($(item.id + "-source"), item, {
        letter: entry[1], caption: entry[2] ? "独立提供的分组上报总额" : key === "left" ? "相对容差以此侧数值为基准" : "与参考侧逐笔比较的数值",
        changed: invalidate, updated: function () {
          if (!entry[2]) $(item.id + "-dimensions").replaceChildren(U.el("h3", {}, item.name), mapping(item, item.loading, false, true));
          update();
        },
        mapping: function (source, disabled) { return mapping(source, disabled, entry[2]); },
        reset: function (source) { source.mapping = {}; },
        inspected: function (source) {
          Object.keys(source.mapping).forEach(function (field) { if (!source.headers.includes(source.mapping[field])) source.mapping[field] = null; });
          const patterns = {record_id: /^(record[_ ]?id|trade[_ ]?id|id)$/i, date: /^(date|valuation[_ ]?date|as[_ ]?of|month|period)$/i,
            measure: /^(measure|metric)$/i, risk_type: /^(risk[_ ]?type|risk)$/i, tenor: /^tenor$/i,
            currency: /^(currency|ccy)$/i, unit: /^unit$/i, value: /^(value|amount|result|total)$/i};
          Object.entries(patterns).forEach(function (pair) {
            if ((!entry[2] || pair[0] !== "record_id") && !source.mapping[pair[0]]) source.mapping[pair[0]] = source.headers.find(function (name) { return pair[1].test(name); }) || null;
          });
        }
      });
    });
  }
  function sourcePayload(source, totals) {
    U.requireSource(source);
    if (!source.mapping.value || (!totals && !source.mapping.record_id)) throw new Error("Map " + (totals ? "the numeric value" : "record ID and numeric value") + " for " + source.name + ".");
    ["date", "measure", "currency", "unit"].forEach(function (field) {
      if (!source.mapping[field] && !String(source.defaults[field] || "").trim()) throw new Error(source.name + ": map " + field + " or declare one constant for the file.");
    });
    const mapped = {}, defaults = {};
    DIMENSIONS.filter(function (pair) { return !totals || pair[0] !== "record_id"; }).forEach(function (pair) {
      mapped[pair[0]] = source.mapping[pair[0]] || null;
      if (pair[0] !== "record_id" && pair[0] !== "value") defaults[pair[0]] = source.defaults[pair[0]] || "";
    });
    return {name: source.name, file: source.file, sheet: source.sheet, header_row: source.header_row, mapping: mapped, defaults: defaults};
  }
  function buildRequest() {
    if ((state.leftTotalsEnabled || state.rightTotalsEnabled) && !state.additive) throw new Error("Reported totals require your explicit confirmation that values are additive within the declared groups.");
    ["absolute_tolerance", "relative_tolerance"].forEach(function (key) {
      const value = state[key].trim();
      if (!value || !Number.isFinite(Number(value)) || Number(value) < 0) throw new Error("Tolerances must be nonnegative finite numbers. Relative tolerance is a ratio.");
    });
    return {
      schema_version: 1, title: state.title.trim() || "金融结果对账",
      left: sourcePayload(state.left, false), right: sourcePayload(state.right, false),
      left_totals: state.leftTotalsEnabled ? sourcePayload(state.left_totals, true) : null,
      right_totals: state.rightTotalsEnabled ? sourcePayload(state.right_totals, true) : null,
      absolute_tolerance: state.absolute_tolerance.trim(), relative_tolerance: state.relative_tolerance.trim(), additive: state.additive
    };
  }
  function syncInputs() {
    $("reconcile-title").value = state.title; $("absolute-tolerance").value = state.absolute_tolerance; $("relative-tolerance").value = state.relative_tolerance;
    $("additive").checked = state.additive; $("left-totals-enabled").checked = state.leftTotalsEnabled; $("right-totals-enabled").checked = state.rightTotalsEnabled;
    mountSources(); update();
  }
  async function reconcile() {
    if (state.busy) return;
    U.clearMessages(); let request;
    try { request = buildRequest(); } catch (error) { U.message(error.message, true); return; }
    const revision = state.revision; state.busy = true; update();
    try {
      const result = await U.api("/api/reconcile", request);
      if (revision !== state.revision) throw new Error("The inputs changed. Reconcile the current files again.");
      state.result = result; state.request = request; state.dirty = false; state.editing = false;
      renderResult(); U.message("Reconciliation complete. Inspect row differences before interpreting group totals.", false);
      $("reconcile-results").scrollIntoView({behavior: "smooth", block: "start"});
    } catch (error) { U.message(error.message, true); }
    finally { state.busy = false; update(); }
  }
  function statusLabel(status) {
    const labels = {pass: "Within tolerance", breach: "Outside tolerance", missing_left: "Missing reference", missing_right: "Missing challenger", duplicate: "Duplicate key",
      invalid: "Invalid value / key", definition_conflict: "Currency / unit conflict", missing_reported: "Missing reported total", missing_raw: "Missing detailed rows", blocked: "Blocked by invalid rows", attention: "Needs attention"};
    return labels[status] || String(status || "Needs review").replaceAll("_", " ");
  }
  function statusCell(status) { return U.el("td", {className: "status-cell"}, U.badge(statusLabel(status), status === "pass" ? "success" : "warning")); }
  function dimensions(value, withId) {
    const d = value || {};
    return U.el("td", {className: "group-key"}, [
      withId ? U.el("strong", {}, U.text(d.record_id)) : null,
      U.el("div", {}, U.text(d.date) + " · " + U.text(d.measure)),
      U.el("div", {}, (d.risk_type ? d.risk_type + " · " : "") + (d.tenor || "No tenor")),
      !withId ? U.el("div", {}, U.text(d.currency) + " · " + U.text(d.unit)) : null
    ]);
  }
  function valueCell(value, currency, unit) {
    return U.el("td", {className: "numeric", title: U.text(value)}, [U.number(value), U.el("small", {className: "row-ref"}, [U.text(currency), " · ", U.text(unit)])]);
  }
  function renderResult() {
    const result = state.result, summary = result.summary || {};
    const attention = Number(summary.expected || 0) - Number(summary.pass || 0);
    $("reconcile-context").textContent = U.text(summary.left_rows) + " reference rows · " + U.text(summary.right_rows) + " challenger rows. Coverage is the union of supplied keys; records absent from both files cannot be discovered here.";
    $("reconcile-summary").replaceChildren(
      U.stat("Record keys", summary.expected, "Union of both supplied tables"),
      U.stat("Comparable", summary.comparable, "Unique, valid and compatible"),
      U.stat("Within tolerance", summary.pass, "Each individual record", true),
      U.stat("Row attention", attention, "Record gaps, conflicts or differences")
    );
    const warnings = $("reconcile-warnings"); warnings.replaceChildren();
    if (summary.definition_conflict) warnings.appendChild(U.el("div", {className: "extension-alert"}, U.text(summary.definition_conflict) + " records have incompatible currency or unit declarations. They are not compared numerically."));
    if (result.additive && summary.group_attention) warnings.appendChild(U.el("div", {className: "extension-alert"}, U.text(summary.group_attention) + " financial groups need attention. Matching net amounts do not clear missing rows, invalid values or offsetting row differences."));
    if (summary.reported_totals_attention) warnings.appendChild(U.el("div", {className: "extension-alert"}, [
      U.el("strong", {}, U.text(summary.reported_totals_attention) + " reported-total checks need attention. "),
      "These checks are separate from individual-record and cross-source group results. ",
      U.button("Inspect reported totals →", function () { showView("totals"); $("view-totals").scrollIntoView({behavior: "smooth", block: "start"}); }, {className: "text-button"})
    ]));
    const list = result.warnings || [];
    if (list.length) warnings.appendChild(U.el("ul", {className: "warnings-list"}, list.map(function (warning) { return U.el("li", {}, U.text(warning)); })));
    renderRows(); renderGroups(); renderTotals(); renderInputRows(); renderMetadata(); renderNotes(); showView(state.view);
    $("reconcile-fingerprint").textContent = "Current review fingerprint: " + result.fingerprint;
    update();
  }
  function renderRows() {
    U.pagedTable($("record-table"), state.result.rows || [], [
      {label: "Record & dimensions", render: function (row) { return dimensions(row.identity, true); }},
      {label: "Reference", render: function (row) { return valueCell(row.reference, row.reference_currency, row.reference_unit); }},
      {label: "Challenger", render: function (row) { return valueCell(row.challenger, row.challenger_currency, row.challenger_unit); }},
      {label: "Difference", render: function (row) { return U.cell(row.status === "definition_conflict" ? null : row.difference, true); }},
      {label: "|Difference|", render: function (row) { return U.cell(row.status === "definition_conflict" ? null : row.absolute_difference, true); }},
      {label: "Allowed", render: function (row) { return U.cell(row.status === "definition_conflict" ? null : row.allowed_difference, true); }},
      {label: "Status", render: function (row) { return statusCell(row.status); }},
      {label: "Explanation", key: "reasons"},
      {label: "Original rows", render: function (row) { const refs = row.source_rows || {}; return U.el("td", {}, [U.el("div", {}, "Reference: " + U.text(refs.left)), U.el("div", {}, "Challenger: " + U.text(refs.right))]); }},
      {label: "Review", render: function (row) { return U.el("td", {}, U.button("Add / view note", function () { addNote(row); }, {"data-note-action": true, disabled: state.busy})); }}
    ], {searchLabel: "Search ID, status or explanation"});
  }
  function renderGroups() {
    const host = $("group-table");
    if (!state.result.additive) { host.replaceChildren(U.el("div", {className: "report-total-info"}, "Group sums are not shown. Confirm additivity in the input settings and reconcile again if these values can be summed within each financial group.")); return; }
    U.pagedTable(host, state.result.groups || [], [
      {label: "Financial group", render: function (row) { return dimensions(row.dimensions, false); }},
      {label: "Reference", key: "reference", numeric: true}, {label: "Challenger", key: "challenger", numeric: true}, {label: "Difference", key: "difference", numeric: true},
      {label: "|Difference|", key: "absolute_difference", numeric: true}, {label: "Allowed", key: "allowed_difference", numeric: true},
      {label: "Status", render: function (row) { return statusCell(row.status); }},
      {label: "Offsetting breaches", render: function (row) { return U.el("td", {}, row.offsetting_breaches ? U.badge("Yes · inspect rows", "warning") : "No"); }},
      {label: "Explanation", key: "reasons"},
      {label: "Rows, reference / challenger", render: function (row) { return U.cell(U.text(row.reference_rows) + " / " + U.text(row.challenger_rows)); }},
      {label: "Member records", render: function (row) { return U.el("td", {}, U.el("details", {}, [U.el("summary", {}, (row.record_keys || []).length + " record keys"), U.el("p", {className: "note-row-ref"}, U.text(row.record_keys))])); }}
    ], {searchLabel: "Search financial group or reason"});
  }
  function renderTotals() {
    const host = $("reported-totals-table");
    if (!state.result.additive) { host.replaceChildren(U.el("div", {className: "report-total-info"}, "Reported totals can only be checked after you explicitly confirm additivity within the financial groups.")); return; }
    if (!state.request.left_totals && !state.request.right_totals) { host.replaceChildren(U.el("div", {className: "report-total-info"}, "No reported-total files were supplied. Add either side’s totals in the input section to compare them with its detailed rows.")); return; }
    U.pagedTable(host, state.result.reported_totals || [], [
      {label: "Side", render: function (row) { return U.cell(row.side === "left" ? "Reference" : row.side === "right" ? "Challenger" : row.side); }},
      {label: "Financial group", render: function (row) { return dimensions(row.dimensions, false); }},
      {label: "Calculated from rows", key: "calculated", numeric: true}, {label: "Reported", key: "reported", numeric: true},
      {label: "Difference", key: "difference", numeric: true}, {label: "|Difference|", key: "absolute_difference", numeric: true}, {label: "Allowed", key: "allowed_difference", numeric: true},
      {label: "Status", render: function (row) { return statusCell(row.status); }}, {label: "Explanation", key: "reasons"}, {label: "Original total rows", key: "source_rows"}
    ], {searchLabel: "Search totals by group or status"});
  }
  function renderInputRows() {
    U.pagedTable($("reconcile-input-rows"), state.result.input_rows || [], [
      {label: "Source", key: "source_id"}, {label: "Original row", key: "row"}, {label: "Raw mapped values", key: "raw"}, {label: "Parsed values", key: "values"},
      {label: "Errors", key: "errors"}, {label: "Record key", key: "record_key"}, {label: "Group key", key: "group_key"}
    ], {searchLabel: "Search original values or errors"});
  }
  function showView(view) {
    state.view = view;
    ["rows", "groups", "totals"].forEach(function (key) {
      $("view-" + key).classList.toggle("hidden", key !== view);
      document.querySelector('[data-view="' + key + '"]').setAttribute("aria-pressed", String(key === view));
    });
  }
  function noteTitle(row) { const identity = row.identity || {}; return U.text(identity.record_id) + " · " + U.text(identity.date) + " · " + U.text(identity.measure); }
  function addNote(row) {
    if (state.busy || state.dirty) return;
    if (!state.notes[row.record_key]) state.notes[row.record_key] = {record_key: row.record_key, title: noteTitle(row), decision: "", text: "", fingerprint: state.result.fingerprint, stale: false};
    renderNotes();
    const noteIndex = Object.keys(state.notes).indexOf(row.record_key);
    const card = $("reconcile-note-" + noteIndex);
    if (card) { card.scrollIntoView({behavior: "smooth", block: "center"}); const control = card.querySelector("select:not(:disabled), button"); if (control) control.focus({preventScroll: true}); }
  }
  function renderNotes() {
    const host = $("reconcile-notes"); host.replaceChildren();
    const currentKeys = new Set((state.result.rows || []).map(function (row) { return row.record_key; }));
    const entries = Object.values(state.notes);
    if (!entries.length) { host.appendChild(U.el("p", {className: "notes-disabled-message"}, "Use “Add / view note” beside a record to explain a difference or request more evidence. Notes are optional.")); return; }
    entries.forEach(function (note, index) {
      const stale = note.stale || note.fingerprint !== state.result.fingerprint;
      const present = currentKeys.has(note.record_key);
      const card = U.el("div", {id: "reconcile-note-" + index, className: "note-card" + (stale ? " stale" : "")}, [
        U.el("h3", {}, note.title), U.el("p", {className: "note-row-ref"}, "Record key: " + note.record_key)
      ]);
      if (stale) {
        card.appendChild(U.el("div", {className: "note-stale-message"}, present ? "This opinion belongs to earlier inputs. Recheck it against the current evidence before using it." : "This record is not in the current review. Discard this draft before exporting the current result."));
        card.appendChild(U.el("div", {className: "note-stale-actions"}, [
          present ? U.button("Rechecked · use for this run", function () { note.fingerprint = state.result.fingerprint; note.stale = false; U.clearMessages(); renderNotes(); }, {className: "text-button"}) : null,
          U.button("Discard this draft", function () { delete state.notes[note.record_key]; U.clearMessages(); renderNotes(); }, {className: "text-button danger-button"})
        ]));
      }
      const decision = U.select([{value: "", label: "Choose a review decision"}, {value: "needs_evidence", label: "Needs more evidence"}, {value: "accepted_difference", label: "Accept this difference"}], note.decision, function (event) { note.decision = event.target.value; U.clearMessages(); }, {id: "reconcile-decision-" + index, disabled: stale});
      const comments = U.el("textarea", {id: "reconcile-text-" + index, value: note.text, rows: 3, maxlength: 4000, disabled: stale, placeholder: "Describe supporting evidence, the explanation or what is still missing.", oninput: function (event) { note.text = event.target.value; }});
      card.append(U.field("Decision", decision), U.field("Evidence and reasoning", comments, "Up to 4,000 characters. The computed comparison status stays unchanged."));
      if (!stale) card.appendChild(U.el("div", {className: "inline-actions"}, U.button("Remove note", function () { delete state.notes[note.record_key]; U.clearMessages(); renderNotes(); }, {className: "text-button danger-button"})));
      host.appendChild(card);
    });
    update();
  }
  function renderMetadata() {
    const host = $("reconcile-metadata"); host.replaceChildren();
    const summary = state.result.summary || {};
    const counts = U.el("dl", {className: "extension-kv"});
    ["breach", "missing_left", "missing_right", "duplicate", "invalid", "definition_conflict", "groups", "group_attention", "reported_totals_attention"].forEach(function (key) {
      counts.append(U.el("dt", {}, key.replaceAll("_", " ")), U.el("dd", {}, U.text(summary[key])));
    });
    host.appendChild(counts);
    const sourceValues = Array.isArray(state.result.sources) ? state.result.sources : Object.values(state.result.sources || {});
    sourceValues.forEach(function (source) {
      const fields = U.el("dl", {className: "extension-kv"});
      Object.entries(source).forEach(function (pair) { fields.append(U.el("dt", {}, pair[0].replaceAll("_", " ")), U.el("dd", {}, U.text(pair[1]))); });
      host.appendChild(U.el("details", {className: "extension-details"}, [U.el("summary", {}, source.name || source.id || source.file_name || "Source"), fields]));
    });
    host.appendChild(U.el("p", {className: "extension-help"}, "Difference is challenger minus reference. The allowed magnitude is absolute tolerance + relative tolerance × |reference|. This checks additive values; it does not reproduce nonlinear margin aggregation or a pricing model."));
  }
  async function exportReconciliation() {
    if (state.busy || state.dirty || !state.result || !state.request) return;
    U.clearMessages();
    const notes = Object.values(state.notes).filter(function (note) { return note.text.trim() || note.decision; });
    if (notes.some(function (note) { return note.stale || note.fingerprint !== state.result.fingerprint; })) { U.message("Some notes belong to earlier inputs. Recheck and explicitly reuse them, or discard them before exporting.", true); return; }
    if (notes.some(function (note) { return !note.text.trim() || !note.decision; })) { U.message("Choose a decision and add evidence for every note you keep. Empty notes are omitted.", true); return; }
    const revision = state.revision; state.busy = true; update();
    try {
      await U.download("/api/reconcile/export", {request: state.request, fingerprint: state.result.fingerprint, notes: notes.map(function (note) {
        return {record_key: note.record_key, decision: note.decision, text: note.text, fingerprint: note.fingerprint};
      })}, state.title, function () { return revision === state.revision; });
      U.message("Reconciliation ZIP downloaded with the current results and notes for this exact review.", false);
    } catch (error) { U.message(error.message, true); }
    finally { state.busy = false; update(); }
  }
  async function loadExample() {
    if (state.busy || sources().some(function (source) { return source.loading; })) return;
    state.busy = true; U.clearMessages(); update();
    try {
      const request = await U.api("/api/reconcile/example");
      state.title = request.title; state.absolute_tolerance = request.absolute_tolerance; state.relative_tolerance = request.relative_tolerance;
      state.additive = false;
      $("aggregation-options").open = true;
      state.leftTotalsEnabled = Boolean(request.left_totals); state.rightTotalsEnabled = Boolean(request.right_totals);
      state.left = U.restoreSource("left", "参考表", request.left);
      state.right = U.restoreSource("right", "待比较表", request.right);
      state.left_totals = U.restoreSource("left-totals", "参考侧上报总额", request.left_totals);
      state.right_totals = U.restoreSource("right-totals", "待比较侧上报总额", request.right_totals);
      invalidate(); syncInputs();
      const keys = ["left", "right"].concat(state.leftTotalsEnabled ? ["left_totals"] : [], state.rightTotalsEnabled ? ["right_totals"] : []);
      for (const key of keys) await cards[key].inspect();
      U.message("已载入虚构文件。先确认 ID 和数值列，再进入下一步；检查示例总额需要你明确确认可加性。", false);
    } catch (error) { U.message(error.message, true); }
    finally { state.busy = false; update(); }
  }
  $("reconcile-form").addEventListener("submit", function (event) { event.preventDefault(); if (inputFlow.current() === "files") inputFlow.next(); else reconcile(); });
  $("edit-reconcile-inputs").addEventListener("click", function () { state.editing = true; update(); inputFlow.show("settings", true); });
  $("reconcile-title").addEventListener("input", function (event) { state.title = event.target.value; invalidate(); });
  [["absolute-tolerance", "absolute_tolerance"], ["relative-tolerance", "relative_tolerance"]].forEach(function (pair) {
    $(pair[0]).addEventListener("input", function (event) { state[pair[1]] = event.target.value; invalidate(); });
  });
  $("additive").addEventListener("change", function (event) { state.additive = event.target.checked; invalidate(); });
  $("left-totals-enabled").addEventListener("change", function (event) { state.leftTotalsEnabled = event.target.checked; invalidate(); });
  $("right-totals-enabled").addEventListener("change", function (event) { state.rightTotalsEnabled = event.target.checked; invalidate(); });
  document.querySelectorAll("[data-view]").forEach(function (control) { control.addEventListener("click", function () { showView(control.dataset.view); }); });
  $("example-button").addEventListener("click", loadExample);
  $("reconcile-export").addEventListener("click", exportReconciliation);
  inputFlow = U.setupFlow({formId: "reconcile-form", validateFiles: function () {
    [state.left, state.right].forEach(function (source) {
      U.requireSource(source);
      if (!source.mapping.record_id || !source.mapping.value) throw new Error("请为“" + source.name + "”确认记录 ID 列与数值列。");
    });
  }, summary: function () {
    return [state.left, state.right].map(function (source) { return source.file ? source.file.name : "未选文件"; }).join(" ↔ ") + "。请核对下列维度，未映射的必填项需声明固定值。";
  }});
  syncInputs();
})();
