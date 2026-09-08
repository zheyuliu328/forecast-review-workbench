"""Failure-focused checks for producer transport and exact result reconciliation."""

import base64
import copy
import csv
import hashlib
import io
import json
import math
import re

import pytest
from openpyxl import Workbook
from test_server import browser_headers, local_tool, request  # noqa: F401

from forecast_review_workbench.engine import review
from forecast_review_workbench.experiments import (
    experiment_example,
    experiment_result,
    normalize_experiment,
    reveal_experiment,
    transfer_experiment,
)
from forecast_review_workbench.exporter import bundle_zip
from forecast_review_workbench.reconciliation import reconcile, reconciliation_example
from forecast_review_workbench.server import main
from forecast_review_workbench.workflow_exports import build_experiment_bundle, build_reconciliation_bundle


def rows_of(file):
    return list(csv.reader(io.StringIO(base64.b64decode(file["content_base64"]).decode())))


def replace_rows(file, rows):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    file["content_base64"] = base64.b64encode(stream.getvalue().encode()).decode()


def test_all_candidates_pooled_metrics_and_two_stages_are_reproducible():
    sample = experiment_example()
    development = experiment_result(sample)
    assert len(development["candidates"]) == 17
    assert sum(row["role"] == "candidate" for row in development["candidates"]) == 15
    assert all(row["holdout"] is None for row in development["candidates"])
    assert {row["split"] for row in development["predictions"]} == {"development"}
    revealed = reveal_experiment(sample, development["fingerprint"])
    assert revealed["selected_on_development"] == development["selected_on_development"]
    assert revealed["selection_fingerprint"] == development["selection_fingerprint"]
    assert revealed["fingerprint"] != development["fingerprint"]
    for model in revealed["candidates"]:
        for split in ("development", "holdout"):
            errors = [
                p["prediction"] - p["actual"]
                for p in revealed["predictions"]
                if p["model_id"] == model["id"] and p["split"] == split
            ]
            expected = {
                "n": len(errors),
                "mae": sum(map(abs, errors)) / len(errors),
                "rmse": math.sqrt(sum(value * value for value in errors) / len(errors)),
                "bias": sum(errors) / len(errors),
            }
            assert model[split] == pytest.approx(expected)
    for prediction in revealed["predictions"]:
        assert prediction["training_cutoff"] <= prediction["origin"] < prediction["period"]


def test_future_targets_change_full_evidence_but_not_development_selection():
    sample = experiment_example()
    before = experiment_result(sample)
    rows = rows_of(sample["file"])
    for row in rows[1:]:
        if row[0] > sample["spec"]["development_end"]:
            row[1] = "99999"
    replace_rows(sample["file"], rows)
    after = experiment_result(sample)
    assert after["selection_fingerprint"] == before["selection_fingerprint"]
    assert after["selected_on_development"] == before["selected_on_development"]
    assert after["candidates"] == before["candidates"]
    assert after["fingerprint"] != before["fingerprint"]
    with pytest.raises(ValueError, match="changed"):
        reveal_experiment(sample, before["fingerprint"])


def test_physical_rows_and_raw_values_survive_reordering_and_nonfirst_header():
    sample = experiment_example()
    rows = rows_of(sample["file"])
    replace_rows(sample["file"], [["Preamble"], ["Second preamble"], rows[0], *reversed(rows[1:])])
    sample["header_row"] = 3
    result = experiment_result(sample)
    first = result["input_rows"][0]
    assert first["period"] == "2010-01" and first["row"] == 183
    assert first["raw"]["Month"] == first["period"]
    assert result["input_rows"][-1]["row"] == 4


def test_excel_sheet_header_and_formula_boundary():
    sample = experiment_example()
    rows = rows_of(sample["file"])
    workbook = Workbook()
    workbook.active.title = "Instructions"
    workbook.active.append(["Use Observations"])
    sheet = workbook.create_sheet("Observations")
    sheet.append(["Independently invented observations"])
    sheet.append(["Header follows"])
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    sample.update(
        {
            "file": {
                "name": "observations.xlsx",
                "content_base64": base64.b64encode(buffer.getvalue()).decode(),
            },
            "sheet": "Observations",
            "header_row": 3,
        }
    )
    assert experiment_result(sample)["coverage"]["raw"] == 180
    sheet["B4"] = "=20+5"
    buffer = io.BytesIO()
    workbook.save(buffer)
    sample["file"]["content_base64"] = base64.b64encode(buffer.getvalue()).decode()
    with pytest.raises(ValueError, match="formulas"):
        experiment_result(sample)


@pytest.mark.parametrize(
    "problem",
    ["duplicate_month", "missing_month", "blank_target", "same_column", "insufficient_lag", "nan_feature"],
)
def test_ambiguous_or_unavailable_training_inputs_fail_loud(problem):
    sample = experiment_example()
    rows = rows_of(sample["file"])
    if problem == "duplicate_month":
        rows[4][0] = rows[3][0]
    elif problem == "missing_month":
        rows.pop(4)
    elif problem == "blank_target":
        rows[4][1] = ""
    elif problem == "same_column":
        sample["mapping"]["features"][0]["column"] = "Observed"
    elif problem == "insufficient_lag":
        sample["mapping"]["features"][0]["release_delay"] = 1
    elif problem == "nan_feature":
        rows[4][2] = "NaN"
    replace_rows(sample["file"], rows)
    with pytest.raises(ValueError):
        experiment_result(sample)


def test_failed_candidates_and_holdout_gaps_survive_transfer_and_exports():
    sample = experiment_example()
    rows = rows_of(sample["file"])
    for row in rows[1:]:
        row[-1] = "1"
        if row[0] == "2023-06":
            row[2] = ""
    replace_rows(sample["file"], rows)
    result = experiment_result(sample, reveal=True)
    assert sum(row["status"] == "failed" for row in result["candidates"]) == 5
    assert len(result["candidates"]) == 17
    assert result["coverage"]["holdout"]["excluded"] == 1
    selected = result["selected_on_development"]
    alternate = next(
        row["id"]
        for row in result["candidates"]
        if row["role"] == "candidate" and row["status"] == "ok" and row["id"] != selected
    )
    transferred = transfer_experiment(sample, result["fingerprint"], [selected, alternate], "baseline-mean")
    assert not transferred["accept_common_sample"]
    assert selected in transferred["candidates"][0]["source_note"]
    assert "exploratory" in transferred["candidates"][1]["source_note"]
    reviewed = review(transferred)
    assert reviewed["summary"]["expected"] == 24 and reviewed["summary"]["common"] == 23
    assert not reviewed["comparison_ready"]
    transferred["accept_common_sample"] = True
    assert review(transferred)["comparison_ready"]
    with pytest.raises(ValueError, match="successful"):
        transfer_experiment(sample, result["fingerprint"], ["ols-f5"], "baseline-mean")
    files, _ = build_experiment_bundle(sample, result["fingerprint"], "holdout")
    csv_rows = list(csv.DictReader(io.StringIO(files["candidates.csv"].decode("utf-8-sig"))))
    assert len(csv_rows) == 17 and sum(row["status"] == "failed" for row in csv_rows) == 5


@pytest.mark.parametrize("change", ["definition", "file", "stage"])
def test_experiment_export_rejects_stale_stage_or_source(change):
    sample = experiment_example()
    result = experiment_result(sample)
    stage = "development"
    if change == "definition":
        sample["source_note"] += " changed declaration"
    elif change == "file":
        rows = rows_of(sample["file"])
        rows[-1][1] = "44"
        replace_rows(sample["file"], rows)
    else:
        stage = "holdout"
    with pytest.raises(ValueError, match="changed"):
        build_experiment_bundle(sample, result["fingerprint"], stage)


def test_additive_net_match_keeps_individual_breaches_and_wrong_reported_total():
    result = reconcile(reconciliation_example())
    assert result["summary"]["breach"] == 2 and result["summary"]["pass"] == 1
    assert result["groups"][0]["difference"] == "0"
    assert result["groups"][0]["status"] == "attention"
    assert result["groups"][0]["offsetting_breaches"]
    assert {row["side"]: row["status"] for row in result["reported_totals"]} == {
        "left": "pass",
        "right": "breach",
    }
    assert len(result["input_rows"]) == 8


@pytest.mark.parametrize("value", ["false", "true", 1, 0, None])
def test_additivity_cannot_be_inferred_or_truthy(value):
    sample = reconciliation_example()
    sample["additive"] = value
    with pytest.raises(ValueError):
        reconcile(sample)


def test_totals_require_explicit_additivity():
    sample = reconciliation_example()
    sample["additive"] = False
    with pytest.raises(ValueError, match="additiv"):
        reconcile(sample)
    sample["left_totals"] = sample["right_totals"] = None
    result = reconcile(sample)
    assert result["groups"] == [] and result["reported_totals"] == []
    assert result["summary"]["breach"] == 2


@pytest.mark.parametrize(
    "change,status",
    [
        ("currency", "definition_conflict"),
        ("unit", "definition_conflict"),
        ("duplicate", "duplicate"),
        ("invalid", "invalid"),
        ("missing", "missing_right"),
    ],
)
def test_invalid_or_ambiguous_financial_rows_cannot_become_group_pass(change, status):
    sample = reconciliation_example()
    rows = rows_of(sample["right"]["file"])
    if change == "currency":
        rows[1][5] = "EUR"
    elif change == "unit":
        rows[1][6] = "thousands"
    elif change == "duplicate":
        rows.append(rows[1][:])
    elif change == "invalid":
        rows[1][-1] = "NaN"
    else:
        rows.pop(1)
    replace_rows(sample["right"]["file"], rows)
    result = reconcile(sample)
    assert result["summary"][status] == 1
    row = next(row for row in result["rows"] if row["identity"]["record_id"] == "001")
    assert row["difference"] is None
    assert all(group["status"] == "attention" for group in result["groups"])
    assert result["summary"]["right_rows"] == len(rows) - 1


def test_decimal_tolerance_has_exact_reference_based_boundary():
    sample = reconciliation_example()
    sample.update(
        {
            "relative_tolerance": "0.001",
            "absolute_tolerance": "0.01",
            "left_totals": None,
            "right_totals": None,
        }
    )
    rows = rows_of(sample["right"]["file"])
    rows[1][-1] = "100.1100000000000000000000000000001"
    replace_rows(sample["right"]["file"], rows)
    result = reconcile(sample)
    row = next(row for row in result["rows"] if row["identity"]["record_id"] == "001")
    assert row["allowed_difference"] == "0.110"
    assert row["status"] == "breach"
    rows[1][-1] = "100.11"
    replace_rows(sample["right"]["file"], rows)
    result = reconcile(sample)
    assert next(row for row in result["rows"] if row["identity"]["record_id"] == "001")["status"] == "pass"


def test_reported_totals_are_checked_per_group_and_extra_groups_are_retained():
    sample = reconciliation_example()
    rows = rows_of(sample["left_totals"]["file"])
    rows.append(rows[1][:])
    rows[-1][3] = "3M"
    replace_rows(sample["left_totals"]["file"], rows)
    result = reconcile(sample)
    left_checks = [row for row in result["reported_totals"] if row["side"] == "left"]
    assert len(left_checks) == 2
    assert any(row["status"] != "pass" and row["dimensions"]["tenor"] == "3M" for row in left_checks)


def test_manual_opinions_are_source_bound_and_never_change_calculated_status():
    sample = reconciliation_example()
    result = reconcile(sample)
    record = next(row for row in result["rows"] if row["status"] == "breach")
    note = {
        "record_key": record["record_key"],
        "decision": "accepted_difference",
        "text": "<script>alert(1)</script> reviewer explanation",
        "fingerprint": result["fingerprint"],
    }
    files, reviewed = build_reconciliation_bundle(sample, result["fingerprint"], [note])
    assert reviewed["summary"]["breach"] == 2
    assert b"<script>alert" not in files["report.html"]
    assert b"&lt;script&gt;" in files["report.html"]
    assert json.loads(files["review-notes.json"])[0]["origin"] == "manual caller opinion"
    sample["absolute_tolerance"] = "100"
    refreshed = reconcile(sample)
    with pytest.raises(ValueError, match="changed"):
        build_reconciliation_bundle(sample, refreshed["fingerprint"], [note])


def test_csv_columns_and_signed_numerics_are_usable_and_text_is_escaped():
    sample = reconciliation_example()
    rows = rows_of(sample["left"]["file"])
    rows[1][0] = "=DANGEROUS()"
    replace_rows(sample["left"]["file"], rows)
    result = reconcile(sample)
    files, _ = build_reconciliation_bundle(sample, result["fingerprint"])
    values = list(csv.DictReader(io.StringIO(files["row-differences.csv"].decode("utf-8-sig"))))
    assert all(None not in row for row in values)
    assert any(row["record_id"].startswith("'=DANGEROUS") for row in values)
    normal = next(row for row in values if row["record_id"] == "002")
    assert float(normal["difference"]) == -10
    assert normal["status"] == "breach" and normal["left_source_rows"] == "3"
    for name in ("group-differences.csv", "reported-totals.csv", "input-rows.csv"):
        assert all(None not in row for row in csv.DictReader(io.StringIO(files[name].decode("utf-8-sig"))))


@pytest.mark.parametrize("workflow", ["experiment", "reconcile"])
def test_complete_evidence_is_reproducible_and_replayable(workflow):
    sample = experiment_example() if workflow == "experiment" else reconciliation_example()
    if workflow == "experiment":
        result = experiment_result(sample)
        build = lambda: build_experiment_bundle(sample, result["fingerprint"], "development")  # noqa: E731
    else:
        result = reconcile(sample)
        build = lambda: build_reconciliation_bundle(sample, result["fingerprint"])  # noqa: E731
    files, _ = build()
    manifest = json.loads(files["manifest.json"])
    assert set(manifest["files"]) == set(files) - {"manifest.json"}
    for name, metadata in manifest["files"].items():
        assert metadata == {"sha256": hashlib.sha256(files[name]).hexdigest(), "bytes": len(files[name])}
    assert json.loads(files["request.json"]) == sample
    assert bundle_zip(files) == bundle_zip(build()[0])
    assert b"http://" not in files["report.html"] and b"https://" not in files["report.html"]


def test_extension_pages_serve_actual_scripts_and_tokens(local_tool):  # noqa: F811
    for path in ("/experiments", "/reconcile"):
        status, _, page = request(local_tool, path)
        assert status == 200
        assert local_tool.csrf_token.encode() in page
        for asset in re.findall(rb'(?:src|href)="(/static/[^"]+)"', page):
            assert request(local_tool, asset.decode())[0] == 200


def test_http_extensions_reveal_export_and_reject_changed_input(local_tool):  # noqa: F811
    headers = browser_headers(local_tool)
    sample = experiment_example()
    status, _, raw = request(local_tool, "/api/experiments/prepare", "POST", sample, headers)
    assert status == 200
    result = json.loads(raw)
    payload = {"request": sample, "fingerprint": result["fingerprint"]}
    assert request(local_tool, "/api/experiments/reveal", "POST", payload, headers)[0] == 200
    assert (
        request(local_tool, "/api/experiments/export", "POST", {**payload, "stage": "development"}, headers)[
            0
        ]
        == 200
    )
    sample["spec"]["target"]["unit"] = "changed unit"
    assert request(local_tool, "/api/experiments/reveal", "POST", payload, headers)[0] == 400
    sample = reconciliation_example()
    status, _, raw = request(local_tool, "/api/reconcile", "POST", sample, headers)
    assert status == 200
    result = json.loads(raw)
    assert (
        request(
            local_tool,
            "/api/reconcile/export",
            "POST",
            {"request": sample, "fingerprint": result["fingerprint"]},
            headers,
        )[0]
        == 200
    )


@pytest.mark.parametrize("workflow", ["experiment", "reconcile"])
def test_cli_accepts_explicit_paths_and_never_overwrites(workflow, tmp_path):
    sample = experiment_example() if workflow == "experiment" else reconciliation_example()
    sources = (
        [sample]
        if workflow == "experiment"
        else [sample[key] for key in ("left", "right", "left_totals", "right_totals")]
    )
    for i, source in enumerate(sources):
        source_path = tmp_path / f"source-{i}.csv"
        source_path.write_bytes(base64.b64decode(source["file"]["content_base64"]))
        source["file"] = {"path": source_path.name}
    config = tmp_path / "request.json"
    config.write_text(json.dumps(sample))
    output = tmp_path / "evidence"
    status = main([f"--{workflow}", str(config), "--output", str(output)])
    assert status == (0 if workflow == "experiment" else 1)
    before = (output / "results.json").read_bytes()
    assert main([f"--{workflow}", str(config), "--output", str(output)]) == 2
    assert (output / "results.json").read_bytes() == before


def test_normalized_kernel_request_has_no_browser_file_paths():
    sample = experiment_example()
    normalized, source, mapped = normalize_experiment(copy.deepcopy(sample))
    assert "file" not in normalized and len(normalized["rows"]) == len(mapped) == source["rows"]
    assert normalized["features"][0]["id"] == "f1"
