"""Exercise the installed command with external files, independent of its source checkout."""

import csv
import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pytest


def _command(cwd, *arguments):
    executable = Path(sys.executable).parent / (
        "forecast-review.exe" if os.name == "nt" else "forecast-review"
    )
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [str(executable), *map(str, arguments)],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.fixture
def external_request(tmp_path):
    request_dir = tmp_path / "request pack"
    input_dir = request_dir / "inputs"
    input_dir.mkdir(parents=True)
    actual = input_dir / "actual values.csv"
    forecast = input_dir / "forecast values.csv"
    actual.write_bytes(b"Period,Observed\n2024-01,10\n2024-02,20\n2024-03,30\n")
    forecast.write_bytes(b"Month,Prediction\n2024-03,34\n2024-01,11\n")
    declaration = {
        "target": "Invented monthly total",
        "unit": "units",
        "horizon": 1,
        "transformation": "none",
        "frequency": "monthly",
    }
    request = {
        "schema_version": 1,
        "title": "CLI external-file fixture",
        "scope": {"start": "2024-01", "end": "2024-03", "frequency": "monthly", "entities": []},
        "contract": {key: value for key, value in declaration.items() if key != "frequency"},
        "actual": {
            "file": {"path": "inputs/actual values.csv"},
            "mapping": {"date": "Period", "value": "Observed", "entity": None},
            "contract": dict(declaration),
            "source_note": "Invented actuals in a separate request directory",
        },
        "candidates": [
            {
                "id": "external-model",
                "name": "External forecast",
                "file": {"path": "inputs/forecast values.csv"},
                "mapping": {"date": "Month", "value": "Prediction", "entity": None},
                "contract": dict(declaration),
                "source_note": "Two invented forecast rows, deliberately reversed",
            }
        ],
        "baseline": None,
        "segments": [],
        "accept_common_sample": True,
    }
    request_path = request_dir / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    cwd = tmp_path / "unrelated directory"
    (cwd / "inputs").mkdir(parents=True)
    # These are valid but wrong files if source paths are incorrectly based on process cwd.
    (cwd / "inputs/actual values.csv").write_text("Period,Observed\n2024-01,999\n")
    (cwd / "inputs/forecast values.csv").write_text("Month,Prediction\n2024-01,999\n")
    return {
        "request": request,
        "request_path": request_path,
        "argument": os.path.relpath(request_path, cwd),
        "cwd": cwd,
        "sources": {"actual": actual, "external-model": forecast},
    }


def _bundle(output):
    required = {
        "report.html",
        "results.json",
        "metrics.csv",
        "evaluation-rows.csv",
        "input-rows.csv",
        "issues.csv",
        "config.json",
        "review-notes.json",
        "manifest.json",
    }
    assert required.issubset({path.name for path in output.iterdir()})
    manifest = json.loads((output / "manifest.json").read_text())
    assert set(manifest["files_sha256"]) == {path.name for path in output.iterdir()} - {"manifest.json"}
    for name, expected_hash in manifest["files_sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected_hash
    results = json.loads((output / "results.json").read_text())
    assert manifest["fingerprint"] == results["fingerprint"]
    return results, manifest


def test_cli_resolves_source_paths_against_request_file_and_exports_real_evidence(external_request):
    case = external_request
    before = {identifier: path.read_bytes() for identifier, path in case["sources"].items()}
    process = _command(case["cwd"], "--review", case["argument"], "--output", "fresh report")
    assert process.returncode == 0, process.stderr
    output = case["cwd"] / "fresh report"
    results, manifest = _bundle(output)
    summary = json.loads(process.stdout)
    assert Path(summary["output"]).resolve() == output.resolve()
    assert summary["comparison_ready"] and summary["expected"] == 3 and summary["common"] == 2
    assert results["title"] == "CLI external-file fixture"
    assert [row["actual"] for row in results["rows"]] == ["10", "20", "30"]
    assert [row["predictions"]["external-model"] for row in results["rows"]] == ["11", None, "34"]
    model = results["models"][0]
    assert model["metrics"]["n"] == 2
    assert model["metrics"]["mae"] == "2.5" and model["metrics"]["bias"] == "2.5"
    with localcontext() as context:
        context.prec = 60
        assert abs(Decimal(model["metrics"]["rmse"]) - Decimal("8.5").sqrt()) < Decimal("1e-39")
    expected_hashes = {
        identifier: hashlib.sha256(content).hexdigest() for identifier, content in before.items()
    }
    assert {item["id"]: item["sha256"] for item in manifest["inputs"]} == expected_hashes
    assert {item["id"]: item["sha256"] for item in results["sources"]} == expected_hashes
    assert before == {identifier: path.read_bytes() for identifier, path in case["sources"].items()}
    with (output / "evaluation-rows.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3 and rows[1]["included_in_common_sample"] == "False"
    assert rows[0]["residual:external-model"] == "1" and rows[2]["residual:external-model"] == "4"
    report = (output / "report.html").read_text()
    assert "CLI external-file fixture" in report and "External forecast" in report


def test_cli_refuses_repeated_destination_without_changing_any_evidence(external_request):
    case = external_request
    output = case["cwd"] / "saved report"
    arguments = ("--review", case["argument"], "--output", output)
    assert _command(case["cwd"], *arguments).returncode == 0
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    sources = {identifier: path.read_bytes() for identifier, path in case["sources"].items()}
    repeated = _command(case["cwd"], *arguments)
    assert repeated.returncode == 2 and not repeated.stdout
    assert "existing" in repeated.stderr.lower() or "already exists" in repeated.stderr.lower()
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    assert sources == {identifier: path.read_bytes() for identifier, path in case["sources"].items()}


def test_cli_pending_sample_exports_coverage_with_exit_one_and_no_common_metrics(external_request):
    case = external_request
    case["request"]["accept_common_sample"] = False
    case["request_path"].write_text(json.dumps(case["request"]), encoding="utf-8")
    output = case["cwd"] / "pending report"
    process = _command(case["cwd"], "--review", case["argument"], "--output", output)
    assert process.returncode == 1, process.stderr
    results, _manifest = _bundle(output)
    assert not results["comparison_ready"] and results["summary"]["common"] == 2
    assert all(model["metrics"] is None for model in results["models"])
    with (output / "metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
        metrics = list(csv.DictReader(stream))
    assert len(metrics) == 1
    assert all(metrics[0][field] == "" for field in ("n", "mae", "rmse", "bias"))
    assert "No common-sample metric conclusion" in (output / "report.html").read_text()


@pytest.mark.parametrize(
    "defect", ["missing_source", "duplicate_headers", "malformed_json", "invalid_schema"]
)
def test_cli_invalid_input_exits_two_without_output_or_source_mutation(external_request, defect):
    case = external_request
    if defect == "missing_source":
        case["request"]["actual"]["file"]["path"] = "inputs/absent.csv"
    elif defect == "duplicate_headers":
        case["sources"]["actual"].write_bytes(b"Period,Observed,Observed\n2024-01,10,20\n")
    elif defect == "invalid_schema":
        case["request"]["schema_version"] = 999
    case["request_path"].write_text(
        "{broken" if defect == "malformed_json" else json.dumps(case["request"]), encoding="utf-8"
    )
    before = {identifier: path.read_bytes() for identifier, path in case["sources"].items()}
    output = case["cwd"] / "invalid report"
    process = _command(case["cwd"], "--review", case["argument"], "--output", output)
    assert process.returncode == 2, process.stderr
    assert process.stderr and "Traceback" not in process.stderr and not process.stdout
    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}-*"))
    assert before == {identifier: path.read_bytes() for identifier, path in case["sources"].items()}


def test_cli_example_exports_accepted_seven_row_common_sample_with_exit_zero(tmp_path):
    cwd = tmp_path / "outside checkout"
    cwd.mkdir()
    process = _command(cwd, "--example", "--output", "example report")
    assert process.returncode == 0, process.stderr
    results, _manifest = _bundle(cwd / "example report")
    assert results["comparison_ready"] and results["accepted_common_sample"]
    assert results["summary"]["expected"] == 12 and results["summary"]["common"] == 7
    models = {model["id"]: model for model in results["models"]}
    assert models["model-a"]["coverage"]["valid"] == 9
    assert models["model-b"]["coverage"]["valid"] == 10
    assert all(model["metrics"]["n"] == 7 for model in models.values())
    assert models["model-a"]["metrics"]["mae"] == "2"
    assert models["model-b"]["metrics"]["mae"] == "1"
    assert models["baseline"]["metrics"]["mae"] == "3"
