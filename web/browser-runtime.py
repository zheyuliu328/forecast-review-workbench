"""Browser transport for the unchanged review, training and reconciliation engines."""

import hashlib
import json
from pathlib import Path

from forecast_review_workbench.engine import review
from forecast_review_workbench.example import example_request
from forecast_review_workbench.experiments import (
    experiment_example,
    experiment_result,
    reveal_experiment,
    transfer_experiment,
)
from forecast_review_workbench.exporter import build_bundle, bundle_zip
from forecast_review_workbench.reconciliation import reconcile, reconciliation_example
from forecast_review_workbench.tableio import inspect_table
from forecast_review_workbench.workflow_exports import (
    build_experiment_bundle,
    build_reconciliation_bundle,
)

MAX_REQUEST_BYTES = 40 * 1024 * 1024


def _payload(raw):
    if len(raw.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("本次所选文件合计过大，请使用较小的数据摘录（请求上限 40 MiB）。")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("请求必须是一个对象。")
    return value


def dispatch(action, raw):
    payload = _payload(raw)
    if action == "/api/example":
        result = example_request()
    elif action == "/api/experiments/example":
        result = experiment_example()
    elif action == "/api/reconcile/example":
        result = reconciliation_example()
    elif action == "/api/inspect":
        file = payload.get("file")
        if not isinstance(file, dict) or "path" in file:
            raise ValueError("请选择浏览器中的文件，不接受磁盘路径。")
        result = inspect_table(file, payload.get("sheet"), payload.get("header_row", 1))
    elif action == "/api/review":
        result = review(payload)
    elif action == "/api/experiments/prepare":
        result = experiment_result(payload)
    elif action == "/api/experiments/reveal":
        result = reveal_experiment(payload.get("request"), payload.get("fingerprint"))
    elif action == "/api/experiments/transfer":
        result = {
            "request": transfer_experiment(
                payload.get("request"),
                payload.get("fingerprint"),
                payload.get("model_ids"),
                payload.get("baseline_id"),
            )
        }
    elif action == "/api/reconcile":
        result = reconcile(payload)
    else:
        raise ValueError("未支持的操作。")
    return json.dumps(result, ensure_ascii=False, allow_nan=False)


def download(action, raw):
    payload = _payload(raw)
    if action == "/api/export":
        files, _ = build_bundle(payload.get("request"), payload.get("fingerprint"), payload.get("notes", []))
    elif action == "/api/experiments/export":
        files, _ = build_experiment_bundle(
            payload.get("request"), payload.get("fingerprint"), payload.get("stage")
        )
    elif action == "/api/reconcile/export":
        files, _ = build_reconciliation_bundle(
            payload.get("request"), payload.get("fingerprint"), payload.get("notes", [])
        )
    else:
        raise ValueError("未支持的下载类型。")
    runtime = Path("/app/browser-build.json").read_bytes()
    files["browser-build.json"] = runtime
    manifest = json.loads(files["manifest.json"])
    digest = hashlib.sha256(runtime).hexdigest()
    if "files_sha256" in manifest:
        manifest["files_sha256"]["browser-build.json"] = digest
    else:
        manifest["files"]["browser-build.json"] = {"sha256": digest, "bytes": len(runtime)}
    manifest["execution"] = "Browser-local Pyodide Worker; input files are not uploaded."
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    return bundle_zip(files)
