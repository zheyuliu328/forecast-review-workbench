"""Hand-counted forecast coverage and Decimal metric counterexamples."""

import base64
import copy
import csv
import io
import json
from datetime import datetime
from decimal import Decimal, localcontext

import pytest
from openpyxl import Workbook

from forecast_review_workbench.engine import review

CONTRACT = {"target": "Revenue", "unit": "USD", "horizon": 1, "transformation": "none"}


def source(identifier, rows, *, entities=False, frequency="monthly"):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Date", "Value", "Entity"] if entities else ["Date", "Value"])
    writer.writerows(rows)
    return {
        "id": identifier,
        "name": identifier.upper(),
        "file": {
            "name": f"{identifier}.csv",
            "content_base64": base64.b64encode(stream.getvalue().encode()).decode(),
        },
        "mapping": {"date": "Date", "value": "Value", "entity": "Entity" if entities else None},
        "contract": {**CONTRACT, "frequency": frequency},
        "source_note": "Invented test rows",
    }


def payload():
    actual = [[f"2024-{month:02d}", 10 + month] for month in range(1, 13)]
    a = [[f"2024-{month:02d}", 11 + month] for month in range(1, 10)]
    b = [[f"2024-{month:02d}", 7 + month] for month in range(3, 13)]
    baseline = [[f"2024-{month:02d}", 12 + month] for month in range(1, 13)]
    return {
        "schema_version": 1,
        "title": "Invented forecast review",
        "scope": {"start": "2024-01", "end": "2024-12", "frequency": "monthly", "entities": []},
        "contract": dict(CONTRACT),
        "actual": source("actual", actual),
        "candidates": [source("a", a), source("b", b)],
        "baseline": source("base", baseline),
        "accept_common_sample": False,
        "segments": [
            {"name": "No common rows", "start": "2024-01", "end": "2024-02"},
            {"name": "Four rows", "start": "2024-03", "end": "2024-06"},
        ],
    }


def models(result):
    return {model["id"]: model for model in result["models"]}


def test_explicit_12_period_universe_a9_b10_common7_before_acceptance():
    result = review(payload())
    assert result["summary"]["expected"] == 12 and result["summary"]["common"] == 7
    assert result["summary"]["excluded"] == 5
    assert not result["comparison_ready"] and not result["accepted_common_sample"]
    mapped = models(result)
    assert mapped["a"]["coverage"] == {
        "expected": 12,
        "valid": 9,
        "missing": 3,
        "duplicate": 0,
        "invalid": 0,
        "outside_scope": 0,
    }
    assert mapped["b"]["coverage"]["valid"] == 10
    assert mapped["a"]["available_metrics"] == {"n": 9, "mae": "1", "rmse": "1", "bias": "1"}
    assert mapped["b"]["available_metrics"] == {"n": 10, "mae": "3", "rmse": "3", "bias": "-3"}
    assert all(model["metrics"] is None for model in result["models"])
    assert all(segment["metrics"] is None for segment in result["segments"])
    assert sum(row["included"] for row in result["rows"]) == 7
    assert len(result["input_rows"]) == 12 + 9 + 10 + 12
    json.dumps(result, allow_nan=False)


def test_accepted_common_sample_and_baseline_keep_bad_results():
    request = payload()
    request["accept_common_sample"] = True
    result = review(request)
    assert result["comparison_ready"]
    mapped = models(result)
    assert [mapped[key]["metrics"]["n"] for key in ("a", "b", "base")] == [7, 7, 7]
    assert mapped["a"]["vs_baseline"] == {"mae_pct": "50", "rmse_pct": "50", "reason": None}
    assert mapped["b"]["vs_baseline"] == {"mae_pct": "-50", "rmse_pct": "-50", "reason": None}
    assert result["segments"][0]["n"] == 0
    assert result["segments"][0]["metrics"] == {"a": None, "b": None, "base": None}
    assert result["segments"][1]["n"] == 4
    assert all(metric["n"] == 4 for metric in result["segments"][1]["metrics"].values())


def test_eight_period_hand_calculation_uses_rmse_not_residual_standard_error():
    request = payload()
    request["scope"]["end"] = "2024-08"
    errors = [-3, -2, -1, 0, 1, 2, 3, 4]
    request["actual"] = source("actual", [[f"2024-{i:02d}", i] for i in range(1, 9)])
    request["candidates"] = [
        source("hand", [[f"2024-{i:02d}", i + error] for i, error in enumerate(errors, 1)])
    ]
    request["baseline"], request["segments"], request["accept_common_sample"] = None, [], True
    model = review(request)["models"][0]
    assert model["metrics"]["n"] == 8
    assert model["metrics"]["mae"] == "2" and model["metrics"]["bias"] == "0.5"
    with localcontext() as context:
        context.prec = 60
        expected = Decimal("5.5").sqrt()
        assert abs(Decimal(model["metrics"]["rmse"]) - expected) < Decimal("1e-39")
    assert model["vs_baseline"] is None


def test_reordering_rows_changes_fingerprint_but_not_coverage_or_metrics():
    request = payload()
    request["accept_common_sample"] = True
    first = review(request)
    reordered = copy.deepcopy(request)
    for item in [reordered["actual"], *reordered["candidates"], reordered["baseline"]]:
        raw = base64.b64decode(item["file"]["content_base64"]).decode()
        rows = list(csv.reader(io.StringIO(raw)))
        stream = io.StringIO(newline="")
        csv.writer(stream).writerows([rows[0], *reversed(rows[1:])])
        item["file"]["content_base64"] = base64.b64encode(stream.getvalue().encode()).decode()
    second = review(reordered)
    assert first["models"] == second["models"] and first["segments"] == second["segments"]
    assert first["summary"] == second["summary"]
    assert first["fingerprint"] != second["fingerprint"]


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("unit", "HKD"),
        ("target", "Profit"),
        ("horizon", 2),
        ("transformation", "log"),
        ("frequency", "daily"),
        ("horizon", True),
    ],
)
def test_contract_conflicts_block_all_numerical_comparison(field, wrong):
    request = payload()
    request["accept_common_sample"] = True
    request["candidates"][0]["contract"][field] = wrong
    result = review(request)
    assert result["contract_errors"] and not result["comparison_ready"]
    assert result["summary"]["common"] == 7
    assert all(model["metrics"] is None and model["available_metrics"] is None for model in result["models"])
    assert all(value is None for row in result["rows"] for value in row["residuals"].values())
    assert result["rows"][0]["actual"] == "11"
    json.dumps(result, allow_nan=False)


def test_fingerprint_includes_source_declaration_and_acceptance_but_not_title_or_notes():
    request = payload()
    initial = review(request)["fingerprint"]
    request["title"] = "A different display title"
    request["notes"] = [{"text": "untrusted freeform review note"}]
    assert review(request)["fingerprint"] == initial
    request["actual"]["source_note"] = "A changed caller declaration"
    changed = review(request)["fingerprint"]
    assert changed != initial
    request["accept_common_sample"] = True
    assert review(request)["fingerprint"] != changed


def test_zero_baseline_denominator_has_no_infinite_or_fabricated_improvement():
    request = payload()
    request["baseline"] = copy.deepcopy(request["actual"])
    request["baseline"].update(id="zero", name="Perfect supplied baseline")
    request["accept_common_sample"] = True
    result = review(request)
    comparison = models(result)["a"]["vs_baseline"]
    assert comparison["mae_pct"] is None and comparison["rmse_pct"] is None
    assert "zero" in comparison["reason"]
    json.dumps(result, allow_nan=False)


def test_duplicate_invalid_and_outside_rows_are_all_retained_without_zero_fill():
    request = payload()
    request["scope"]["end"] = "2024-04"
    request["actual"] = source("actual", [[f"2024-{i:02d}", "10"] for i in range(1, 5)])
    rows = [
        ["2024-01", "11"],
        ["2024-01-15", "12"],
        ["2024-02", "nan"],
        ["not a date", "1"],
        ["2023-12", "2"],
        ["2024-04", "13"],
    ]
    request["candidates"], request["baseline"] = [source("a", rows)], None
    request["accept_common_sample"] = True
    result = review(request)
    assert models(result)["a"]["coverage"] == {
        "expected": 4,
        "valid": 1,
        "missing": 1,
        "duplicate": 1,
        "invalid": 1,
        "outside_scope": 1,
    }
    assert result["summary"]["common"] == 1 and result["summary"]["extra_rows"] == 1
    retained = [row for row in result["input_rows"] if row["source_id"] == "a"]
    assert len(retained) == 6
    assert [row["status"] for row in retained] == [
        "duplicate",
        "duplicate",
        "invalid_numeric",
        "invalid_date",
        "outside_scope",
        "valid",
    ]
    assert result["rows"][0]["source_rows"]["a"] == [2, 3]
    assert result["rows"][0]["predictions"]["a"] is None
    assert result["rows"][1]["predictions"]["a"] is None
    assert models(result)["a"]["metrics"] == {"n": 1, "mae": "3", "rmse": "3", "bias": "3"}


def test_explicit_entity_cross_product_preserves_leading_zero_ids():
    request = payload()
    request["scope"].update(end="2024-02", entities=["001", "1"])
    rows = [["2024-01", "10", "001"], ["2024-01", "20", "1"], ["2024-02", "30", "001"]]
    request["actual"] = source("actual", rows, entities=True)
    request["candidates"] = [source("a", list(reversed(rows)), entities=True)]
    request["baseline"] = None
    request["accept_common_sample"] = True
    result = review(request)
    assert result["summary"]["expected"] == 4 and result["summary"]["common"] == 3
    assert [(row["period"], row["entity"]) for row in result["rows"]] == [
        ("2024-01", "001"),
        ("2024-01", "1"),
        ("2024-02", "001"),
        ("2024-02", "1"),
    ]
    assert result["rows"][-1]["actual"] is None


@pytest.mark.parametrize(
    "dates,frequency,start,end,expected",
    [
        (["2024-01-31", "2024-02-29"], "monthly", "2024-01", "2024-02", ["2024-01", "2024-02"]),
        (["2024-03-31", "2024-04"], "quarterly", "2024-Q1", "2024-Q2", ["2024-Q1", "2024-Q2"]),
        (["2024-02-28", "2024-02-29"], "daily", "2024-02-28", "2024-02-29", ["2024-02-28", "2024-02-29"]),
    ],
)
def test_dates_normalize_only_under_declared_frequency(dates, frequency, start, end, expected):
    request = payload()
    request["scope"] = {"start": start, "end": end, "frequency": frequency, "entities": []}
    data = [[period, "5"] for period in dates]
    request["actual"] = source("actual", data, frequency=frequency)
    request["candidates"] = [source("a", data, frequency=frequency)]
    request["baseline"], request["segments"] = None, []
    assert [row["period"] for row in review(request)["rows"]] == expected


@pytest.mark.parametrize("bad", ["2024-W01-1", "20240101", "2023-02-29", "2024-1-01", " 2024-01-01", "45292"])
def test_invalid_dates_remain_input_diagnostics(bad):
    request = payload()
    request["candidates"] = [source("a", [[bad, "1"]])]
    request["baseline"] = None
    result = review(request)
    assert any(issue["source_id"] == "a" and issue["code"] == "invalid_date" for issue in result["issues"])
    assert models(result)["a"]["coverage"]["valid"] == 0


def test_excel_date_formula_and_numeric_entity_inputs_are_not_coerced():
    request = payload()
    request["scope"].update(end="2024-02", entities=["0007"])
    actual = [["2024-01", "1", "0007"], ["2024-02", "2", "0007"]]
    request["actual"] = source("actual", actual, entities=True)
    item = source("a", actual, entities=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Date", "Value", "Entity"])
    sheet.append([datetime(2024, 1, 15, 12), "=1+0", "0007"])
    sheet.append([datetime(2024, 2, 1), 2, 7])
    sheet["C3"].number_format = "0000"
    data = io.BytesIO()
    workbook.save(data)
    workbook.close()
    item["file"] = {"name": "typed.xlsx", "content_base64": base64.b64encode(data.getvalue()).decode()}
    request["candidates"], request["baseline"] = [item], None
    result = review(request)
    rows = [row for row in result["input_rows"] if row["source_id"] == "a"]
    assert [row["status"] for row in rows] == ["formula_cell", "invalid_entity"]
    assert rows[0]["period"] == "2024-01" and rows[0]["value"] is None
    assert rows[1]["raw_entity"] == "7" and rows[1]["entity"] is None
    assert result["summary"]["common"] == 0


def test_decimal_residuals_retain_more_than_default_28_digits():
    request = payload()
    request["scope"]["end"] = "2024-01"
    request["actual"] = source("actual", [["2024-01", "0"]])
    value = "0.123456789012345678901234567890123456789"
    request["candidates"] = [source("a", [["2024-01", value]])]
    request["baseline"], request["segments"], request["accept_common_sample"] = None, [], True
    result = review(request)
    assert result["rows"][0]["residuals"]["a"] == value
    assert result["models"][0]["metrics"]["mae"] == value


def test_extreme_bounded_decimal_cancellation_retains_tiny_nonzero_bias():
    request = payload()
    request["scope"]["end"] = "2024-03"
    request["actual"] = source("actual", [[f"2024-{i:02d}", "0"] for i in range(1, 4)])
    data = [["2024-01", "1e100"], ["2024-02", "1e-100"], ["2024-03", "-1e100"]]
    request["candidates"] = [source("a", data)]
    request["baseline"], request["segments"], request["accept_common_sample"] = None, [], True
    first = review(request)
    with localcontext() as context:
        context.prec = 650
        expected_bias = Decimal("1e-100") / 3
        assert abs(Decimal(first["models"][0]["metrics"]["bias"]) - expected_bias) < Decimal("1e-140")
    request["candidates"] = [source("a", list(reversed(data)))]
    assert review(request)["models"] == first["models"]
    json.dumps(first, allow_nan=False)


def test_large_errors_squared_for_rmse_remain_finite_decimal_values():
    request = payload()
    request["scope"]["end"] = "2024-01"
    request["actual"] = source("actual", [["2024-01", "1e100"]])
    request["candidates"] = [source("a", [["2024-01", "-1e100"]])]
    request["baseline"], request["segments"], request["accept_common_sample"] = None, [], True
    metrics = review(request)["models"][0]["metrics"]
    assert Decimal(metrics["mae"]) == Decimal("2e100")
    assert Decimal(metrics["rmse"]) == Decimal("2e100")
    assert Decimal(metrics["bias"]) == Decimal("-2e100")


@pytest.mark.parametrize("bad", ["nan", "inf", "1,000", "1e101", "1e-101", "1_000"])
def test_nonfinite_ambiguous_and_out_of_bounds_numbers_are_diagnostics(bad):
    request = payload()
    request["candidates"], request["baseline"] = [source("a", [["2024-01", bad]])], None
    result = review(request)
    invalid = [row for row in result["input_rows"] if row["source_id"] == "a"]
    assert invalid[0]["status"] == "invalid_numeric" and invalid[0]["raw_value"] == bad
    assert invalid[0]["value"] is None and result["summary"]["common"] == 0
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda request: request["scope"].update(frequency=["monthly"]),
        lambda request: request["scope"].update(entities=["001"]),
        lambda request: request["actual"]["mapping"].update(entity="Date"),
        lambda request: request["candidates"][0].update(id="actual"),
        lambda request: request.update(accept_common_sample="true"),
        lambda request: request["scope"].update(start="1000-01", end="9999-12"),
    ],
)
def test_malformed_requests_raise_actionable_value_error(mutate):
    request = payload()
    mutate(request)
    with pytest.raises(ValueError):
        review(request)
