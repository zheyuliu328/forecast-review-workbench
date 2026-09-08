"""Complete offline evidence for the two executable workflows."""

import hashlib
import html
from importlib.metadata import version

from . import __version__
from .experiments import check_fingerprint, experiment_result, normalize_experiment
from .exporter import _csv, _json, _table
from .reconciliation import DIMENSIONS, IDENTITY, reconcile


def _report(title, introduction, sections, files, fingerprint, warnings):
    escape = lambda text: html.escape(str(text), quote=True)  # noqa: E731
    links = "".join(f'<li><a href="{escape(name)}">{escape(name)}</a></li>' for name in files)
    body = "".join(f"<section><h2>{escape(name)}</h2>{content}</section>" for name, content in sections)
    warning_list = "".join(f"<li>{escape(warning)}</li>" for warning in warnings)
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'\">"
        f"<title>{escape(title)}</title><style>"
        "body{font:16px/1.55 system-ui,sans-serif;color:#182e3b;background:#f5f8fa;max-width:1200px;"
        "margin:0 auto;padding:32px}h1{font-size:clamp(26px,4vw,40px);line-height:1.2}"
        "h2{font-size:22px}section{background:white;border:1px solid #d8e2e8;border-radius:12px;"
        "padding:24px;margin:24px 0}.table-wrap{overflow:auto}table{border-collapse:collapse;"
        "width:100%;font-size:14px}td,th{padding:10px;text-align:left;border-bottom:1px solid #e5ecf0;"
        "vertical-align:top}th{background:#edf4f7}a{color:#165d79}code{overflow-wrap:anywhere}"
        ".preserve{white-space:pre-wrap}p,li{overflow-wrap:anywhere}@media(max-width:600px){"
        "body{padding:16px}section{padding:14px}}"
        f"</style><main><h1>{escape(title)}</h1><p>{escape(introduction)}</p>"
        f"<p>Result fingerprint: <code>{escape(fingerprint)}</code></p>{body}"
        f"<section><h2>Evidence files</h2><ul>{links}</ul></section>"
        f"<section><h2>Interpretation and limits</h2><ul>{warning_list}</ul></section></main></html>"
    ).encode()


def _finish(files, result, workflow):
    files["manifest.json"] = _json(
        {
            "schema_version": 1,
            "workflow": workflow,
            "tool_version": __version__,
            "fingerprint": result["fingerprint"],
            "dependencies": {package: version(package) for package in ("numpy", "openpyxl", "defusedxml")},
            "files": {
                name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
                for name, content in sorted(files.items())
            },
            "note": "Checksums detect changed evidence. They are not signatures or business approval.",
        }
    )
    return files, result


def _candidate_table(candidates, split):
    rows = []
    for model in candidates:
        metrics = model.get(split) or {}
        rows.append(
            [
                model["id"],
                model["name"],
                model["status"],
                metrics.get("n"),
                *(
                    None if metrics.get(key) is None else format(metrics[key], ".7g")
                    for key in ("mae", "rmse", "bias")
                ),
            ]
        )
    return _table(["Model ID", "Model", "Development status", "Common months", "MAE", "RMSE", "Bias"], rows)


def build_experiment_bundle(request, fingerprint, stage):
    if stage not in {"development", "holdout"}:
        raise ValueError("Choose the development or holdout stage explicitly.")
    result = experiment_result(request, reveal=stage == "holdout")
    check_fingerprint(result, fingerprint)
    normalized, _source, _rows = normalize_experiment(request)
    candidates = result["candidates"]
    headers = [
        "id",
        "name",
        "role",
        "status",
        "reason",
        "features",
        "development_n",
        "development_mae",
        "development_rmse",
        "development_bias",
        "holdout_n",
        "holdout_mae",
        "holdout_rmse",
        "holdout_bias",
        "holdout_reason",
    ]
    metrics = [
        [
            model["id"],
            model["name"],
            model["role"],
            model["status"],
            model["reason"],
            ";".join(model["features"]),
            *(
                (model.get(split) or {}).get(key)
                for split in ("development", "holdout")
                for key in ("n", "mae", "rmse", "bias")
            ),
            model.get("holdout_reason"),
        ]
        for model in candidates
    ]
    pred_headers = [
        "period",
        "split",
        "fold",
        "model_id",
        "actual",
        "prediction",
        "residual",
        "origin",
        "training_cutoff",
    ]
    folds = [
        [
            row["model_id"],
            row["fold"],
            row["status"],
            row["reason"],
            row["training_cutoff"],
            ";".join(row["train_periods"]),
            ";".join(row["validation_periods"]),
            *((row.get("development") or {}).get(key) for key in ("n", "mae", "rmse", "bias")),
        ]
        for row in result["folds"]
    ]
    selection = {
        key: result[key]
        for key in ("selected_on_development", "selection_fingerprint", "data_fingerprint", "fingerprint")
    }
    selection.update(
        {
            "stage": stage,
            "rule": result["protocol"]["selection_rule"],
            "development_end": result["protocol"]["development_end"],
            "ranking": result["protocol"]["ranking"],
            "producer": result["producer"],
            "all_candidates": [
                {key: row[key] for key in ("id", "role", "status", "reason", "development")}
                for row in candidates
            ],
        }
    )
    files = {
        "request.json": _json(request),
        "producer-request.json": _json(normalized),
        "results.json": _json(result),
        "selection-record.json": _json(selection),
        "candidates.csv": _csv(headers, metrics, numeric_columns=range(6, 14)),
        "predictions.csv": _csv(
            pred_headers, [[row[key] for key in pred_headers] for row in result["predictions"]], (2, 4, 5, 6)
        ),
        "folds.csv": _csv(
            [
                "model_id",
                "fold",
                "status",
                "reason",
                "training_cutoff",
                "train_periods",
                "validation_periods",
                "n",
                "mae",
                "rmse",
                "bias",
            ],
            folds,
            (1, 7, 8, 9, 10),
        ),
        "input-rows.json": _json(result["input_rows"]),
        "source-rows.json": _json(result["source_rows"]),
        "fit-diagnostics.json": _json(
            {"final": {row["id"]: row["fit"] for row in candidates}, "folds": result["folds"]}
        ),
    }
    protocol = _table(
        ["Setting", "Value"],
        [[key, value] for key, value in result["protocol"].items() if not isinstance(value, (dict, list))],
    )
    sections = [
        (
            "Selection fixed on development",
            _table(
                ["Selected OLS", "Development fingerprint", "Stage"],
                [[result["selected_on_development"], result["selection_fingerprint"], stage]],
            ),
        ),
        ("All candidates and baselines — development", _candidate_table(candidates, "development")),
        *(
            ([("All candidates and baselines — holdout", _candidate_table(candidates, "holdout"))])
            if stage == "holdout"
            else []
        ),
        (
            "Retained failures and unavailable scores",
            _table(
                ["Model", "Reason"],
                [
                    [model["id"], model["reason"] or model.get("holdout_reason")]
                    for model in candidates
                    if model["reason"] or model.get("holdout_reason")
                ],
            ),
        ),
        (
            "Sample accounting",
            _table(
                ["Scope", "Raw", "Usable", "Excluded"],
                [
                    [scope, *(result["coverage"][scope][key] for key in ("raw", "usable", "excluded"))]
                    for scope in ("development", "holdout")
                ],
            ),
        ),
        ("Protocol", protocol),
        (
            "Development folds",
            _table(
                ["Model", "Fold", "Status", "Reason", "Training cutoff", "N", "MAE"],
                [[*row[:5], row[7], row[8]] for row in folds],
            ),
        ),
        (
            "Prediction preview",
            f"<p>Showing {min(100, len(result['predictions']))} of "
            f"{len(result['predictions'])} model-month rows. predictions.csv contains every row.</p>"
            + _table(
                pred_headers, [[row[key] for key in pred_headers] for row in result["predictions"][:100]]
            ),
        ),
    ]
    warnings = [
        *result["protocol"]["disclosures"],
        "Raw input evidence includes all supplied observations, including holdout targets. "
        "The development stage hides holdout predictions and scores, not the caller's own input data.",
        "Transfers contain an explicitly selected subset. All attempted candidates remain here.",
        "HTML score tables round to seven significant digits; full calculated values remain in CSV and JSON.",
        "Input evidence is embedded for local reproduction; choose its recipients deliberately.",
    ]
    files["report.html"] = _report(
        result["title"],
        f"Monthly candidate experiment — {stage}. Baselines are comparisons; the selected candidate "
        "uses pooled development MAE only.",
        sections,
        [*files, "manifest.json"],
        result["fingerprint"],
        warnings,
    )
    return _finish(files, result, "monthly-candidate-experiment")


def reconciliation_notes(notes, result):
    if not isinstance(notes, list) or len(notes) > len(result["rows"]):
        raise ValueError("Supply at most one manual note per compared identity.")
    identifiers = {row["record_key"] for row in result["rows"]}
    checked, seen = [], set()
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError("Each note must contain an identity, decision, reason and fingerprint.")
        key, decision, text = note.get("record_key"), note.get("decision"), note.get("text", "")
        if not isinstance(key, str) or key not in identifiers or key in seen:
            raise ValueError("A note references an unknown or repeated identity.")
        if decision not in {"needs_evidence", "accepted_difference"}:
            raise ValueError("Choose needs_evidence or accepted_difference.")
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("Each manual decision requires a reason of at most 4,000 characters.")
        check_fingerprint(result, note.get("fingerprint"))
        checked.append(
            {
                "record_key": key,
                "decision": decision,
                "text": text,
                "fingerprint": result["fingerprint"],
                "origin": "manual caller opinion",
            }
        )
        seen.add(key)
    return checked


def build_reconciliation_bundle(request, fingerprint, notes=None):
    result = reconcile(request)
    check_fingerprint(result, fingerprint)
    checked_notes = reconciliation_notes([] if notes is None else notes, result)
    row_headers = [
        "record_key",
        *IDENTITY,
        "reference_currency",
        "challenger_currency",
        "reference_unit",
        "challenger_unit",
        "reference",
        "challenger",
        "difference",
        "absolute_difference",
        "allowed_difference",
        "status",
        "reasons",
        "left_source_rows",
        "right_source_rows",
    ]
    rows = [
        [
            row["record_key"],
            *(row["identity"][field] for field in IDENTITY),
            *(row[key] for key in row_headers[6:16]),
            "; ".join(row["reasons"]),
            ";".join(map(str, row["source_rows"]["left"])),
            ";".join(map(str, row["source_rows"]["right"])),
        ]
        for row in result["rows"]
    ]
    group_headers = [
        "group_key",
        *DIMENSIONS,
        "reference",
        "challenger",
        "reference_rows",
        "challenger_rows",
        "difference",
        "absolute_difference",
        "allowed_difference",
        "status",
        "offsetting_breaches",
        "reasons",
        "record_keys",
    ]
    groups = [
        [
            row["group_key"],
            *(row["dimensions"][key] for key in DIMENSIONS),
            *(row[key] for key in group_headers[7:16]),
            "; ".join(row["reasons"]),
            ";".join(row["record_keys"]),
        ]
        for row in result["groups"]
    ]
    total_headers = [
        "side",
        "group_key",
        *DIMENSIONS,
        "calculated",
        "reported",
        "difference",
        "absolute_difference",
        "allowed_difference",
        "status",
        "reasons",
        "source_rows",
    ]
    totals = [
        [
            row["side"],
            row["group_key"],
            *(row["dimensions"].get(key) for key in DIMENSIONS),
            *(row[key] for key in total_headers[8:14]),
            "; ".join(row["reasons"]),
            ";".join(map(str, row["source_rows"])),
        ]
        for row in result["reported_totals"]
    ]
    inputs = [
        [
            row["source_id"],
            row["row"],
            row["record_key"],
            row["group_key"],
            *(row["raw"].get(field) for field in (*IDENTITY, "currency", "unit", "value")),
            "; ".join(row["errors"]),
        ]
        for row in result["input_rows"]
    ]
    files = {
        "request.json": _json(request),
        "results.json": _json(result),
        "review-notes.json": _json(checked_notes),
        "row-differences.csv": _csv(row_headers, rows, range(10, 15)),
        "group-differences.csv": _csv(group_headers, groups, range(7, 14)),
        "reported-totals.csv": _csv(total_headers, totals, range(8, 13)),
        "input-rows.csv": _csv(
            [
                "source_id",
                "source_row",
                "record_key",
                "group_key",
                *IDENTITY,
                "currency",
                "unit",
                "raw_value",
                "errors",
            ],
            inputs,
        ),
        "input-rows.json": _json(result["input_rows"]),
        "sources.json": _json(result["sources"]),
    }
    sections = [
        (
            "Result accounting",
            _table(
                ["Count", "Value"],
                [[key.replace("_", " ").capitalize(), value] for key, value in result["summary"].items()],
            ),
        ),
        ("Tolerance contract", _table(["Setting", "Value"], list(result["tolerances"].items()))),
        (
            "Row comparisons",
            f"<p>Showing {min(len(rows), 200)} of {len(rows)} identities. "
            "row-differences.csv contains every identity; input-rows.csv accounts for every supplied row.</p>"
            + _table(
                [
                    "Record",
                    "Date / measure / risk / tenor",
                    "Reference",
                    "Reference currency / unit",
                    "Challenger",
                    "Challenger currency / unit",
                    "Difference",
                    "Allowed",
                    "Status",
                    "Reason",
                ],
                [
                    [
                        row[1],
                        " / ".join(str(value or "—") for value in row[2:6]),
                        row[10],
                        f"{row[6]} / {row[8]}",
                        row[11],
                        f"{row[7]} / {row[9]}",
                        row[12],
                        row[14],
                        row[15],
                        row[16],
                    ]
                    for row in rows[:200]
                ],
            ),
        ),
        (
            "Additive group comparisons",
            f"<p>Showing {min(len(groups), 200)} of {len(groups)} groups. "
            "All groups are in group-differences.csv.</p>"
            + _table(
                [
                    "Date / measure / risk / tenor / currency / unit",
                    "Reference",
                    "Challenger",
                    "Difference",
                    "Allowed",
                    "Status",
                    "Offsetting breaches",
                    "Reason",
                ],
                [
                    [
                        " / ".join(str(value or "—") for value in row[1:7]),
                        row[7],
                        row[8],
                        row[11],
                        row[13],
                        row[14],
                        row[15],
                        row[16],
                    ]
                    for row in groups[:200]
                ],
            ),
        ),
        (
            "Reported totals vs their own raw rows",
            f"<p>Showing {min(len(totals), 200)} of {len(totals)} groups. "
            "All checks are in reported-totals.csv.</p>"
            + _table(
                [
                    "Side",
                    "Date / measure / risk / tenor / currency / unit",
                    "Calculated",
                    "Reported",
                    "Difference",
                    "Allowed",
                    "Status",
                    "Reason",
                ],
                [
                    [
                        row[0],
                        " / ".join(str(value or "—") for value in row[2:8]),
                        row[8],
                        row[9],
                        row[10],
                        row[12],
                        row[13],
                        row[14],
                    ]
                    for row in totals[:200]
                ],
            ),
        ),
        (
            "Manual opinions — calculated statuses retained",
            _table(
                ["Identity", "Decision", "Reason"],
                [[note["record_key"], note["decision"], note["text"]] for note in checked_notes],
            ),
        ),
    ]
    files["report.html"] = _report(
        result["title"],
        "Row differences, additive groups and each side's reported totals are separate checks. "
        "Net agreement cannot clear a failing member row.",
        sections,
        [*files, "manifest.json"],
        result["fingerprint"],
        result["warnings"],
    )
    return _finish(files, result, "additive-result-reconciliation")
