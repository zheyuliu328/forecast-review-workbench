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
        raise ValueError("The selected files are too large in total. Use a smaller data extract (40 MiB request limit).")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("The request must be an object.")
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
            raise ValueError("Select a file in the browser; disk paths are not accepted.")
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
        raise ValueError("Unsupported operation.")
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
        raise ValueError("Unsupported download type.")
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
