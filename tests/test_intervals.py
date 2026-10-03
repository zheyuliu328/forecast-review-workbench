import base64
import hashlib
import json
from pathlib import Path

import pytest

from forecast_review_workbench.example import _file
from forecast_review_workbench.interval_exports import build_interval_bundle
from forecast_review_workbench.intervals import main, review_intervals
from forecast_review_workbench.server import _resolve_files


def example():
    path = Path(__file__).parents[1] / "examples/interval-review/request.json"
    return _resolve_files(json.loads(path.read_text()), path.parent)


def set_rows(source, rows):
    fields = ["target", "actual"] if "actual" in source["mapping"] else ["origin", "target", "lower", "upper"]
    source["file"] = _file("input.csv", [source["mapping"][k] for k in fields], rows)


def test_independent_interval_scores_and_portable_bundle():
    request = example()
    result = review_intervals(request)
    expected = {"A": ("1", "1", "1"), "B": ("1", "20", "20"), "C": ("0.25", "0.5", "4.25")}
    for sid, (coverage, width, score) in expected.items():
        m = result["metrics"][sid]
        assert (m["empirical_interval_coverage"], m["mean_width"], m["mean_interval_score"]) == (
            coverage,
            width,
            score,
        )
    files, exported = build_interval_bundle(request, result["fingerprint"])
    assert exported == result
    manifest = json.loads(files["manifest.json"])
    assert all(hashlib.sha256(files[n]).hexdigest() == h for n, h in manifest["files_sha256"].items())
    assert review_intervals(json.loads(files["request.json"])) == result
    assert b"not source authenticity" in files["report.html"]
    request["contract"]["nominal_coverage"] = "0.9"
    with pytest.raises(ValueError, match="changed"):
        build_interval_bundle(request, result["fingerprint"])


def test_precision_before_reporting_and_zero_width():
    request = example()
    request["candidates"] = request["candidates"][:1]
    keys = request["expected_keys"][:2]
    request["expected_keys"] = keys
    n = 10**49
    set_rows(request["actual"], [(keys[0]["target"], str(n + 2)), (keys[1]["target"], str(n + 4))])
    set_rows(request["candidates"][0], [(k["origin"], k["target"], str(n + 1), str(n + 3)) for k in keys])
    m = review_intervals(request)["metrics"]["A"]
    assert (m["empirical_interval_coverage"], m["mean_width"], m["mean_interval_score"]) == ("0.5", "2", "7")
    set_rows(request["actual"], [(keys[0]["target"], 5), (keys[1]["target"], 6)])
    set_rows(request["candidates"][0], [(k["origin"], k["target"], 5, 5) for k in keys])
    m = review_intervals(request)["metrics"]["A"]
    assert (m["empirical_interval_coverage"], m["mean_width"], m["mean_interval_score"]) == ("0.5", "0", "5")


def overlap():
    request = example()
    request["candidates"] = request["candidates"][:2]
    request["expected_keys"] = [
        {"origin": f"2024-01-0{i}", "target": "2024-01-03", "entity": ""} for i in [1, 2]
    ]
    set_rows(request["actual"], [("2024-01-03", 10)])
    set_rows(
        request["candidates"][0], [("2024-01-01", "2024-01-03", 8, 12), ("2024-01-02", "2024-01-03", 11, 13)]
    )
    set_rows(request["candidates"][1], [(k["origin"], k["target"], 9, 11) for k in request["expected_keys"]])
    return request


def test_overlapping_targets_have_distinct_origins_and_group_scores():
    result = review_intervals(overlap())
    assert result["common"] == 2
    assert result["metrics"]["A"]["mean_interval_score"] == "8"
    assert result["metrics"]["B"]["mean_interval_score"] == "2"
    assert {g["horizon_days"]: g["metrics"]["A"]["mean_interval_score"] for g in result["group_results"]} == {
        1: "12",
        2: "4",
    }


def test_invalid_duplicate_poisoning_and_actual_propagation():
    request = overlap()
    source = request["candidates"][0]
    raw = base64.b64decode(source["file"]["content_base64"]) + b"2024-01-01,2024-01-03,bad,12\r\n"
    source["file"]["content_base64"] = base64.b64encode(raw).decode()
    result = review_intervals(request)
    assert result["common"] == 1
    assert result["metrics"]["A"]["mean_interval_score"] == "12"
    assert sum(r["status"] == "duplicate" for r in result["input_rows"]) == 2
    request = overlap()
    set_rows(request["actual"], [("2024-01-03", 10), ("2024-01-03", 10)])
    result = review_intervals(request)
    assert result["common"] == 0 and not result["comparison_ready"]
    assert all(v is None for v in result["metrics"].values())


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "1e101", "bad"])
def test_invalid_numeric_rows_retained(invalid):
    request = overlap()
    set_rows(request["candidates"][0], [("2024-01-01", "2024-01-03", invalid, 12)])
    result = review_intervals(request)
    assert result["common"] == 0
    assert any(r["status"] == "invalid" and r["source"] == "A" for r in result["input_rows"])


def test_reversed_bounds_never_swapped_and_equal_endpoints_included():
    request = overlap()
    set_rows(
        request["candidates"][0], [("2024-01-01", "2024-01-03", 12, 8), ("2024-01-02", "2024-01-03", 8, 10)]
    )
    result = review_intervals(request)
    assert result["common"] == 1
    assert result["metrics"]["A"]["empirical_interval_coverage"] == "1"
    assert result["metrics"]["B"]["n"] == 1


def test_acceptance_contract_conflicts_and_fingerprint():
    request = example()
    old = review_intervals(request)["fingerprint"]
    request["accept_common_sample"] = False
    result = review_intervals(request)
    assert result["common"] == 4 and not result["comparison_ready"]
    assert all(m is None for m in result["metrics"].values())
    assert result["fingerprint"] != old
    request["accept_common_sample"] = True
    request["candidates"][0]["contract"]["nominal_coverage"] = "0.95"
    assert review_intervals(request)["contract_errors"]
    for accepted in [0, 1, "true", None]:
        request["accept_common_sample"] = accepted
        with pytest.raises(ValueError, match="boolean"):
            review_intervals(request)


def test_cli_frozen_request_replay_and_no_replace(tmp_path):
    source = tmp_path / "request.json"
    source.write_text(json.dumps(example()))
    out = tmp_path / "output"
    assert main([str(source), "--output", str(out)]) == 0
    again = tmp_path / "again"
    assert main([str(out / "request.json"), "--output", str(again)]) == 0
    assert (out / "results.json").read_bytes() == (again / "results.json").read_bytes()
    with pytest.raises(SystemExit) as exc:
        main([str(source), "--output", str(out)])
    assert exc.value.code == 2
