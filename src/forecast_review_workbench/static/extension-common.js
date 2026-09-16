"use strict";

(function () {
  function append(parent, child) {
    if (Array.isArray(child)) child.forEach(function (item) { append(parent, item); });
    else if (child !== null && child !== undefined && child !== false) parent.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(function (pair) {
      const key = pair[0], value = pair[1];
      if (key === "value" || key === "checked") return;
      if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (key === "className") node.className = value;
      else if (value !== null && value !== undefined && value !== false) node.setAttribute(key, value === true ? "" : String(value));
    });
    append(node, children);
    if (Object.hasOwn(attrs || {}, "value")) node.value = attrs.value === null ? "" : attrs.value;
    if (Object.hasOwn(attrs || {}, "checked")) node.checked = Boolean(attrs.checked);
    return node;
  }
  function button(label, action, attrs) { return el("button", Object.assign({type: "button", className: "button button-small", onclick: action}, attrs || {}), label); }
  function field(label, control, help) { return el("label", {className: "field"}, [el("span", {}, label), control, help ? el("small", {}, help) : null]); }
  function select(options, value, action, attrs) {
    return el("select", Object.assign({value: value || "", onchange: action}, attrs || {}), options.map(function (option) {
      const item = typeof option === "string" ? {value: option, label: option} : option;
      return el("option", {value: item.value}, item.label);
    }));
  }
  function text(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (Array.isArray(value)) return value.map(text).join(" · ");
    if (typeof value === "object") return Object.entries(value).map(function (pair) { return pair[0].replaceAll("_", " ") + ": " + text(pair[1]); }).join("; ");
    return String(value);
  }
  function number(value) {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value);
    if (n === 0) return "0";
    return Math.abs(n) >= 1e9 || Math.abs(n) < 0.00001 ? n.toExponential(4) : new Intl.NumberFormat("en", {maximumSignificantDigits: 7}).format(n);
  }
  function cell(value, numeric) { return el("td", {className: numeric ? "numeric" : null, title: text(value)}, numeric ? number(value) : text(value)); }
  function table(headers, rows) {
    return el("div", {className: "table-wrap", tabindex: "0", "aria-label": "Scrollable data table"}, el("table", {}, [
      el("thead", {}, el("tr", {}, headers.map(function (label) { return el("th", {}, label); }))),
      el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", {colspan: headers.length, className: "empty-state"}, "当前没有符合条件的记录。")))
    ]));
  }
  function stat(label, value, detail, emphasis) { return el("div", {className: "stat-card" + (emphasis ? " emphasis" : "")}, [el("div", {className: "stat-label"}, label), el("div", {className: "stat-value"}, text(value)), el("div", {className: "stat-description"}, detail)]); }
  function badge(label, status) { return el("span", {className: "tag" + (status ? " tag-" + status : "")}, label); }
  function clearMessages() { ["notice", "error"].forEach(function (id) { document.getElementById(id).classList.add("hidden"); }); }
  function message(value, error) {
    clearMessages();
    const host = document.getElementById(error ? "error" : "notice");
    host.textContent = value; host.classList.remove("hidden");
    if (error) host.scrollIntoView({behavior: "smooth", block: "center"});
  }
  function headers() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return {"Content-Type": "application/json", "X-Workbench-Token": meta ? meta.content : ""};
  }
  function transport() {
    const browserPage = document.querySelector('meta[name="frw-runtime"][content="browser"]');
    const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);
    if ((browserPage || !loopback) && !window.FrwBrowser) throw new Error("浏览器计算组件未能加载。请刷新后重试；文件没有上传。");
    return window.FrwBrowser || null;
  }
  async function api(url, payload) {
    const browser = transport();
    if (browser) return browser.request(url, payload);
    const response = await fetch(url, {method: payload === undefined ? "GET" : "POST", credentials: "same-origin", headers: headers(), body: payload === undefined ? undefined : JSON.stringify(payload)});
    let data;
    try { data = await response.json(); } catch (_error) { throw new Error("The local application returned an unreadable response."); }
    if (!response.ok) throw new Error(data.error || "The local request could not be completed.");
    return data;
  }
  async function download(url, payload, title, isCurrent) {
    let blob;
    const browser = transport();
    if (browser) blob = await browser.download(url, payload);
    else {
      const response = await fetch(url, {method: "POST", credentials: "same-origin", headers: headers(), body: JSON.stringify(payload)});
      if (!response.ok) { const data = await response.json(); throw new Error(data.error || "无法下载复核结果。"); }
      blob = await response.blob();
    }
    if (isCurrent && !isCurrent()) throw new Error("The inputs changed while preparing the download. Run the updated analysis first.");
    const href = URL.createObjectURL(blob);
    const name = String(title || "workbench-review").replace(/[^a-zA-Z0-9_-]+/g, "-").slice(0, 70) || "workbench-review";
    const link = el("a", {href: href, download: name + ".zip", className: "hidden"});
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(function () { URL.revokeObjectURL(href); }, 60000);
  }
  function source(id, name) {
    return {id: id, name: name, file: null, sheet: null, header_row: 1, mapping: {}, defaults: {},
      sheets: [], headers: [], preview: [], row_count: null, error: "", loading: false, epoch: 0};
  }
  function restoreSource(id, name, entry) {
    const result = source(id, name);
    ["name", "file", "sheet", "header_row", "mapping", "defaults"].forEach(function (key) {
      if (entry && entry[key] !== undefined) result[key] = typeof entry[key] === "object" && entry[key] !== null ? JSON.parse(JSON.stringify(entry[key])) : entry[key];
    });
    return result;
  }
  function fileCard(host, item, options) {
    const opts = options || {};
    function changed() { if (opts.changed) opts.changed(); }
    function render() {
      const disabled = item.loading;
      const fileInput = el("input", {type: "file", id: item.id + "-file", accept: ".csv,.xlsx", disabled: disabled, onchange: function (event) { if (event.target.files[0]) readFile(event.target.files[0]); }});
      const body = el("div", {className: "source-body"}, [
          el("div", {className: "file-control"}, [
            el("span", {className: "file-symbol", "aria-hidden": "true"}, "▤"),
            el("div", {}, [el("span", {className: "file-name"}, item.file ? item.file.name : "选择 CSV 或 Excel 文件"), el("span", {className: "file-detail"}, "不超过 10 MiB · 原文件保持不变")]),
            el("label", {className: "button file-choose", for: item.id + "-file"}, [item.file ? "更换文件" : "选择文件", fileInput])
          ])
      ]);
      if (item.file) {
        const isCsv = /\.csv$/i.test(item.file.name);
        const options = el("details", {className: "table-options", id: item.id + "-table-options", open: Boolean(item.error || (!isCsv && !item.sheet))}, [
          el("summary", {}, isCsv ? "表头不在第 1 行？调整读取位置" : "工作表与表头 · " + (item.sheet || "请选择工作表") + " · 第 " + item.header_row + " 行"),
          el("div", {className: "form-grid"}, [
          el("div", {hidden: isCsv}, field("工作表", select([{value: "", label: "选择工作表"}].concat(item.sheets), item.sheet, function (event) {
            item.sheet = event.target.value || null; item.headers = []; item.preview = []; changed(); inspect();
          }, {id: item.id + "-sheet", disabled: disabled || isCsv}))),
          field("表头所在行", el("input", {id: item.id + "-header-row", type: "number", min: 1, step: 1, value: item.header_row, disabled: disabled,
            oninput: function (event) { item.header_row = Number(event.target.value); item.error = "请重新读取当前表头。"; item.headers = []; changed(); },
            onchange: function () { inspect(); }}))
          ]), button("重新读取表头 ↻", inspect, {className: "text-button", disabled: disabled})
        ]);
        body.appendChild(options);
      }
      if (item.loading) body.appendChild(el("p", {className: "source-status loading", role: "status"}, "正在读取所选表格…"));
      if (item.error) body.appendChild(el("p", {className: "source-status error", role: "status"}, item.error));
      if (opts.mapping && item.headers.length) {
        body.appendChild(el("p", {className: "mapping-suggestion"}, "已按列名建议字段，请对照预览确认；建议不代表已核实含义。"));
        body.appendChild(opts.mapping(item, disabled));
      }
      if (item.headers.length || item.preview.length) body.appendChild(el("details", {className: "extension-preview", open: true}, [
        el("summary", {}, "查看前 5 行 · 共 " + text(item.row_count) + " 个非空行"),
        table(item.headers, item.preview.slice(0, 5).map(function (row) { return el("tr", {}, row.map(function (value) { return cell(value); })); }))
      ]));
      host.replaceChildren(el("article", {className: "source-card", "aria-label": item.name}, [
        el("div", {className: "source-head"}, [
          el("div", {className: "source-heading"}, [el("span", {className: "source-letter"}, opts.letter || "F"), el("div", {}, [el("h3", {}, item.name), opts.caption ? el("span", {className: "role-caption"}, opts.caption) : null])]),
          badge(item.loading ? "读取中…" : item.error ? "请检查" : item.headers.length ? text(item.row_count) + " 行" : "等待选择", item.error ? "warning" : item.headers.length ? "success" : "")
        ]), body
      ]));
      if (opts.updated) opts.updated();
    }
    async function inspect(propagateAbort = false) {
      if (!item.file || !Number.isInteger(item.header_row) || item.header_row < 1) { item.error = "表头行号须为正整数。"; render(); return; }
      item.epoch += 1; const epoch = item.epoch; item.loading = true; item.error = ""; changed(); render();
      try {
        const data = await api("/api/inspect", {file: item.file, sheet: item.sheet, header_row: item.header_row});
        if (epoch !== item.epoch) return;
        item.sheets = data.sheets || []; item.headers = data.headers || []; item.preview = data.preview || [];
        item.row_count = data.row_count; item.error = data.error || ""; item.sheet = data.sheet || item.sheet;
        if (opts.inspected) opts.inspected(item);
      } catch (error) { if (epoch === item.epoch) { item.error = error.message; item.headers = []; item.preview = []; } if (propagateAbort === true && error.name === "AbortError") throw error; }
      finally { if (epoch === item.epoch) { item.loading = false; render(); } }
    }
    async function readFile(file) {
      if (!/\.(csv|xlsx)$/i.test(file.name)) { message("请选择 UTF-8 CSV 或 .xlsx 文件。", true); return; }
      if (file.size > 10 * 1024 * 1024) { message(file.name + " exceeds 10 MiB. Choose a smaller values-only extract.", true); return; }
      clearMessages(); item.epoch += 1; const epoch = item.epoch;
      item.file = null; item.sheet = null; item.sheets = []; item.headers = []; item.preview = []; item.error = ""; item.loading = true;
      if (opts.reset) opts.reset(item);
      changed(); render();
      try {
        const encoded = await new Promise(function (resolve, reject) {
          const reader = new FileReader();
          reader.onload = function () { resolve(String(reader.result).split(",")[1]); };
          reader.onerror = function () { reject(new Error("The selected file could not be read. Choose it again.")); };
          reader.readAsDataURL(file);
        });
        if (epoch !== item.epoch) return;
        item.file = {name: file.name, content_base64: encoded}; await inspect();
      } catch (error) { if (epoch === item.epoch) { item.loading = false; item.error = error.message; render(); } }
    }
    render();
    return {render: render, inspect: inspect};
  }
  function columns(item, emptyLabel) { return [{value: "", label: emptyLabel || "选择列"}].concat(item.headers); }
  function setupFlow(options) {
    const form = document.getElementById(options.formId);
    const next = document.getElementById("setup-next"), back = document.getElementById("setup-back");
    const fileStep = document.getElementById("setup-files"), settingsStep = document.getElementById("setup-settings");
    let current = "files", locked = false;
    function show(step, scroll) {
      current = step;
      form.querySelectorAll("[data-input-panel]").forEach(function (panel) { panel.hidden = panel.dataset.inputPanel !== step; });
      [[fileStep, "files"], [settingsStep, "settings"]].forEach(function (pair) {
        pair[0].classList.toggle("active", pair[1] === step);
        if (pair[1] === step) pair[0].setAttribute("aria-current", "step");
        else pair[0].removeAttribute("aria-current");
      });
      const summary = document.getElementById("setup-summary");
      if (summary && options.summary) summary.textContent = options.summary();
      if (scroll) {
        document.getElementById("input-progress").scrollIntoView({behavior: "smooth", block: "start"});
        const heading = form.querySelector('[data-input-panel="' + step + '"] h2');
        if (heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}); }
      }
    }
    function advance() {
      if (locked) return;
      clearMessages();
      try { options.validateFiles(); show("settings", true); }
      catch (error) { message(error.message, true); }
    }
    next.addEventListener("click", advance);
    settingsStep.addEventListener("click", advance);
    [back, fileStep].forEach(function (control) { control.addEventListener("click", function () { if (!locked) show("files", true); }); });
    show("files", false);
    return {show: show, next: advance, current: function () { return current; }, update: function (busy) {
      locked = Boolean(busy);
      [next, back, fileStep, settingsStep].forEach(function (control) { control.disabled = locked; });
      const summary = document.getElementById("setup-summary");
      if (summary && options.summary) summary.textContent = options.summary();
    }};
  }
  function requireSource(item) {
    if (!item.file) throw new Error("请先选择文件：" + item.name + ".");
    if (item.loading) throw new Error("请等待 " + item.name + " 读取完成。");
    if (item.error) throw new Error(item.name + ": " + item.error);
    if (!item.headers.length) throw new Error("请确认工作表和表头行：" + item.name + ".");
  }
  function pagedTable(host, rows, columnsSpec, options) {
    const opts = options || {}; let page = 0, query = "", pageSize = 25;
    const search = el("input", {className: "search-input", type: "search", placeholder: opts.searchLabel || "搜索记录", "aria-label": opts.searchLabel || "搜索记录"});
    const count = el("span");
    const output = el("div");
    const previous = button("上一页", function () { page -= 1; render(); });
    const next = button("下一页", function () { page += 1; render(); });
    const pageLabel = el("span");
    search.addEventListener("input", function () { query = search.value.toLowerCase(); page = 0; render(); });
    host.replaceChildren(el("div", {className: "extension-table-controls"}, [search, count]), output,
      el("div", {className: "pagination"}, [pageLabel, el("div", {className: "pagination-controls"}, [previous, next])]));
    function render() {
      const filtered = query ? rows.filter(function (row) { return JSON.stringify(row).toLowerCase().includes(query); }) : rows;
      const pages = Math.max(1, Math.ceil(filtered.length / pageSize)); page = Math.max(0, Math.min(page, pages - 1));
      output.replaceChildren(table(columnsSpec.map(function (spec) { return spec.label; }), filtered.slice(page * pageSize, (page + 1) * pageSize).map(function (row, index) {
        return el("tr", {}, columnsSpec.map(function (spec) { return spec.render ? spec.render(row, page * pageSize + index) : cell(row[spec.key], spec.numeric); }));
      })));
      count.textContent = filtered.length + " of " + rows.length + " rows";
      pageLabel.textContent = "Page " + (page + 1) + " of " + pages;
      previous.disabled = page === 0; next.disabled = page >= pages - 1;
    }
    render();
  }
  window.WorkbenchUI = {transport: transport, el: el, button: button, field: field, select: select, text: text, number: number, cell: cell, table: table, stat: stat, badge: badge,
    clearMessages: clearMessages, message: message, api: api, download: download, source: source, restoreSource: restoreSource, fileCard: fileCard, columns: columns, requireSource: requireSource, pagedTable: pagedTable, setupFlow: setupFlow};
})();
