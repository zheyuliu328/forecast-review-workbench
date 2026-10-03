"""Portable evidence for a supplied-probability review; no fitting or calibration."""

import hashlib
import json
from pathlib import Path

from .exporter import _csv, _json
from .probabilities import render, review_probabilities


def build_probability_bundle(request, fingerprint=None):
    result = review_probabilities(request)
    if fingerprint is not None and fingerprint != result["fingerprint"]:
        raise ValueError("Inputs or settings changed. Review and accept the new common sample before export.")
    files = {
        "request.json": _json(request),
        "results.json": _json(result),
        "report.html": render(result).encode(),
        "evaluation-rows.csv": _csv(
            ["origin", "entity", "eligible_common", "source_states"],
            [
                [r["origin"], r["entity"], r["included"], json.dumps(r["states"])]
                for r in result["evaluation_rows"]
            ],
        ),
        "input-rows.csv": _csv(
            ["source", "row", "status", "key", "value", "reason", "raw"],
            [
                [
                    r["source"],
                    r["row"],
                    r["status"],
                    json.dumps(r["key"]),
                    r.get("value"),
                    r.get("reason", ""),
                    json.dumps(r["raw"]),
                ]
                for r in result["input_rows"]
            ],
            numeric_columns=(1, 4),
        ),
    }
    files["manifest.json"] = _json(
        {
            "task": "binary_event_review",
            "schema_version": 1,
            "fingerprint": result["fingerprint"],
            "files_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
            "source_code_sha256": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in [
                    "probabilities.py",
                    "probability_exports.py",
                    "exporter.py",
                    "engine.py",
                    "tableio.py",
                ]
            },
        }
    )
    return files, result
