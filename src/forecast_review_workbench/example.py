"""Fresh invented files demonstrating why coverage comes before model ranking."""

import base64
import csv
import io


def _file(name, headers, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return {"name": name, "content_base64": base64.b64encode(stream.getvalue().encode()).decode()}


def example_request():
    """No model is fitted; the supplied forecasts and errors are deliberately invented."""
    periods = [f"2024-{month:02d}" for month in range(1, 13)]
    values = [100, 108, 111, 107, 120, 118, 132, 129, 146, 158, 225, 260]
    declaration = {
        "target": "Monthly revenue",
        "unit": "USD",
        "horizon": 1,
        "transformation": "none",
        "frequency": "monthly",
    }

    def source(name, headers, rows, date_column, value_column):
        return {
            "file": _file(name, headers, rows),
            "sheet": None,
            "header_row": 1,
            "mapping": {"date": date_column, "value": value_column, "entity": None},
            "contract": dict(declaration),
            "source_note": "Independently invented illustration; no fitted model or business data.",
        }

    actual = source("actual.csv", ["Month", "Observed"], zip(periods, values), "Month", "Observed")
    a_rows = [
        (p, value + (0 if i in (3, 4) else 2)) for i, (p, value) in enumerate(zip(periods, values)) if i < 9
    ]
    b_rows = [
        (p, value + (1 if i < 9 else 12))
        for i, (p, value) in enumerate(zip(periods, values))
        if i not in (3, 4)
    ]
    model_a = source("candidate-a.csv", ["period", "Forecast"], a_rows, "period", "Forecast")
    model_b = source("candidate-b.csv", ["snapshot", "prediction"], b_rows, "snapshot", "prediction")
    baseline = source(
        "baseline.csv",
        ["Month", "Reference"],
        [(p, value + 3) for p, value in zip(periods, values)],
        "Month",
        "Reference",
    )
    return {
        "schema_version": 1,
        "title": "A lower error can hide missing periods",
        "scope": {"start": "2024-01", "end": "2024-12", "frequency": "monthly", "entities": []},
        "contract": {key: value for key, value in declaration.items() if key != "frequency"},
        "actual": actual,
        "candidates": [
            {"id": "model-a", "name": "Candidate A", **model_a},
            {"id": "model-b", "name": "Candidate B", **model_b},
        ],
        "baseline": {"id": "baseline", "name": "Provided baseline", **baseline},
        "accept_common_sample": False,
        "segments": [{"name": "Later half", "start": "2024-07", "end": "2024-12"}],
    }


def origin_example_request():
    """An original two-horizon example whose preferred candidate depends on horizon."""
    declaration = {"target": "Revenue", "unit": "USD", "transformation": "none", "frequency": "monthly"}
    origins = ["2024-01", "2024-01", "2024-02", "2024-02"]
    targets = ["2024-02", "2024-03", "2024-03", "2024-04"]
    horizons = [1, 2, 1, 2]
    candidates = []
    for identifier, values in (("a", [101, 112, 109, 118]), ("b", [102, 111, 111, 119])):
        candidates.append(
            {
                "id": identifier,
                "name": "Candidate " + identifier.upper(),
                "file": _file(
                    identifier + ".csv",
                    ["Origin", "Target", "Horizon", "Value"],
                    zip(origins, targets, horizons, values),
                ),
                "mapping": {
                    "date": "Target",
                    "value": "Value",
                    "entity": None,
                    "origin": "Origin",
                    "horizon": "Horizon",
                },
                "contract": {**declaration, "horizons": [1, 2]},
                "source_note": "Independently invented rolling-origin illustration.",
            }
        )
    return {
        "schema_version": 2,
        "title": "A different winner at each horizon",
        "scope": {"origin_start": "2024-01", "origin_end": "2024-02", "frequency": "monthly", "entities": []},
        "contract": {"target": "Revenue", "unit": "USD", "transformation": "none", "horizons": [1, 2]},
        "actual": {
            "file": _file(
                "actual.csv", ["Target", "Value"], [["2024-02", 100], ["2024-03", 110], ["2024-04", 120]]
            ),
            "mapping": {"date": "Target", "value": "Value", "entity": None},
            "contract": declaration,
            "source_note": "Independently invented actuals, each target appears once.",
        },
        "candidates": candidates,
        "accept_common_sample": False,
    }


def group_example_request():
    """Pooled gains hide an invented smaller entity's deterioration."""
    declaration = {"target": "Revenue", "unit": "USD", "transformation": "none", "frequency": "monthly"}

    def source(identifier, values):
        actual = identifier == "actual"
        headers = ["Target", "Entity", "Value"] + ([] if actual else ["Origin"])
        rows = [
            [target, entity, values[entity]] + ([] if actual else [origin])
            for origin, target in [("2024-01", "2024-02"), ("2024-02", "2024-03")]
            for entity in ["Large", "Small"]
        ]
        return {
            "id": identifier,
            "name": identifier,
            "file": _file(identifier + ".csv", headers, rows),
            "mapping": {
                "date": "Target",
                "entity": "Entity",
                "value": "Value",
                **({} if actual else {"origin": "Origin"}),
            },
            "contract": {**declaration, **({} if actual else {"horizons": [1]})},
            "source_note": "Original invented example; no fitted models.",
        }

    return {
        "schema_version": 2,
        "title": "Pooled improvement hides a smaller entity getting worse",
        "scope": {
            "frequency": "monthly",
            "entities": ["Large", "Small"],
            "origin_start": "2024-01",
            "origin_end": "2024-02",
        },
        "contract": {"target": "Revenue", "unit": "USD", "transformation": "none", "horizons": [1]},
        "actual": source("actual", {"Large": 1000, "Small": 10}),
        "candidates": [
            source("a", {"Large": 1050, "Small": 12}),
            source("b", {"Large": 1075, "Small": 10.5}),
        ],
        "baseline": source("baseline", {"Large": 1100, "Small": 11}),
        "accept_common_sample": False,
    }


def interval_example():
    """Original wide/narrow/missed-bound counterexample, not fitted forecasts."""
    contract = {
        "target": "Invented net cash flow",
        "unit": "USD",
        "transformation": "none",
        "nominal_coverage": "0.8",
    }
    targets = [f"2024-01-{i:02d}" for i in range(2, 6)]
    candidates = []
    for sid in ("A", "B", "C"):
        rows = []
        for i, target in enumerate(targets):
            lo, hi = (i - 0.5, i + 0.5) if sid == "A" else (i - 10, i + 10)
            if sid == "C":
                lo, hi = max(0, i - 1), max(0, i - 1) + 0.5
            rows.append(["2024-01-01", target, lo, hi])
        candidates.append(
            {
                "id": sid,
                "file": _file(sid + ".csv", ["Origin", "Target", "Lower", "Upper"], rows),
                "mapping": {
                    "origin": "Origin",
                    "target": "Target",
                    "entity": None,
                    "lower": "Lower",
                    "upper": "Upper",
                },
                "contract": dict(contract),
                "source_note": "Original invented bounds; not fitted forecasts.",
            }
        )
    return {
        "task": "interval_review",
        "schema_version": 1,
        "title": "Equal containment can hide very wide intervals",
        "contract": contract,
        "accept_common_sample": False,
        "expected_keys": [{"origin": "2024-01-01", "target": t, "entity": ""} for t in targets],
        "actual": {
            "id": "actual",
            "file": _file("actual.csv", ["Target", "Actual"], zip(targets, range(4))),
            "mapping": {"target": "Target", "entity": None, "actual": "Actual"},
            "contract": {k: v for k, v in contract.items() if k != "nominal_coverage"},
            "source_note": "Original invented observations; no financial records.",
        },
        "candidates": candidates,
    }


def probability_example():
    """Original labels becoming available over time, including an impossible prediction."""
    event = "Invented event: count exceeds a fixed threshold within two observation steps."
    origins = ["2025-01-01", "2025-01-02", "2025-01-03"]

    def source(sid, fields, rows, mapping):
        return {
            "id": sid,
            "file": _file(sid + ".csv", fields, rows),
            "mapping": mapping,
            "event_definition": event,
            "source_note": "Original invented test; no model fit.",
        }

    return {
        "task": "binary_event_review",
        "schema_version": 1,
        "event_definition": event,
        "evaluation_as_of": "2025-01-03",
        "expected_keys": [{"origin": origin, "entity": ""} for origin in origins],
        "accept_common_sample": False,
        "labels": source(
            "labels",
            ["Origin", "Label", "Available"],
            zip(origins, [0, 1, 1], ["2025-01-02", "2025-01-03", "2025-01-04"]),
            {"origin": "Origin", "entity": None, "label": "Label", "available": "Available"},
        ),
        "candidates": [
            source(
                "a",
                ["Origin", "Probability"],
                zip(origins, ["0.25", "0.75", "0"]),
                {"origin": "Origin", "entity": None, "probability": "Probability"},
            )
        ],
        "baseline": source(
            "baseline",
            ["Origin", "Probability"],
            zip(origins, ["0.5"] * 3),
            {"origin": "Origin", "entity": None, "probability": "Probability"},
        ),
    }
