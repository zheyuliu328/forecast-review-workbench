"""Independent hand-computed counterexamples for pooled error comparisons."""

import copy
import csv
import io
from decimal import Decimal

from test_origins import origin_request, origin_source

from forecast_review_workbench.engine import review
from forecast_review_workbench.example import _file
from forecast_review_workbench.exporter import build_bundle


def group_request(schema=2):
    declaration = {"target": "Revenue", "unit": "USD", "frequency": "monthly", "transformation": "none"}
    declaration.update({"horizons": [1]} if schema == 2 else {"horizon": 1})

    def source(identifier, values):
        actual = identifier == "actual"
        headers = ["Target", "Entity", "Value"] + (["Origin"] if schema == 2 and not actual else [])
        rows = [
            [target, entity, values[entity]] + ([origin] if schema == 2 and not actual else [])
            for origin, target in [("2024-01", "2024-02"), ("2024-02", "2024-03")]
            for entity in ["Large", "Small"]
        ]
        contract = copy.deepcopy(declaration)
        if schema == 2 and actual:
            del contract["horizons"]
        return {
            "id": identifier,
            "name": identifier,
            "file": _file(identifier + ".csv", headers, rows),
            "mapping": {
                "date": "Target",
                "entity": "Entity",
                "value": "Value",
                **({"origin": "Origin"} if schema == 2 and not actual else {}),
            },
            "contract": contract,
            "source_note": "Original invented example; no fitted models.",
        }

    return {
        "schema_version": schema,
        "title": "Pooled improvement hides a smaller entity getting worse",
        "scope": {
            "frequency": "monthly",
            "entities": ["Large", "Small"],
            **(
                {"origin_start": "2024-01", "origin_end": "2024-02"}
                if schema == 2
                else {"start": "2024-02", "end": "2024-03"}
            ),
        },
        "contract": {k: v for k, v in declaration.items() if k != "frequency"},
        "actual": source("actual", {"Large": 1000, "Small": 10}),
        "candidates": [
            source("a", {"Large": 1050, "Small": 12}),
            source("b", {"Large": 1075, "Small": 10.5}),
        ],
        "baseline": source("baseline", {"Large": 1100, "Small": 11}),
        "accept_common_sample": True,
    }


def test_pooled_improvement_conceals_group_deterioration_in_both_schemas():
    for schema in (1, 2):
        result = review(group_request(schema))
        large, small = result["group_results"]
        assert large["metrics"]["a"]["mae"] == "50"
        assert small["metrics"]["a"]["mae"] == "2"
        assert large["vs_baseline"]["a"]["mae_pct"] == "50"
        assert small["vs_baseline"]["a"]["mae_pct"] == "-100"
        assert small["vs_baseline"]["b"]["mae_pct"] == "50"
        assert result["models"][0]["metrics"]["mae"] == "26"
        assert Decimal(result["models"][0]["vs_baseline"]["mae_pct"]) > 48
        assert sum(g["common"] for g in result["group_results"]) == result["summary"]["common"]


def test_unaccepted_and_contract_conflict_never_expose_group_metrics():
    for conflict in (False, True):
        request = group_request()
        if conflict:
            request["candidates"][0]["contract"]["unit"] = "EUR"
        else:
            request["accept_common_sample"] = False
        result = review(request)
        assert all(g["metrics"] is None and g["vs_baseline"] is None for g in result["group_results"])
        files, _ = build_bundle(request, result["fingerprint"])
        assert b"Common-sample comparison is not ready." in files["group-metrics.csv"]


def test_missing_and_zero_baseline_preserve_empty_groups():
    request = group_request()
    request["baseline"]["file"] = _file(
        "baseline.csv",
        ["Target", "Entity", "Value", "Origin"],
        [["2024-02", "Large", 1000, "2024-01"], ["2024-03", "Large", 1000, "2024-02"]],
    )
    result = review(request)
    large, small = result["group_results"]
    assert large["common"] == 2 and small["common"] == 0
    assert small["expected"] == small["excluded"] == 2
    assert large["vs_baseline"]["a"]["mae_pct"] is None
    assert "zero" in large["vs_baseline"]["a"]["reason"]
    assert all(value is None for value in small["metrics"].values())
    assert "not ready" in small["vs_baseline"]["a"]["reason"]
    assert review(group_request())["fingerprint"] != result["fingerprint"]


def test_no_baseline_and_csv_roundtrip():
    request = group_request()
    del request["baseline"]
    result = review(request)
    assert all(all(v is None for v in g["vs_baseline"].values()) for g in result["group_results"])
    files, _ = build_bundle(request, result["fingerprint"])
    rows = list(csv.DictReader(io.StringIO(files["group-metrics.csv"].decode("utf-8-sig"))))
    assert len(rows) == 4
    assert rows[-1]["baseline_reason"] == "No baseline supplied."
    assert b"Entity and horizon diagnostics" in files["report.html"]


def test_overlapping_horizons_partition_exactly_and_keep_baseline_units():
    request = origin_request()
    request["baseline"] = origin_source(
        "baseline",
        [
            ["2024-01", "2024-02", 1, 102],
            ["2024-01", "2024-03", 2, 112],
            ["2024-02", "2024-03", 1, 112],
            ["2024-02", "2024-04", 2, 122],
        ],
    )
    result = review(request)
    for group, horizon in zip(result["group_results"], result["horizon_results"]):
        assert group["metrics"] == horizon["metrics"]
    h1, h2 = result["group_results"]
    assert h1["vs_baseline"]["a"]["mae_pct"] == "50"
    assert h2["vs_baseline"]["a"]["mae_pct"] == "0"
    assert h2["vs_baseline"]["b"]["mae_pct"] == "50"
    assert result["summary"]["unique_actual_keys"] == 3


def test_report_preview_is_bounded_but_csv_keeps_every_group_and_escapes_entities():
    import base64

    request = group_request()
    entities = [f"Entity-{i:03}" for i in range(99)] + ["=SUM(1,2)", "<script>alert(1)</script>"]
    request["scope"]["entities"] = entities
    for source in [request["actual"], *request["candidates"], request["baseline"]]:
        original = list(csv.reader(io.StringIO(base64.b64decode(source["file"]["content_base64"]).decode())))
        rows = []
        for row in original[1:]:
            if row[1] == "Large":
                rows.extend([[row[0], entity, *row[2:]] for entity in entities])
        source["file"] = _file(source["file"]["name"], original[0], rows)
    result = review(request)
    files, _ = build_bundle(request, result["fingerprint"])
    rows = list(csv.DictReader(io.StringIO(files["group-metrics.csv"].decode("utf-8-sig"))))
    assert len(rows) == 303
    assert any(row["entity"] == "'=SUM(1,2)" for row in rows)
    report = files["report.html"].decode()
    assert "Showing 100 of 101 groups" in report
    assert "<script>alert(1)</script>" not in report
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in report


def test_baseline_gain_uses_unrounded_metrics_in_both_schemas_and_groups():
    import base64
    import json

    for schema in (1, 2):
        for prediction, expected in [
            ("1." + "0" * 48 + "1", Decimal("-1e-47")),
            ("0." + "9" * 49, Decimal("1e-47")),
            ("1", Decimal(0)),
        ]:
            request = group_request(schema)
            for source in [request["actual"], *request["candidates"], request["baseline"]]:
                rows = list(
                    csv.reader(io.StringIO(base64.b64decode(source["file"]["content_base64"]).decode()))
                )
                for row in rows[1:]:
                    row[2] = "0" if source["id"] == "actual" else prediction if source["id"] == "a" else "1"
                source["file"] = _file(source["file"]["name"], rows[0], rows[1:])
            result = review(request)
            # Reported errors still round to 1, but final gains retain the independently
            # known +/- 1e-49 error difference times 100, not a rounded intermediate.
            assert result["models"][0]["metrics"]["mae"] == "1"
            for field in ("mae_pct", "rmse_pct"):
                assert Decimal(result["models"][0]["vs_baseline"][field]) == expected
                for group in result["group_results"]:
                    assert Decimal(group["vs_baseline"]["a"][field]) == expected
            json.dumps(result, allow_nan=False)
            files, _ = build_bundle(request, result["fingerprint"])
            exported = list(csv.DictReader(io.StringIO(files["group-metrics.csv"].decode("utf-8-sig"))))
            assert len(exported) == 6
