"use strict";
(() => {
  let worker = null, serial = 0;
  const pending = new Map();
  const actions = new Set(["/api/example", "/api/experiments/example", "/api/reconcile/example", "/api/inspect", "/api/review", "/api/experiments/prepare", "/api/experiments/reveal", "/api/experiments/transfer", "/api/reconcile"]);
  const exports = new Set(["/api/export", "/api/experiments/export", "/api/reconcile/export"]);
  function notify(active, message = "") {
    const host = document.getElementById("runtime-status");
    if (host) { host.hidden = !active; host.querySelector("span").textContent = message; }
  }
  function cancel(message = "已取消。你可以重新读取文件或再次运行。") {
    if (worker) worker.terminate();
    worker = null;
    for (const item of pending.values()) { clearTimeout(item.timer); const error = new Error(message); error.name = "AbortError"; item.reject(error); }
    pending.clear(); notify(false);
  }
  function ensureWorker() {
    if (worker) return;
    if (!window.Worker || !window.WebAssembly || !window.crypto?.subtle) throw new Error("请使用较新的 Safari、Chrome、Edge 或 Firefox，以在浏览器内处理文件。");
    worker = new Worker("/worker.mjs", {type: "module", name: "forecast-review-local"});
    const current = worker;
    worker.onmessage = ({data}) => {
      if (worker !== current) return;
      if (data.type === "progress") { notify(true, data.message); return; }
      const item = pending.get(data.id);
      if (!item) return;
      pending.delete(data.id); clearTimeout(item.timer);
      if (!pending.size) notify(false);
      if (data.error) item.reject(new Error(data.error));
      else item.resolve(data.bytes ? new Blob([data.bytes], {type:"application/zip"}) : data.result);
    };
    worker.onerror = () => { if (worker === current) cancel("计算组件未能运行，请重新尝试或选择较小的文件。"); };
  }
  function call(action, payload, download) {
    return new Promise((resolve, reject) => {
      const raw = JSON.stringify(payload ?? {});
      if (new TextEncoder().encode(raw).byteLength > 40 * 1024 * 1024) { reject(new Error("所选文件合计过大，请缩小数据范围（请求上限 40 MiB）。")); return; }
      try { ensureWorker(); } catch (error) { reject(error); return; }
      const id = ++serial;
      const timer = setTimeout(() => cancel("本次处理超过 2 分钟，已停止。请缩小数据范围后重试。"), 120000);
      pending.set(id, {resolve, reject, timer});
      notify(true, "正在准备处理…"); worker.postMessage({id, action, raw, download});
    });
  }
  window.FrwBrowser = {
    request(action, payload) { return actions.has(action) ? call(action, payload, false) : Promise.reject(new Error("未支持的操作。")); },
    download(action, payload) { return exports.has(action) ? call(action, payload, true) : Promise.reject(new Error("未支持的下载。")); },
    cancel: () => cancel(),
  };
  window.addEventListener("pagehide", () => cancel("页面已关闭。"));
  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("runtime-cancel")?.addEventListener("click", () => cancel());
    // A small read-only tool exposes the same visible workflow state; never input bytes.
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tool = {name:"read_review_stage", title:"查看复核进度", description:"Read the visible review stage and notices without reading selected files or changing the review.", inputSchema:{type:"object",properties:{},additionalProperties:false}, annotations:{readOnlyHint:true,untrustedContentHint:true}, execute(input) {
      if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).length) throw new Error("此操作不接受参数。");
      const heading = [...document.querySelectorAll("h1,h2")].filter(el => el.getClientRects().length).map(el => el.textContent);
      return {page: location.pathname, headings: heading, processing: pending.size > 0};
    }};
    try { Promise.resolve(context.registerTool(tool, {signal:lifecycle.signal})).catch(() => {}); } catch (_) {}
    window.addEventListener("pagehide", () => lifecycle.abort(), {once:true});
  });
})();
