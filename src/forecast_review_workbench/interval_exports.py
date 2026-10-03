"""Portable interval-review evidence; no fitting or uploaded files."""

import hashlib
import html
import json
from decimal import Decimal
from pathlib import Path

from .engine import _reported
from .exporter import _csv, _json
from .intervals import _row_score, review_intervals


def render(result):
    def esc(value):
        return html.escape(str(value))

    def table(headers, rows):
        return (
            '<div class="scroll"><table><tr>'
            + "".join("<th>" + esc(x) + "</th>" for x in headers)
            + "</tr>"
            + "".join("<tr>" + "".join("<td>" + esc(x) + "</td>" for x in row) + "</tr>" for row in rows)
            + "</table></div>"
        )

    columns = [
        "n",
        "empirical_interval_coverage",
        "mean_width",
        "mean_interval_score",
        "lower_misses",
        "upper_misses",
    ]
    scores = table(
        [
            "Candidate",
            "Common n",
            "Observed containment",
            "Mean width",
            "Mean interval score",
            "Lower misses",
            "Upper misses",
        ],
        [[sid] + [(m or {}).get(k, "Not scored") for k in columns] for sid, m in result["metrics"].items()],
    )
    groups = table(
        ["Entity", "Horizon days", "Expected", "Common", "Candidate", "Containment", "Width", "Score"],
        [
            [
                g["entity"] or "(single series)",
                g["horizon_days"],
                g["expected"],
                g["common"],
                sid,
                *[(m or {}).get(k, "Not scored") for k in columns[1:4]],
            ]
            for g in result["group_results"]
            for sid, m in g["metrics"].items()
        ],
    )
    exclusions = [r for r in result["evaluation_rows"] if not r["included"]]
    rows = table(
        ["Origin", "Target", "Entity", "Source status"],
        [[r["origin"], r["target"], r["entity"], json.dumps(r["states"])] for r in exclusions],
    )
    sources = table(
        ["ID", "File / sheet / header", "Original SHA-256", "Declaration"],
        [
            [
                s["id"],
                f"{s['file_name']} / {s['sheet'] or 'CSV'} / {s['header_row']}",
                s["sha256"],
                s["source_note"],
            ]
            for s in result["sources"]
        ],
    )
    errors = [r for r in result["input_rows"] if r["status"] != "valid"]
    diagnostics = table(
        ["Source", "Row", "Status", "Reason"],
        [[r["source"], r["row"], r["status"], r.get("reason", "")] for r in errors[:100]],
    )
    c = result["contract"]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>Prediction interval review</title>'
        "<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:32px auto;padding:20px;"
        "color:#23313d}.scroll{overflow:auto}table{border-collapse:collapse;width:100%}"
        "td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere}</style><h1>"
        + esc(result["title"])
        + "</h1><p>"
        + esc(c["target"])
        + " · "
        + esc(c["unit"])
        + " · "
        + esc(c["transformation"])
        + " · nominal central coverage "
        + esc(c["nominal_coverage"])
        + "</p><p>Expected keys: "
        + str(result["expected"])
        + "; eligible common keys: "
        + str(result["common"])
        + "; excluded: "
        + str(result["excluded"])
        + "; common sample explicitly accepted: "
        + str(result["accepted_common_sample"])
        + "; comparison ready: "
        + str(result["comparison_ready"])
        + ".</p><p>Data completeness and "
        "empirical interval coverage are different. All candidates use exactly the same accepted keys.</p>"
        "<h2>Interval comparison</h2>" + scores + "<p>Containment is a ratio; interval endpoints count as "
        "covered. Width and score use the target unit. Lower interval score is better, balancing width "
        "and missed outcomes. Narrower alone or higher containment alone is not a ranking rule.</p>"
        "<h2>Entity and horizon detail</h2>"
        + groups
        + "<h2>Excluded expected keys</h2>"
        + rows
        + "<p>Contract conflicts: "
        + esc("; ".join(result["contract_errors"]) or "None")
        + "</p>"
        "<h2>Input diagnostics</h2>" + diagnostics + "<p>First 100 non-valid rows shown; all raw rows and "
        "statuses are preserved in results.json and input-rows.csv.</p><h2>Method</h2>"
        "<p>Let alpha = 1 - nominal coverage. For actual y and bounds L, U: width = U - L; "
        "interval score = width + (2/alpha)*(L-y) if y&lt;L, or width + (2/alpha)*(y-U) if y&gt;U; "
        "otherwise the score is width. Reported means give every included forecast key equal weight. "
        "An actual reused by several forecast origins is not an independent outcome each time.</p>"
        "<h2>Sources</h2>" + sources + "<h2>Reproduce</h2><p>request.json contains the frozen original "
        "file bytes and declarations. Rerun it with the installed interval tool into a new directory. "
        "Treat this bundle as containing the original data; nothing is uploaded by this tool. "
        "A hash identifies bytes, not source authenticity.</p><h2>Limits</h2><ul>"
        + "".join("<li>" + esc(x) + "</li>" for x in result["limits"])
        + "</ul></html>"
    )


def build_interval_bundle(request, fingerprint=None):
    result = review_intervals(request)
    if fingerprint is not None and fingerprint != result["fingerprint"]:
        raise ValueError("Inputs or settings changed. Review and accept the new common sample before export.")
    level = Decimal(result["contract"]["nominal_coverage"])
    rows = []
    for row in result["evaluation_rows"]:
        for sid in result["metrics"]:
            bounds = row["intervals"].get(sid)
            values = [None] * 4
            if result["comparison_ready"] and row["included"]:
                width, score, lo, hi = _row_score(Decimal(row["actual"]), *map(Decimal, bounds), level)
                values = [_reported(width), _reported(score), int(lo), int(hi)]
            rows.append(
                [
                    row["origin"],
                    row["target"],
                    row["entity"],
                    row["horizon_days"],
                    sid,
                    row["included"],
                    row["actual"],
                    *(bounds or [None, None]),
                    *values,
                    json.dumps(row["states"]),
                ]
            )
    headers = [
        "origin",
        "target",
        "entity",
        "horizon_days",
        "candidate",
        "eligible_common",
        "actual",
        "lower",
        "upper",
        "width",
        "interval_score",
        "lower_miss",
        "upper_miss",
        "source_states",
    ]
    files = {
        "request.json": _json(request),
        "results.json": _json(result),
        "report.html": render(result).encode(),
        "evaluation-rows.csv": _csv(headers, rows, numeric_columns=(3, 6, 7, 8, 9, 10, 11, 12)),
        "input-rows.csv": _csv(
            ["source", "row", "status", "key", "reason", "raw"],
            [
                [
                    r["source"],
                    r["row"],
                    r["status"],
                    json.dumps(r["key"]),
                    r.get("reason", ""),
                    json.dumps(r["raw"]),
                ]
                for r in result["input_rows"]
            ],
            numeric_columns=(1,),
        ),
    }
    files["manifest.json"] = _json(
        {
            "task": "interval_review",
            "schema_version": 1,
            "fingerprint": result["fingerprint"],
            "files_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
            "source_code_sha256": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in [
                    "intervals.py",
                    "interval_exports.py",
                    "exporter.py",
                    "engine.py",
                    "probabilities.py",
                    "tableio.py",
                ]
            },
        }
    )
    return files, result
