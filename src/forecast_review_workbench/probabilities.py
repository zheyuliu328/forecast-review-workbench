"""Frozen binary-event probability review with an explicit availability cutoff."""

import argparse
import base64
import copy
import hashlib
import html
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from .engine import _number, _reported, _text
from .tableio import MAX_BYTES, read_table


def _fields(obj, allowed, required, context):
    if not isinstance(obj, dict) or set(obj) - set(allowed) or set(required) - set(obj):
        raise ValueError(f"{context}: missing or unsupported fields.")


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use an ISO calendar date YYYY-MM-DD.")
    date.fromisoformat(value)
    return value


def _key(origin, entity):
    if not isinstance(entity, str) or len(entity) > 200:
        raise ValueError("Entity must be exact text of at most 200 characters; empty means one series.")
    return _day(origin), entity


def _score(pairs):
    if not pairs:
        return None
    with localcontext() as context:
        context.prec = 600
        squared, losses, impossible = Decimal(0), Decimal(0), 0
        for label, probability in pairs:
            squared += (probability - label) ** 2
            event_probability = probability if label == 1 else 1 - probability
            if event_probability == 0:
                impossible += 1
            else:
                losses -= event_probability.ln()
        return {
            "n": len(pairs),
            "brier": _reported(squared / len(pairs)),
            "log_loss": None if impossible else _reported(losses / len(pairs)),
            "log_loss_status": "infinite" if impossible else "finite",
            "impossible_events": impossible,
        }


def review_probabilities(request):
    """Do not infer an expected universe, refit, choose thresholds or clip probabilities."""
    _fields(
        request,
        [
            "task",
            "schema_version",
            "event_definition",
            "evaluation_as_of",
            "expected_keys",
            "labels",
            "candidates",
            "baseline",
            "accept_common_sample",
        ],
        [
            "task",
            "schema_version",
            "event_definition",
            "evaluation_as_of",
            "expected_keys",
            "labels",
            "candidates",
            "accept_common_sample",
        ],
        "request",
    )
    if (
        request["task"] != "binary_event_review"
        or type(request["schema_version"]) is not int
        or request["schema_version"] != 1
    ):
        raise ValueError("Use binary_event_review schema_version 1.")
    json.dumps(request, allow_nan=False)
    _text(request["event_definition"], "event_definition", 2000)
    event = request["event_definition"]
    cutoff = _day(request["evaluation_as_of"])
    if type(request["accept_common_sample"]) is not bool:
        raise ValueError("Common-sample acceptance must be an explicit boolean.")
    universe = request["expected_keys"]
    if not isinstance(universe, list) or not 1 <= len(universe) <= 5000:
        raise ValueError("Declare 1–5000 expected origin/entity keys independently of surviving rows.")
    keys = []
    for entry in universe:
        _fields(entry, ["origin", "entity"], ["origin", "entity"], "expected key")
        keys.append(_key(entry["origin"], entry["entity"]))
    universe_set = set(keys)
    if len(universe_set) != len(keys):
        raise ValueError("Expected keys must be unique.")
    candidates = request["candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 5:
        raise ValueError("Provide 1–5 candidates.")
    sources = [("labels", request["labels"])] + [("candidate", s) for s in candidates]
    if request.get("baseline") is not None:
        sources.append(("baseline", request["baseline"]))
    seen, parsed, metadata, records, contract_errors = set(), {}, [], [], []
    for role, source in sources:
        _fields(
            source,
            ["id", "file", "mapping", "event_definition", "source_note", "sheet", "header_row"],
            ["id", "file", "mapping", "event_definition", "source_note"],
            "source",
        )
        sid = source["id"]
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", sid) or sid in seen:
            raise ValueError("Source IDs must be unique: a letter followed by letters, digits, _ or -.")
        seen.add(sid)
        _text(source["source_note"], f"{sid}: source_note", 2000)
        if source["event_definition"] != event:
            contract_errors.append(f"{sid}: event definition differs from the common declaration.")
        required = (
            ["origin", "entity", "label", "available"]
            if role == "labels"
            else ["origin", "entity", "probability"]
        )
        mapping = source["mapping"]
        _fields(mapping, required, required, f"{sid}: mapping")
        columns = [v for v in mapping.values() if v is not None]
        if any(not isinstance(v, str) or not v for v in columns) or len(set(columns)) != len(columns):
            raise ValueError(f"{sid}: mapped columns must be distinct nonempty text.")
        if any(mapping[k] is None for k in required if k != "entity"):
            raise ValueError(f"{sid}: only the entity mapping may be null.")
        table = read_table(source["file"], source.get("sheet"), source.get("header_row", 1))
        if set(columns) - set(table["headers"]):
            raise ValueError(f"{sid}: mapped column is missing from {table['file_name']}.")
        metadata.append(
            {k: v for k, v in table.items() if k != "rows"}
            | {"id": sid, "role": role, "source_note": source["source_note"]}
        )
        grouped = defaultdict(list)
        for original in table["rows"]:
            record = {
                "source": sid,
                "row": original["row"],
                "raw": original["cells"],
                "status": "invalid",
                "key": None,
            }
            records.append(record)
            try:

                def cell(field):
                    column = mapping[field]
                    if column is None:
                        return ""
                    item = original["cells"][column]
                    if field == "entity" and (item["kind"] != "text" or not item["text"]):
                        raise ValueError(
                            "Mapped entity IDs must be nonempty exact text; no numeric/date coercion."
                        )
                    if item["kind"] in ("formula", "error", "boolean"):
                        raise ValueError(f"{field}: formulas, errors and booleans are not accepted.")
                    return item["text"][:10] if item["kind"] == "date" else item["text"]

                key = _key(cell("origin"), cell("entity"))
                record["key"] = list(key)
                grouped[key].append(record)
                if role == "labels":
                    available = _day(cell("available"))
                    if available <= key[0]:
                        raise ValueError(
                            "Label availability must be after origin; intraday tasks are unsupported."
                        )
                    record["available"] = available
                    label_text = cell("label")
                    label = None if available > cutoff and not label_text.strip() else _number(label_text)
                    if label is not None and label not in (0, 1):
                        raise ValueError("Label must be exactly 0 or 1.")
                    record["value"] = None if label is None else str(label)
                    record["status"] = "pending" if available > cutoff else "valid"
                else:
                    probability = _number(cell("probability"))
                    if not 0 <= probability <= 1:
                        raise ValueError("Probability must be in [0,1]; percentages are not inferred.")
                    record.update(value=str(probability), status="valid")
                if key not in universe_set:
                    record["status"] = "outside_scope"
                elif key[0] > cutoff:
                    record["status"] = "not_yet_issued"
            except (ValueError, TypeError) as exc:
                record["reason"] = str(exc)
        for members in grouped.values():
            if len(members) > 1:
                for record in members:
                    record["status"] = "duplicate"
                    record["reason"] = "All occurrences of this key are excluded."
        parsed[sid] = grouped
    label_id = metadata[0]["id"]
    evaluation, common = [], []
    for key in keys:
        states = {}
        for sid in parsed:
            members = parsed[sid].get(key, [])
            states[sid] = members[0]["status"] if len(members) == 1 else "duplicate" if members else "missing"
        included = all(state == "valid" for state in states.values()) and not contract_errors
        if included:
            common.append(key)
        evaluation.append({"origin": key[0], "entity": key[1], "included": included, "states": states})
    ready = request["accept_common_sample"] and bool(common) and not contract_errors
    metrics = {}
    for source in metadata[1:]:
        sid = source["id"]
        metrics[sid] = (
            _score(
                [
                    (Decimal(parsed[label_id][key][0]["value"]), Decimal(parsed[sid][key][0]["value"]))
                    for key in common
                ]
            )
            if ready
            else None
        )
    return {
        "task": "binary_event_review",
        "schema_version": 1,
        "event_definition": event,
        "evaluation_as_of": cutoff,
        "accepted_common_sample": request["accept_common_sample"],
        "comparison_ready": ready,
        "expected": len(keys),
        "common": len(common),
        "excluded": len(keys) - len(common),
        "contract_errors": contract_errors,
        "sources": metadata,
        "input_rows": records,
        "evaluation_rows": evaluation,
        "metrics": metrics,
        "fingerprint": hashlib.sha256(
            json.dumps(request, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "limits": [
            "Expected keys are caller-declared; this cannot detect omissions from that declaration.",
            "Availability dates and origins are declarations, not proof of historical vintage or issuance.",
            "Brier and log loss share one fixed sample; no fitting, calibration or threshold selection.",
            "Impossible 0/1 predictions give infinite log loss: null plus status/count, without clipping.",
            "Overlapping events are not independent trials. No significance, profit or model-approval claim.",
            "Calendar dates only; same-day/intraday availability is unsupported.",
        ],
    }


def render(result):
    def esc(value):
        return html.escape(str(value))

    def table(headers, rows):
        return (
            '<div class="scroll"><table><tr>'
            + "".join("<th>" + esc(h) + "</th>" for h in headers)
            + "</tr>"
            + "".join("<tr>" + "".join("<td>" + esc(v) + "</td>" for v in row) + "</tr>" for row in rows)
            + "</table></div>"
        )

    sources = "<h2>Sources</h2>" + table(
        ["ID / role", "File / sheet / header row", "Original SHA-256", "Source declaration"],
        [
            [
                s["id"] + " / " + s["role"],
                f"{s['file_name']} / {s['sheet'] or 'CSV'} / {s['header_row']}",
                s["sha256"],
                s["source_note"],
            ]
            for s in result["sources"]
        ],
    )
    failed_rows = [row for row in result["input_rows"] if row["status"] in ("invalid", "duplicate")]
    failures = (
        "<h2>Input rows needing correction</h2><p>"
        + str(len(failed_rows))
        + " invalid or duplicate rows. First 100 shown; row numbers refer to the original files. "
        "Pending, missing and out-of-scope rows are separate sample states, not necessarily errors.</p>"
        + table(
            ["Source", "File row", "Status", "Reason"],
            [[r["source"], r["row"], r["status"], r.get("reason", "")] for r in failed_rows[:100]],
        )
    )
    exclusions = [row for row in result["evaluation_rows"] if not row["included"]]
    exclusion_table = (
        "<h2>Excluded expected keys</h2><p>First 100 exclusions; all keys remain in results.json.</p>"
    )
    exclusion_table += (
        '<div class="scroll"><table><tr><th>Origin</th><th>Entity</th><th>Source states</th></tr>'
    )
    for row in exclusions[:100]:
        exclusion_table += "<tr><td>" + esc(row["origin"]) + "</td><td>" + esc(row["entity"]) + "</td><td>"
        exclusion_table += esc("; ".join(k + ": " + v for k, v in row["states"].items())) + "</td></tr>"
    exclusion_table += "</table></div>"
    conflicts = "<p>" + esc(" ".join(result["contract_errors"])) + "</p>"
    rows = "".join(
        "<tr>"
        + "".join(
            "<td>" + esc(value) + "</td>"
            for value in [
                sid,
                score["n"],
                score["brier"],
                "Infinite" if score["log_loss_status"] == "infinite" else score["log_loss"],
                score["log_loss_status"],
                score["impossible_events"],
            ]
        )
        + "</tr>"
        for sid, score in result["metrics"].items()
        if score
    )
    return (
        """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Binary event probability review</title>
<style>body{font:16px/1.6 system-ui;margin:30px auto;max-width:1100px;padding:20px;color:#243343}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd;overflow-wrap:anywhere}
.scroll{overflow:auto}
pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>
<h1>Binary event probability review</h1>
<p>"""
        + esc(result["event_definition"])
        + "</p><p>Evaluation cutoff: "
        + esc(result["evaluation_as_of"])
        + "; expected keys: "
        + str(result["expected"])
        + "; fixed common keys: "
        + str(result["common"])
        + "; excluded: "
        + str(result["excluded"])
        + ". Comparison ready: "
        + str(result["comparison_ready"])
        + """</p>
<p>Lower Brier/log loss is better. An infinite log loss is an impossible assigned event, not missing data.
If comparison is not ready, confirm the common sample
and resolve contract errors; no metrics are shown.</p>
<div class="scroll">
<table>
<tr>
<th>Source</th>
<th>n</th>
<th>Brier</th>
<th>Log loss</th>
<th>Log-loss status</th>
<th>Impossible events</th>
</tr>"""
        + rows
        + "</table></div>"
        + conflicts
        + "<h2>Calculation</h2><p>For each included key, y is the binary label and p is the "
        "probability assigned to y = 1. Brier = sum((p - y)^2) / n. Log loss = "
        "-sum(ln(q)) / n, where q = p when y = 1 and q = 1 - p when y = 0. "
        "Logarithms are natural; Brier is dimensionless and log loss is in nats per event. "
        "Every included key has equal weight; all scored sources use exactly the same keys.</p>"
        "<p>Only labels declared available on or before the cutoff can enter the sample. "
        "The expected key must have exactly one valid row in every source. "
        "Scores require accepted common-sample membership and matching event definitions. "
        "No probability clipping or endpoint removal is performed. "
        "Arithmetic uses 600 decimal digits before final 40-significant-digit reporting.</p>"
        + sources
        + exclusion_table
        + failures
        + "<h2>Limits</h2><ul>"
        + "".join("<li>" + esc(x) + "</li>" for x in result["limits"])
        + "</ul><details><summary>Complete inputs, row diagnostics and results</summary><pre>"
        + esc(json.dumps(result, indent=2, allow_nan=False))
        + "</pre></details>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output already exists; choose a new directory.")
        request = json.loads(args.input.read_text())
        request = copy.deepcopy(request)
        sources = [request["labels"], *request["candidates"]]
        if request.get("baseline") is not None:
            sources.append(request["baseline"])
        for source in sources:
            spec = source["file"]
            if isinstance(spec, dict) and "path" in spec:
                if set(spec) != {"path"}:
                    raise ValueError("A local file specification must contain only path.")
                path = args.input.parent / spec["path"]
                with path.open("rb") as f:
                    raw = f.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Source file exceeds 10 MiB.")
                source["file"] = {"name": path.name, "content_base64": base64.b64encode(raw).decode()}
        result = review_probabilities(request)
        report = render(result)
        args.output.mkdir(parents=True, exist_ok=False)
        for name, value in [("request.json", request), ("results.json", result)]:
            (args.output / name).write_text(
                json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
        (args.output / "report.html").write_text(report, encoding="utf-8")
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "comparison_ready": result["comparison_ready"],
                "common": result["common"],
            }
        )
    )


if __name__ == "__main__":
    main()
