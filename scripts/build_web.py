"""Build only allowlisted public assets, with all runtime dependencies self-hosted."""

import hashlib
import io
import json
import shutil
import urllib.request
from pathlib import Path
from tempfile import gettempdir
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "out"
PACKAGE = ROOT / "src/forecast_review_workbench"
RUNTIME = ROOT / "node_modules/pyodide"
PYODIDE_VERSION = "314.0.6"
STATIC = ["app.js", "extension-common.js", "experiments.js", "reconcile.js", "styles.css", "extensions.css"]
PAGES = {
    "index.html": "index.html",
    "experiments/index.html": "experiments.html",
    "reconcile/index.html": "reconcile.html",
}
PACKAGE_FILES = [
    "__init__.py",
    "engine.py",
    "example.py",
    "experiments.py",
    "exporter.py",
    "reconciliation.py",
    "tableio.py",
    "workflow_exports.py",
    "report.html.template",
    "_vendor/__init__.py",
    "_vendor/forecast_engine.py",
    "_vendor/provenance.json",
    "_vendor/MODEL_RISK_LAB_LICENSE.txt",
]
RUNTIME_FILES = [
    "pyodide.mjs",
    "pyodide.asm.mjs",
    "pyodide.asm.wasm",
    "python_stdlib.zip",
    "pyodide-lock.json",
]


def sha(content):
    return hashlib.sha256(content).hexdigest()


def download(url, filename, digest):
    cache = Path(gettempdir()) / "frw-web-wheels"
    cache.mkdir(exist_ok=True)
    target = cache / filename
    if not target.exists() or sha(target.read_bytes()) != digest:
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()
        if sha(content) != digest:
            raise ValueError(f"Dependency hash mismatch: {filename}")
        target.write_bytes(content)
    shutil.copyfile(target, OUTPUT / "runtime" / filename)
    return target


def build():
    if json.loads((RUNTIME / "package.json").read_text())["version"] != PYODIDE_VERSION:
        raise ValueError("Run npm ci to install the pinned browser runtime.")
    wheels = json.loads((ROOT / "web/wheels.lock.json").read_text())
    numpy = json.loads((RUNTIME / "pyodide-lock.json").read_text())["packages"]["numpy"]
    allowed = set(PAGES) | {
        "tools.html",
        "browser.js",
        "worker.mjs",
        "engine.zip",
        "browser-build.json",
        "THIRD_PARTY_NOTICES.txt",
        "LICENSE",
    }
    allowed.update("static/" + name for name in STATIC)
    allowed.update("runtime/" + name for name in RUNTIME_FILES)
    allowed.update("runtime/" + wheel["filename"] for wheel in wheels)
    allowed.add("runtime/" + numpy["file_name"])
    if OUTPUT.is_symlink():
        raise ValueError("Build output cannot be a symlink.")
    for path in OUTPUT.rglob("*"):
        if path.is_symlink() or (path.is_file() and str(path.relative_to(OUTPUT)) not in allowed):
            raise ValueError(f"Unexpected output; refusing to package: {path}")
    for name in ("static", "runtime", "experiments", "reconcile"):
        (OUTPUT / name).mkdir(parents=True, exist_ok=True)
    for name in STATIC:
        shutil.copyfile(PACKAGE / "static" / name, OUTPUT / "static" / name)
    for destination, source in PAGES.items():
        html = (PACKAGE / "static" / source).read_text()
        html = html.replace(
            '<script src="/static/extension-common.js"',
            '<script src="/browser.js" defer></script>\n  <script src="/static/extension-common.js"',
        )
        html = html.replace("本机处理", "浏览器内处理")
        html = html.replace("<head>", '<head><meta name="frw-runtime" content="browser">')
        html = html.replace(
            '<meta name="color-scheme" content="light">',
            "<meta name=\"color-scheme\" content=\"light\">"
            "<meta name=\"referrer\" content=\"no-referrer\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'self'; "
            "script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
            "worker-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'self'; form-action 'none'\">",
        )
        html = html.replace(
            '<main id="main">',
            '<main id="main"><div id="runtime-status" class="runtime-status" role="status" '
            'aria-live="polite" hidden><span></span>'
            '<button id="runtime-cancel" class="button button-small" type="button">取消处理</button></div>',
        )
        html = html.replace(
            "</footer>",
            '<a href="/tools.html">全部工具与状态</a>'
            '<a href="/THIRD_PARTY_NOTICES.txt">开源许可</a></footer>',
        )
        (OUTPUT / destination).write_text(html)
    for name in ("browser.js", "worker.mjs", "tools.html", "THIRD_PARTY_NOTICES.txt"):
        shutil.copyfile(ROOT / "web" / name, OUTPUT / name)
    shutil.copyfile(ROOT / "LICENSE", OUTPUT / "LICENSE")
    for name in RUNTIME_FILES:
        shutil.copyfile(RUNTIME / name, OUTPUT / "runtime" / name)
    for wheel in wheels:
        download(wheel["url"], wheel["filename"], wheel["sha256"])
        wheel["path"] = "/runtime/" + wheel["filename"]
    numpy_path = download(
        "https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/" + numpy["file_name"],
        numpy["file_name"],
        numpy["sha256"],
    )
    with ZipFile(numpy_path) as archive:
        license_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/licenses/LICENSE.txt")
        )
        with (OUTPUT / "THIRD_PARTY_NOTICES.txt").open("ab") as output:
            output.write(b"\n\nNumPy 2.4.6 (Pyodide WASM distribution)\n" + archive.read(license_name))
    engine = io.BytesIO()
    with ZipFile(engine, "w", compression=ZIP_DEFLATED) as archive:
        sources = [(PACKAGE / name, "forecast_review_workbench/" + name) for name in PACKAGE_FILES]
        sources += [(ROOT / "web/browser-runtime.py", "browser_runtime.py")]
        for path, name in sources:
            if path.is_symlink():
                raise ValueError(f"Source cannot be a symlink: {path}")
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    (OUTPUT / "engine.zip").write_bytes(engine.getvalue())
    assets = {
        str(path.relative_to(OUTPUT)): {"sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file() and path.name != "browser-build.json"
    }
    metadata = {
        "schema_version": 1,
        "tool_version": "0.3.0",
        "pyodide_version": PYODIDE_VERSION,
        "numpy": numpy,
        "file_processing": "browser-local Worker; no input upload endpoint",
        "wheels": wheels,
        "assets": assets,
    }
    (OUTPUT / "browser-build.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "directory": str(OUTPUT),
                "files": len(assets) + 1,
                "bytes": sum(a["bytes"] for a in assets.values()),
            }
        )
    )


if __name__ == "__main__":
    build()
