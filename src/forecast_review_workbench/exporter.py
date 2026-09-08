"""Inspectable, offline review bundles with source-bound manual notes."""

import csv
import ctypes
import hashlib
import html
import io
import json
import os
import re
import sys
import zipfile
from decimal import Decimal
from pathlib import Path
from string import Template
from tempfile import TemporaryDirectory

from . import __version__
from .engine import review

DECISIONS = {"retain": "Retain", "needs_evidence": "Needs more evidence", "do_not_adopt": "Do not adopt"}


def _json(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _safe_csv(value):
    if value is None:
        return ""
    text = str(value)
    probe = text.lstrip("\ufeff \t\n\r")
    if (probe and probe[0] in "=+-@") or any(ord(c) < 32 or ord(c) == 127 for c in text):
        return "'" + text
    return text


def _csv(headers, rows, numeric_columns=()):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([_safe_csv(value) for value in headers])
    for row in rows:
        cells = []
        for column, value in enumerate(row):
            if column in numeric_columns and value is not None:
                text = str(value)
                if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text):
                    raise ValueError("A calculated CSV field is not a finite decimal number.")
                cells.append(text)
            else:
                cells.append(_safe_csv(value))
        writer.writerow(cells)
    return stream.getvalue().encode("utf-8-sig")


def _notes(notes, result):
    if not isinstance(notes, list) or len(notes) > len(result["models"]):
        raise ValueError("Provide at most one review note per model.")
    names = {item["id"]: item["name"] for item in result["models"]}
    seen, checked = set(), []
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError("Each review note must contain a model, decision and text.")
        model_id, decision, text = note.get("model_id"), note.get("decision"), note.get("text", "")
        if model_id not in names or model_id in seen:
            raise ValueError("Review notes contain an unknown or repeated model.")
        if decision not in DECISIONS or not isinstance(text, str) or len(text) > 4000:
            raise ValueError("Select a supported decision and keep each note within 4,000 characters.")
        if not text.strip():
            raise ValueError("Add a reason for each manual decision, or remove the empty decision.")
        if note.get("fingerprint") != result["fingerprint"]:
            raise ValueError(
                "A review note belongs to an older input or setting. Review it again before export."
            )
        seen.add(model_id)
        checked.append(
            {
                "model_id": model_id,
                "model_name": names[model_id],
                "decision": decision,
                "text": text,
                "fingerprint": result["fingerprint"],
                "origin": "manual caller opinion",
            }
        )
    return checked


def _table(headers, rows):
    escape = lambda value: html.escape("—" if value is None else str(value), quote=True)  # noqa: E731
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + "".join(f"<th>{escape(value)}</th>" for value in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in row) + "</tr>" for row in rows)
        + "</tbody></table></div>"
    )


def _report(result, notes):
    escape = lambda value: html.escape(str(value), quote=True)  # noqa: E731
    summary = result["summary"]
    contract = result["contract"]
    state = (
        "Common-sample comparison" if result["comparison_ready"] else "Coverage review · comparison pending"
    )
    metrics_rows = []

    def metric_display(value):
        return None if value is None else format(Decimal(value), ".7g")

    for model in result["models"]:
        m = model.get("metrics") or {}
        baseline = model.get("vs_baseline") or {}
        metrics_rows.append(
            [
                model["name"],
                model["role"],
                model["coverage"]["valid"],
                model["coverage"]["expected"],
                m.get("n"),
                metric_display(m.get("mae")),
                metric_display(m.get("rmse")),
                metric_display(m.get("bias")),
                metric_display(baseline.get("mae_pct")),
            ]
        )
    metrics_table = _table(
        [
            "Model",
            "Role",
            "Valid expected",
            "Expected",
            "Common n",
            "MAE",
            "RMSE",
            "Bias",
            "MAE gain vs baseline %",
        ],
        metrics_rows,
    )
    exclusions = [row for row in result["rows"] if not row["included"]]
    exclusions_table = _table(
        ["Period", "Entity", "Why excluded"],
        (
            [
                row["period"],
                row["entity"],
                "; ".join(f"{reason['source_id']}: {reason['detail']}" for reason in row["reasons"]),
            ]
            for row in exclusions[:100]
        ),
    )
    metric_files = "".join(
        f'<li><a href="{name}">{label}</a></li>'
        for name, label in [
            ("metrics.csv", "Same-sample metrics"),
            ("evaluation-rows.csv", "Every expected row and residual"),
            ("input-rows.csv", "Every mapped input row"),
            ("issues.csv", "Input and coverage issues"),
            ("results.json", "Exact results and segment metrics"),
            ("review-notes.json", "Manual review notes"),
            ("config.json", "Mappings and declarations"),
            ("manifest.json", "Input and output fingerprints"),
        ]
    )
    notes_html = (
        "".join(
            f"<article><h3>{escape(note['model_name'])} · {escape(DECISIONS[note['decision']])}</h3>"
            f"<p class='preserve'>{escape(note['text'])}</p>"
            "<small>Manual opinion tied to this fingerprint.</small></article>"
            for note in notes
        )
        or "<p>No manual decisions were supplied.</p>"
    )
    conflicts = (
        _table(
            ["Source", "Field", "Expected", "Declared"],
            ([e["source_id"], e["field"], e["expected"], e["received"]] for e in result["contract_errors"]),
        )
        if result["contract_errors"]
        else "<p>The supplied definitions agree. Their correctness remains caller-declared.</p>"
    )
    sources = _table(
        ["Source", "File", "Rows", "Input SHA-256", "Caller provenance note"],
        (
            [s["name"], s["file_name"], s["rows"], s["sha256"], s.get("source_note", "")]
            for s in result["sources"]
        ),
    )
    warnings = "".join(f"<li>{escape(item)}</li>" for item in result["warnings"])
    interpretation = (
        "Metrics below use exactly the same valid expected keys for every candidate "
        "and the provided baseline. "
        "Excluded periods remain outside the conclusion; a smaller error does not resolve missing coverage."
        if result["comparison_ready"]
        else "No common-sample metric conclusion has been made. Resolve conflicting definitions, "
        "obtain common "
        "valid rows and explicitly accept the available common sample in the tool."
    )
    template = Template(Path(__file__).with_name("report.html.template").read_text(encoding="utf-8"))
    return template.substitute(
        title=escape(result["title"]),
        state=state,
        interpretation=escape(interpretation),
        expected=summary["expected"],
        common=summary["common"],
        excluded=summary["excluded"],
        target=escape(contract["target"]),
        unit=escape(contract["unit"]),
        horizon=escape(contract["horizon"]),
        transformation=escape(contract["transformation"]),
        metrics_table=metrics_table,
        conflicts=conflicts,
        exclusions_table=exclusions_table,
        shown_exclusions=min(100, len(exclusions)),
        exclusion_count=len(exclusions),
        notes_html=notes_html,
        sources=sources,
        metric_files=metric_files,
        warnings=warnings,
        version=__version__,
        fingerprint=escape(result["fingerprint"]),
    ).encode()


def build_bundle(request, fingerprint, notes=None):
    """Recompute the current request and reject opinions tied to any other review state."""
    result = review(request)
    if fingerprint != result["fingerprint"]:
        raise ValueError("Inputs or settings changed after review. Run the review again before exporting.")
    checked_notes = _notes([] if notes is None else notes, result)
    models = result["models"]
    ids = [item["id"] for item in models]
    headers = ["period", "entity", "included_in_common_sample", "actual"]
    for model_id in ids:
        headers.extend([f"prediction:{model_id}", f"residual:{model_id}"])
    headers += ["exclusion_reasons", "source_rows"]
    evaluation_rows = []
    for row in result["rows"]:
        values = [row["period"], row["entity"], row["included"], row["actual"]]
        for model_id in ids:
            values += [row["predictions"].get(model_id), row["residuals"].get(model_id)]
        values += [
            json.dumps(row["reasons"], ensure_ascii=False),
            json.dumps(row["source_rows"], ensure_ascii=False),
        ]
        evaluation_rows.append(values)
    input_headers = [
        "source_id",
        "row",
        "raw_date",
        "raw_value",
        "raw_entity",
        "period",
        "entity",
        "value",
        "status",
    ]
    issue_headers = ["source_id", "row", "period", "entity", "code", "detail"]
    files = {
        "report.html": _report(result, checked_notes),
        "results.json": _json(result),
        "review-notes.json": _json(
            {"fingerprint": fingerprint, "origin": "manual caller opinions", "notes": checked_notes}
        ),
        "evaluation-rows.csv": _csv(headers, evaluation_rows, numeric_columns=range(3, 4 + 2 * len(ids))),
        "input-rows.csv": _csv(
            input_headers,
            ([row.get(k) for k in input_headers] for row in result["input_rows"]),
            numeric_columns=(1, 7),
        ),
        "issues.csv": _csv(
            issue_headers,
            ([row.get(k) for k in issue_headers] for row in result["issues"]),
            numeric_columns=(1,),
        ),
        "metrics.csv": _csv(
            ["model_id", "name", "role", "n", "mae", "rmse", "bias"],
            (
                [m["id"], m["name"], m["role"]]
                + [(m.get("metrics") or {}).get(k) for k in ("n", "mae", "rmse", "bias")]
                for m in models
            ),
            numeric_columns=(3, 4, 5, 6),
        ),
        "config.json": _json(
            {
                "scope": result["scope"],
                "contract": result["contract"],
                "accepted_common_sample": result["accepted_common_sample"],
                "sources": result["sources"],
                "segments": request.get("segments", []),
                "fingerprint": fingerprint,
            }
        ),
    }
    code_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("engine.py", "tableio.py", "exporter.py", "report.html.template")
    }
    files["manifest.json"] = _json(
        {
            "schema_version": 1,
            "tool_version": __version__,
            "fingerprint": fingerprint,
            "source_code_sha256": code_hashes,
            "inputs": [
                {"id": s["id"], "file_name": s["file_name"], "sha256": s["sha256"]} for s in result["sources"]
            ],
            "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            "scope": "Technical review of supplied forecasts; manual opinions are not automated approval.",
        }
    )
    return files, result


def bundle_zip(files):
    """Fixed metadata makes repeated exports of identical evidence byte-reproducible."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return stream.getvalue()


def _publish_new(stage, output):
    """No-replace atomic publication, adapted from the author's public FCT project (MIT)."""
    if sys.platform == "win32":
        os.rename(stage, output)
        return
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = library.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        args = (os.fsencode(stage), os.fsencode(output), 4)
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        function = library.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        args = (-100, os.fsencode(stage), -100, os.fsencode(output), 1)
    else:
        raise OSError("This platform does not provide supported atomic no-replace publication.")
    function.restype = ctypes.c_int
    if function(*args):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(output))


def write_bundle(files, output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Choose a new output directory; this destination already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        for name, content in files.items():
            if Path(name).name != name:
                raise ValueError("Bundle members must be plain filenames.")
            (stage / name).write_bytes(content)
        _publish_new(stage, output)
