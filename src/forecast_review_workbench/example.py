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
