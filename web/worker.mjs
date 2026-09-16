import {loadPyodide} from "/runtime/pyodide.mjs";

let runtime;
let queue = Promise.resolve();
const progress = message => self.postMessage({type: "progress", message});
async function checkedAsset(path, expected) {
  const response = await fetch(new URL(path, self.location.origin));
  if (!response.ok) throw new Error("计算组件未能下载，请检查网络后重试。");
  const bytes = new Uint8Array(await response.arrayBuffer());
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  const actual = Array.from(digest, byte => byte.toString(16).padStart(2, "0")).join("");
  if (actual !== expected) throw new Error("计算组件版本不一致，请刷新网页后重试。");
  return bytes;
}
async function initialize() {
  progress("首次使用正在下载计算组件。文件仍留在此浏览器中…");
  const response = await fetch("/browser-build.json", {cache:"no-cache"});
  if (!response.ok) throw new Error("无法读取工具版本，请刷新后重试。");
  const build = await response.json();
  const py = await loadPyodide({indexURL:new URL("/runtime/", self.location.origin).href});
  // Native NumPy wheels require Pyodide's dynamic-library loader, not ZIP extraction.
  await py.loadPackage("numpy");
  const sitePackages = py.runPython("import site; site.getsitepackages()[0]");
  for (const wheel of build.wheels) {
    const bytes = await checkedAsset(wheel.path, wheel.sha256);
    py.unpackArchive(bytes, "zip", {extractDir:sitePackages});
  }
  const engine = await checkedAsset("/engine.zip", build.assets["engine.zip"].sha256);
  py.unpackArchive(engine, "zip", {extractDir:"/app"});
  py.FS.writeFile("/app/browser-build.json", JSON.stringify(build));
  py.runPython("import sys; sys.path.insert(0, '/app'); import browser_runtime");
  return py;
}
self.onmessage = ({data}) => {
  const {id, action, raw, download} = data;
  queue = queue.then(async () => {
    try {
      runtime ||= initialize().catch(error => { runtime = null; throw error; });
      const py = await runtime;
      progress(download ? "正在准备报告…" : "正在读取与计算…");
      const proxy = py.globals.get("browser_runtime");
      try {
        if (download) {
          const value = proxy.download(action, raw);
          let bytes;
          try { bytes = value.toJs(); } finally { value.destroy(); }
          self.postMessage({id, bytes}, [bytes.buffer]);
        } else {
          const result = JSON.parse(proxy.dispatch(action, raw));
          self.postMessage({id, result});
        }
      } finally { proxy.destroy(); }
    } catch (error) {
      const detail = String(error.message || error).trim().split("\n").at(-1).replace(/^(ValueError|OSError|RuntimeError|Error):\s*/, "");
      self.postMessage({id, error:detail || "未能完成，请检查所选文件。"});
    }
  });
};
