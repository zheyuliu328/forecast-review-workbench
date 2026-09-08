"""Selected file snapshots -> public producer -> reviewable, source-bound results."""

import hashlib
import math
from datetime import datetime, time
from importlib.metadata import version
from pathlib import Path

from . import __version__
from ._vendor import forecast_engine
from .engine import _number, _period
from .example import _file
from .reconciliation import digest
from .tableio import read_table


def normalize_experiment(request):
    if not isinstance(request, dict) or type(request.get("schema_version")) is not int:
        raise ValueError("Use experiment schema_version 1.")
    if request["schema_version"] != 1:
        raise ValueError("Use experiment schema_version 1.")
    file = request.get("file")
    if not isinstance(file, dict) or "path" in file:
        raise ValueError("Select a local file; server file paths are not accepted.")
    table = read_table(file, request.get("sheet"), request.get("header_row", 1))
    mapping, spec = request.get("mapping"), request.get("spec")
    if not isinstance(mapping, dict) or not isinstance(spec, dict):
        raise ValueError("Declare column mappings and experiment settings.")
    features = mapping.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= 5:
        raise ValueError("Select one to five feature columns.")
    if any(not isinstance(feature, dict) for feature in features):
        raise ValueError("Each feature must declare its column, lag and release delay.")
    columns = [mapping.get("date"), mapping.get("target"), *(f.get("column") for f in features)]
    if any(not isinstance(column, str) or column not in table["headers"] for column in columns):
        raise ValueError("Every mapped column must exist in the selected header row.")
    if len(set(columns)) != len(columns):
        raise ValueError("Date, target and features must use distinct columns.")
    definitions = [
        {
            "id": f"f{i + 1}",
            "name": f.get("name", f["column"]),
            "lag": f.get("lag"),
            "release_delay": f.get("release_delay", 0),
        }
        for i, f in enumerate(features)
    ]
    rows, mapped_rows = [], []
    for entry in table["rows"]:
        cells = [entry["cells"][column] for column in columns]
        if any(cell["kind"] in {"formula", "error", "boolean"} for cell in cells):
            raise ValueError(f"Row {entry['row']}: selected formulas, Excel errors and booleans are invalid.")
        date_cell = cells[0]
        if date_cell["kind"] == "date" and "T" in date_cell["text"]:
            stamp = datetime.fromisoformat(date_cell["text"])
            if stamp.time() != time(0) or stamp.tzinfo is not None:
                raise ValueError(f"Row {entry['row']}: use monthly dates without intraday timestamps.")
        period = _period(date_cell["text"], "monthly", excel_date=date_cell["kind"] == "date")

        def number(cell, missing=False):
            if missing and not cell["text"].strip():
                return None
            value = float(_number(cell["text"]))
            if not math.isfinite(value):
                raise ValueError(f"Row {entry['row']}: numbers must be finite.")
            return value

        rows.append(
            {
                "period": period,
                "target": number(cells[1]),
                "features": {f"f{i + 1}": number(cell, True) for i, cell in enumerate(cells[2:])},
            }
        )
        mapped_rows.append(
            {
                "row": entry["row"],
                "period": period,
                "raw": {column: cell["text"] for column, cell in zip(columns, cells)},
            }
        )
    normalized = {
        "schema_version": 1,
        "title": request.get("title", "Monthly candidate experiment"),
        "rows": rows,
        "features": definitions,
        "horizon": spec.get("horizon", 1),
        "development_end": spec.get("development_end"),
        "n_splits": spec.get("n_splits", 3),
        "validation_months": spec.get("validation_months", 12),
        "min_train": spec.get("min_train", 36),
        "target": spec.get("target"),
        "source_note": request.get("source_note", ""),
    }
    source = {key: table[key] for key in ("file_name", "sha256", "sheet", "header_row", "blank_rows_ignored")}
    source.update({"rows": len(rows), "mapping": mapping, "source_note": normalized["source_note"]})
    return normalized, source, mapped_rows


def experiment_result(request, *, reveal=False):
    normalized, source, mapped_rows = normalize_experiment(request)
    result = forecast_engine.run_experiment(normalized, reveal_holdout=reveal)
    kernel_hash = hashlib.sha256(Path(forecast_engine.__file__).read_bytes()).hexdigest()
    result["producer"] = {
        "name": "model-risk-lab monthly OLS kernel",
        "sha256": kernel_hash,
        "numpy_version": version("numpy"),
    }
    result["source"] = source
    result["source_rows"] = mapped_rows
    by_period = {row["period"]: row for row in mapped_rows}
    for row in result["input_rows"]:
        row.update({"row": by_period[row["period"]]["row"], "raw": by_period[row["period"]]["raw"]})
    result["fingerprint"] = digest(
        {
            "version": __version__,
            "kernel": kernel_hash,
            "numpy_version": result["producer"]["numpy_version"],
            "data": result["data_fingerprint"],
            "source": source,
            "stage": result["stage"],
        }
    )
    fold_cutoffs = {(fold["model_id"], fold["fold"]): fold["training_cutoff"] for fold in result["folds"]}
    predictions = []
    for row in result["predictions"]:
        month = int(row["period"][:4]) * 12 + int(row["period"][5:]) - 1 - normalized["horizon"]
        origin = f"{month // 12:04d}-{month % 12 + 1:02d}"
        for model_id, value in row["predictions"].items():
            predictions.append(
                {
                    "period": row["period"],
                    "actual": row["actual"],
                    "split": row["split"],
                    "fold": row["fold"],
                    "model_id": model_id,
                    "prediction": value,
                    "residual": value - row["actual"],
                    "origin": origin,
                    "training_cutoff": fold_cutoffs[(model_id, row["fold"])]
                    if row["fold"] is not None
                    else result["protocol"]["final_training_cutoff"],
                }
            )
    result["predictions"] = predictions
    return result


def check_fingerprint(result, expected):
    if not isinstance(expected, str) or expected != result["fingerprint"]:
        raise ValueError("Files, settings or stage changed. Run this stage again before continuing.")


def reveal_experiment(request, fingerprint):
    check_fingerprint(experiment_result(request), fingerprint)
    return experiment_result(request, reveal=True)


def transfer_experiment(request, fingerprint, model_ids, baseline_id):
    result = experiment_result(request, reveal=True)
    check_fingerprint(result, fingerprint)
    if (
        not isinstance(model_ids, list)
        or not 1 <= len(model_ids) <= 5
        or any(not isinstance(value, str) for value in model_ids)
        or len(set(model_ids)) != len(model_ids)
    ):
        raise ValueError("Transfer one to five distinct successful candidates.")
    candidates = {model["id"]: model for model in result["candidates"]}
    for identifier in [*model_ids, baseline_id]:
        model = candidates.get(identifier) if isinstance(identifier, str) else None
        role = "baseline" if identifier == baseline_id else "candidate"
        if model is None or model["role"] != role or model["status"] != "ok" or not model["holdout"]:
            raise ValueError("Transfer requires successful holdout predictions for each selected role.")
    if baseline_id in model_ids:
        raise ValueError("Select OLS models as candidates and one separate baseline.")
    normalized, _source, _rows = normalize_experiment(request)
    actual_rows = [row for row in normalized["rows"] if row["period"] > normalized["development_end"]]
    actual_rows.sort(key=lambda row: row["period"])
    declaration = {
        "target": normalized["target"]["name"],
        "unit": normalized["target"]["unit"],
        "transformation": normalized["target"]["transformation"],
        "horizon": normalized["horizon"],
        "frequency": "monthly",
    }
    provenance = (
        f"Generated locally by monthly-ols-v1; experiment {result['fingerprint']}; "
        f"development selection {result['selection_fingerprint']}; transfer subset only. "
        f"Preselected OLS on development: {result['selected_on_development']}. "
        "All candidates and failures remain in the experiment bundle."
    )

    def source(name, rows):
        return {
            "file": _file(name, ["Month", "Value"], rows),
            "sheet": None,
            "header_row": 1,
            "mapping": {"date": "Month", "value": "Value", "entity": None},
            "contract": dict(declaration),
            "source_note": provenance,
        }

    def predicted(identifier):
        source_result = source(
            f"{identifier}.csv",
            [
                (p["period"], p["prediction"])
                for p in result["predictions"]
                if p["split"] == "holdout" and p["model_id"] == identifier
            ],
        )
        label = (
            "comparison baseline"
            if identifier == baseline_id
            else "preselected on development"
            if identifier == result["selected_on_development"]
            else "alternative comparison selected for transfer after holdout reveal; exploratory"
        )
        source_result["source_note"] += f" Transferred model: {identifier}; {label}."
        return {
            "id": identifier,
            "name": candidates[identifier]["name"],
            **source_result,
        }

    return {
        "schema_version": 1,
        "title": f"{result['title'][:150]} — holdout review",
        "scope": {
            "start": actual_rows[0]["period"],
            "end": actual_rows[-1]["period"],
            "frequency": "monthly",
            "entities": [],
        },
        "contract": {key: value for key, value in declaration.items() if key != "frequency"},
        "actual": source("holdout-actual.csv", [(row["period"], row["target"]) for row in actual_rows]),
        "candidates": [predicted(identifier) for identifier in model_ids],
        "baseline": predicted(baseline_id),
        "accept_common_sample": False,
        "segments": [],
    }


def experiment_example():
    normalized = forecast_engine.example_request()
    features = normalized["features"]
    columns = [feature["name"] for feature in features]
    file = _file(
        "invented-monthly-observations.csv",
        ["Month", "Observed", *columns],
        [
            (row["period"], row["target"], *(row["features"][f["id"]] for f in features))
            for row in normalized["rows"]
        ],
    )
    return {
        "schema_version": 1,
        "title": normalized["title"],
        "file": file,
        "sheet": None,
        "header_row": 1,
        "mapping": {
            "date": "Month",
            "target": "Observed",
            "features": [
                {"column": f["name"], "name": f["name"], "lag": f["lag"], "release_delay": f["release_delay"]}
                for f in features
            ],
        },
        "spec": {
            key: normalized[key]
            for key in ("horizon", "development_end", "n_splits", "validation_months", "min_train", "target")
        },
        "source_note": normalized["source_note"],
    }
