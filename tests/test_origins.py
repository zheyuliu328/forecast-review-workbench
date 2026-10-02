"""Hand-computed rolling-origin fixtures, including overlapping target dates."""

import base64
import csv
import io
from decimal import Decimal

import pytest

from forecast_review_workbench.engine import review
from forecast_review_workbench.exporter import build_bundle


def origin_source(identifier, rows, actual=False):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Target", "Value"] if actual else ["Origin", "Target", "Horizon", "Value"])
    writer.writerows(rows)
    contract = {"target": "Revenue", "unit": "USD", "transformation": "none", "frequency": "monthly"}
    if not actual:
        contract["horizons"] = [1, 2]
    return {
        "id": identifier,
        "name": identifier,
        "file": {
            "name": identifier + ".csv",
            "content_base64": base64.b64encode(stream.getvalue().encode()).decode(),
        },
        "mapping": {
            "date": "Target",
            "value": "Value",
            "entity": None,
            **({} if actual else {"origin": "Origin", "horizon": "Horizon"}),
        },
        "contract": contract,
        "source_note": "Original invented fixture",
    }


def origin_request():
    return {
        "schema_version": 2,
        "scope": {"frequency": "monthly", "origin_start": "2024-01", "origin_end": "2024-02", "entities": []},
        "contract": {"target": "Revenue", "unit": "USD", "transformation": "none", "horizons": [1, 2]},
        "actual": origin_source("actual", [["2024-02", 100], ["2024-03", 110], ["2024-04", 120]], True),
        "candidates": [
            origin_source(
                "a",
                [
                    ["2024-01", "2024-02", 1, 101],
                    ["2024-01", "2024-03", 2, 112],
                    ["2024-02", "2024-03", 1, 109],
                    ["2024-02", "2024-04", 2, 118],
                ],
            ),
            origin_source(
                "b",
                [
                    ["2024-01", "2024-02", 1, 102],
                    ["2024-01", "2024-03", 2, 111],
                    ["2024-02", "2024-03", 1, 111],
                    ["2024-02", "2024-04", 2, 119],
                ],
            ),
        ],
        "accept_common_sample": True,
    }


def test_overlapping_targets_remain_distinct_forecasts():
    result = review(origin_request())
    assert result["comparison_ready"]
    assert result["summary"]["common"] == 4
    assert result["summary"]["unique_actual_keys"] == 3
    assert len(result["input_rows"]) == 11
    assert not result["issues"]
    h1, h2 = result["horizon_results"]
    assert h1["metrics"]["a"]["mae"] == "1"
    assert h1["metrics"]["b"]["mae"] == "1.5"
    assert h2["metrics"]["a"]["mae"] == "2"
    assert h2["metrics"]["b"]["mae"] == "1"
    a, b = result["models"]
    assert a["metrics"]["mae"] == "1.5" and a["metrics"]["bias"] == "0"
    assert b["metrics"]["mae"] == "1.25" and b["metrics"]["bias"] == "0.75"
    assert abs(Decimal(a["metrics"]["rmse"]) ** 2 - Decimal("2.5")) < Decimal("1e-25")
    march = [row for row in result["rows"] if row["period"] == "2024-03"]
    assert len(march) == 2 and march[0]["source_rows"]["actual"] == march[1]["source_rows"]["actual"]


def test_no_acceptance_no_common_metric_and_fingerprint_changes():
    request = origin_request()
    accepted = review(request)
    request["accept_common_sample"] = False
    result = review(request)
    assert result["fingerprint"] != accepted["fingerprint"]
    assert all(h["metrics"] is None for h in result["horizon_results"])
    assert all(m["metrics"] is None for m in result["models"])


def test_mismatch_duplicate_and_missing_actual_propagate_without_row_expansion():
    request = origin_request()
    request["candidates"][0] = origin_source("a", [["2024-01", "2024-02", 2, 101]])
    result = review(request)
    assert any(x["code"] == "horizon_mismatch" for x in result["issues"])
    assert len(result["input_rows"]) == 8
    assert result["summary"]["common"] == 0
    request = origin_request()
    request["actual"] = origin_source(
        "actual", [["2024-02", 100], ["2024-03", 110], ["2024-03", 111], ["2024-04", 120]], True
    )
    result = review(request)
    assert result["summary"]["common"] == 2
    assert len([r for r in result["input_rows"] if r["status"] == "duplicate"]) == 2
    assert all(
        any(x["code"] == "duplicate" for x in row["reasons"])
        for row in result["rows"]
        if row["period"] == "2024-03"
    )
    request["candidates"][0] = origin_source(
        "a", [["2024-01", "2024-02", 1, 101], ["2024-01", "2024-02", 1, 102]]
    )
    result = review(request)
    assert result["summary"]["common"] == 0
    assert len([r for r in result["input_rows"] if r["source_id"] == "a" and r["status"] == "duplicate"]) == 2


@pytest.mark.parametrize("horizons", [[], [True], [0], [-1], [1, 1], [5001], [1.0]])
def test_invalid_horizon_scopes_fail(horizons):
    request = origin_request()
    request["contract"]["horizons"] = horizons
    with pytest.raises(ValueError, match="Horizons"):
        review(request)


def test_origin_coverage_ranking_reversal_and_recovery():
    request = origin_request()
    request["scope"]["origin_end"] = "2024-03"
    request["contract"]["horizons"] = [1]
    request["actual"] = origin_source("actual", [["2024-02", 100], ["2024-03", 100], ["2024-04", 100]], True)
    request["candidates"] = [
        origin_source("a", [["2024-01", "2024-02", 1, 100], ["2024-02", "2024-03", 1, 104]]),
        origin_source("b", [["2024-02", "2024-03", 1, 101], ["2024-03", "2024-04", 1, 110]]),
    ]
    for s in request["candidates"]:
        s["contract"]["horizons"] = [1]
    result = review(request)
    a, b = result["models"]
    assert (a["available_metrics"]["mae"], b["available_metrics"]["mae"]) == ("2", "5.5")
    assert (a["metrics"]["mae"], b["metrics"]["mae"]) == ("4", "1")
    assert {r["origin"] for r in result["rows"] if not r["included"]} == {"2024-01", "2024-03"}
    request["actual"] = origin_source("actual", [["2024-02", 100], ["2024-04", 100]], True)
    after = review(request)
    assert after["summary"]["common"] == 0 and not after["comparison_ready"]
    assert result["fingerprint"] != after["fingerprint"]


def test_origin_calendar_boundaries_and_explicit_universe():
    request = origin_request()
    request["scope"]["origin_end"] = "9999-12"
    with pytest.raises(ValueError):
        review(request)
    request["scope"]["origin_start"] = "9999-12"
    with pytest.raises(ValueError, match="calendar"):
        review(request)
    request = origin_request()
    del request["candidates"][0]["mapping"]["origin"]
    with pytest.raises(ValueError, match="origin column"):
        review(request)


def test_origin_report_exports_recompute_without_losing_keys():
    request = origin_request()
    result = review(request)
    files, _ = build_bundle(request, result["fingerprint"])
    assert b"Forecast origin" in files["report.html"]
    assert b"Per-horizon" in files["report.html"]
    assert "horizon-metrics.csv" in files
    rows = list(csv.DictReader(io.StringIO(files["evaluation-rows.csv"].decode("utf-8-sig"))))
    assert len(rows) == 4 and rows[0]["origin"] == "2024-01" and rows[0]["horizon"] == "1"
    assert rows[2]["residual:a"] == "-1"
    request["scope"]["origin_end"] = "2024-03"
    with pytest.raises(ValueError, match="changed"):
        build_bundle(request, result["fingerprint"])


@pytest.mark.parametrize(
    "frequency,origin,target,horizon",
    [
        ("daily", "2024-02-28", "2024-03-01", 2),
        ("monthly", "2023-12", "2024-02", 2),
        ("quarterly", "2023-Q4", "2024-Q2", 2),
    ],
)
def test_calendar_periods_and_optional_horizon_column(frequency, origin, target, horizon):
    request = origin_request()
    request["scope"].update(frequency=frequency, origin_start=origin, origin_end=origin)
    request["contract"]["horizons"] = [horizon]
    request["actual"] = origin_source("actual", [[target, 100]], True)
    request["candidates"] = [origin_source("a", [[origin, target, 999, 102]])]
    request["actual"]["contract"]["frequency"] = frequency
    candidate = request["candidates"][0]
    candidate["contract"].update(frequency=frequency, horizons=[horizon])
    candidate["mapping"]["horizon"] = None
    result = review(request)
    assert result["comparison_ready"] and result["summary"]["common"] == 1
    assert result["horizon_results"][0]["metrics"]["a"]["mae"] == "2"
    assert result["rows"][0]["horizon"] == horizon
    candidate["mapping"]["horizon"] = "Horizon"
    result = review(request)
    assert result["summary"]["common"] == 0
    assert any(i["code"] == "horizon_mismatch" for i in result["issues"])


@pytest.mark.parametrize(
    "origin,code",
    [
        ("2024-02", "invalid_horizon"),
        ("2024-03", "invalid_horizon"),
        ("", "invalid_origin"),
        ("2023-12", "unselected_horizon"),
    ],
)
def test_invalid_origins_never_fill_common_sample(origin, code):
    request = origin_request()
    request["contract"]["horizons"] = [1]
    request["candidates"] = [origin_source("a", [[origin, "2024-02", 1, 102]])]
    request["candidates"][0]["contract"]["horizons"] = [1]
    result = review(request)
    assert not result["comparison_ready"]
    assert any(i["code"] == code for i in result["issues"])
    assert len(result["input_rows"]) == 4


def test_origin_contract_baseline_and_target_segment():
    request = origin_request()
    request["baseline"] = origin_source(
        "base",
        [
            ["2024-01", "2024-02", 1, 103],
            ["2024-01", "2024-03", 2, 113],
            ["2024-02", "2024-03", 1, 113],
            ["2024-02", "2024-04", 2, 123],
        ],
    )
    request["segments"] = [{"name": "March targets", "start": "2024-03", "end": "2024-03"}]
    result = review(request)
    assert result["segments"][0]["n"] == 2
    assert result["segments"][0]["metrics"]["a"]["mae"] == "1.5"
    assert result["models"][0]["vs_baseline"]["mae_pct"] == "50"
    request["baseline"]["contract"]["horizons"] = [1]
    result = review(request)
    assert not result["comparison_ready"] and result["contract_errors"]
    assert all(h["metrics"] is None for h in result["horizon_results"])


def test_entities_are_exact_and_actual_rows_are_not_expanded():
    request = origin_request()
    request["scope"]["entities"] = ["001", "002"]
    for source in [request["actual"], *request["candidates"]]:
        raw = base64.b64decode(source["file"]["content_base64"]).decode()
        rows = list(csv.reader(io.StringIO(raw)))
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(rows[0] + ["Entity"])
        for row in rows[1:]:
            for entity in ("001", "002"):
                writer.writerow(row + [entity])
        source["file"]["content_base64"] = base64.b64encode(output.getvalue().encode()).decode()
        source["mapping"]["entity"] = "Entity"
    result = review(request)
    assert result["summary"]["expected"] == 8 and result["summary"]["common"] == 8
    assert result["summary"]["unique_actual_keys"] == 6
    assert len(result["input_rows"]) == 22
    assert {r["entity"] for r in result["rows"]} == {"001", "002"}


def test_unparseable_origin_is_not_claimed_to_be_outside_scope():
    request = origin_request()
    request["candidates"][0] = origin_source("a", [["garbage", "2024-02", 1, 101]])
    result = review(request)
    assert result["models"][0]["coverage"]["outside_scope"] == 0
    assert result["summary"]["extra_rows"] == 0
    request["candidates"][0] = origin_source("a", [["2024-03", "2024-04", 1, 101]])
    result = review(request)
    assert result["models"][0]["coverage"]["outside_scope"] == 1
    assert result["summary"]["extra_rows"] == 1
