"""Independent invented files and export arithmetic for browser acceptance."""

import argparse
import csv
import hashlib
import json
import math
import random
import zipfile
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook


def _csv(destination, name, headers, rows):
    with (destination / name).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def _workbook(destination, name, sheet, headers, rows):
    path = destination / name
    if path.exists():
        raise FileExistsError(f"Refusing to replace {path}")
    workbook = Workbook()
    cover = workbook.active
    cover.title = "Read me"
    cover.append(["Independently invented acceptance-test fixture."])
    cover.append([f"Select {sheet}, with header row 3. No external or private data."])
    table = workbook.create_sheet(sheet)
    table.append(["Independent browser fixture: preserve this original file."])
    table.append([])
    table.append(headers)
    for row in rows:
        table.append(row)
    workbook.save(path)


def make(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    names = [
        "training-history.csv",
        "training-history.xlsx",
        "reference.csv",
        "challenger.xlsx",
        "reference-totals.csv",
        "challenger-totals.xlsx",
        "totals-focus-reference.csv",
        "totals-focus-challenger.csv",
        "totals-focus-left.csv",
        "totals-focus-right.csv",
        "fixture-expectations.json",
    ]
    if any((destination / name).exists() for name in names):
        raise FileExistsError("Choose a fresh output directory; original fixtures are never overwritten.")
    rng = random.Random(9032026)
    features = []
    for index in range(180):
        features.append(
            [
                round(math.sin(index * 0.31) + rng.uniform(-0.35, 0.35), 7),
                round(math.cos(index * 0.13) + rng.uniform(-0.28, 0.28), 7),
                round(math.sin(index * 0.053) + rng.uniform(-0.55, 0.55), 7),
                round(index / 180 + rng.uniform(-0.35, 0.35), 7),
                2,
            ]
        )
    history = []
    for index in range(180):
        month = 2010 * 12 + index
        target = round(
            80
            + 2.1 * features[max(0, index - 1)][0]
            - 0.9 * features[max(0, index - 2)][1]
            + rng.uniform(-0.25, 0.25),
            7,
        )
        values = features[index].copy()
        if index == 70:
            values[2] = None
        if index == 160:
            values[1] = None
        history.append([f"{month // 12:04d}-{month % 12 + 1:02d}", target, *values])
    history_headers = [
        "Observation month",
        "Observed units",
        "Activity",
        "Credit",
        "Prices",
        "Trend",
        "Flat signal",
    ]
    _csv(destination, "training-history.csv", history_headers, history)
    _workbook(destination, "training-history.xlsx", "Monthly history", history_headers, history)

    headers = ["Record code", "As of", "Metric", "Risk class", "Maturity", "CCY", "Value unit", "Amount"]
    reference = [
        ["001", "2025-12-31", "PV", "IR", "5Y", "USD", "USD", "100"],
        ["002", "2025-12-31", "PV", "IR", "5Y", "USD", "USD", "200"],
        ["003", "2025-12-31", "Sensitivity", "FX", "1Y", "USD", "USD", "50"],
        ["004", "2025-12-31", "PV", "IR", "10Y", "USD", "USD", "25"],
        ["005", "2025-12-31", "EAD", "Credit", "1Y", "USD", "USD", "75"],
    ]
    challenger = [
        ["001", "2025-12-31", "PV", "IR", "5Y", "USD", "USD", "110"],
        ["002", "2025-12-31", "PV", "IR", "5Y", "USD", "USD", "190"],
        ["004", "2025-12-31", "PV", "IR", "10Y", "USD", "USD thousands", "25"],
        ["005", "2025-12-31", "EAD", "Credit", "1Y", "USD", "USD", "75.005"],
    ]
    _csv(destination, "reference.csv", headers, reference)
    _workbook(destination, "challenger.xlsx", "Challenger values", headers, challenger)
    totals_headers = headers[1:]
    reference_totals = [
        ["2025-12-31", "PV", "IR", "5Y", "USD", "USD", "300"],
        ["2025-12-31", "Sensitivity", "FX", "1Y", "USD", "USD", "50"],
        ["2025-12-31", "PV", "IR", "10Y", "USD", "USD", "25"],
        ["2025-12-31", "EAD", "Credit", "1Y", "USD", "USD", "75"],
    ]
    challenger_totals = [
        ["2025-12-31", "PV", "IR", "5Y", "USD", "USD", "295"],
        ["2025-12-31", "PV", "IR", "10Y", "USD", "USD thousands", "25"],
        ["2025-12-31", "EAD", "Credit", "1Y", "USD", "USD", "75.005"],
    ]
    _csv(destination, "reference-totals.csv", totals_headers, reference_totals)
    _workbook(destination, "challenger-totals.xlsx", "Reported totals", totals_headers, challenger_totals)
    focused_rows = [
        ["r1", "2025-12-31", "PV", "IR", "1M", "USD", "USD", "100"],
        ["r2", "2025-12-31", "PV", "IR", "3M", "USD", "USD", "200"],
    ]
    _csv(destination, "totals-focus-reference.csv", headers, focused_rows)
    _csv(destination, "totals-focus-challenger.csv", headers, focused_rows)
    _csv(
        destination,
        "totals-focus-left.csv",
        totals_headers,
        [
            ["2025-12-31", "PV", "IR", "1M", "USD", "USD", "200"],
            ["2025-12-31", "PV", "IR", "3M", "USD", "USD", "100"],
            ["2025-12-31", "PV", "IR", "6M", "USD", "USD", "999"],
        ],
    )
    _csv(destination, "totals-focus-right.csv", totals_headers, [row[1:] for row in focused_rows])
    expectations = {
        "training": {
            "raw": 180,
            "development_end": "2021-12",
            "candidates": 15,
            "baselines": 2,
            "feature_columns": history_headers[2:],
            "lags": [1, 2, 3, 1, 2],
            "release_delays": [0, 1, 2, 0, 1],
            "header_row": 3,
        },
        "reconciliation": {
            "expected": 5,
            "left_rows": 5,
            "right_rows": 4,
            "pass": 1,
            "breach": 2,
            "missing_right": 1,
            "definition_conflict": 1,
            "offsetting_ids": ["001", "002"],
            "reference_reported_pv": "300",
            "challenger_reported_pv": "295",
        },
        "files": names[:-1],
    }
    (destination / "fixture-expectations.json").write_text(
        json.dumps(expectations, indent=2) + "\n", encoding="utf-8"
    )


def _month(value):
    year, month = value.split("-")
    return int(year) * 12 + int(month) - 1


def _close(actual, expected):
    assert math.isclose(float(actual), float(expected), rel_tol=1e-11, abs_tol=1e-11), (actual, expected)


def verify(zip_path, kind):
    with zipfile.ZipFile(zip_path) as bundle:
        result = json.loads(bundle.read("results.json"))
        manifest = json.loads(bundle.read("manifest.json"))
        if "files" in manifest:
            for name, entry in manifest["files"].items():
                data = bundle.read(name)
                assert hashlib.sha256(data).hexdigest() == entry["sha256"]
                assert len(data) == entry["bytes"]
        else:
            for name, digest in manifest["files_sha256"].items():
                assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
        if kind in {"development", "holdout"}:
            assert result["stage"] == kind
            assert len([m for m in result["candidates"] if m["role"] == "candidate"]) == 15
            assert len([m for m in result["candidates"] if m["role"] == "baseline"]) == 2
            assert any(m["status"] == "failed" and m["reason"] for m in result["candidates"])
            assert result["coverage"]["raw"] == 180
            assert len(result["input_rows"]) == 180
            assert all(row["row"] >= 4 for row in result["input_rows"])
            for model in result["candidates"]:
                for split in ("development", "holdout"):
                    rows = [
                        row
                        for row in result["predictions"]
                        if row["model_id"] == model["id"] and row["split"] == split
                    ]
                    metrics = model[split]
                    if metrics is None:
                        assert not rows
                        continue
                    errors = [float(row["prediction"]) - float(row["actual"]) for row in rows]
                    assert len(errors) == metrics["n"] and errors
                    _close(metrics["mae"], sum(map(abs, errors)) / len(errors))
                    _close(metrics["rmse"], math.sqrt(sum(x * x for x in errors) / len(errors)))
                    _close(metrics["bias"], sum(errors) / len(errors))
            if kind == "development":
                assert not [row for row in result["predictions"] if row["split"] == "holdout"]
                assert all(model["holdout"] is None for model in result["candidates"])
            horizon = result["protocol"]["horizon"]
            for fold in result["folds"]:
                if fold["validation_periods"]:
                    assert _month(fold["training_cutoff"]) <= (
                        _month(min(fold["validation_periods"])) - horizon
                    )
                assert all(period <= fold["training_cutoff"] for period in fold["train_periods"])
        elif kind == "reconcile":
            summary = result["summary"]
            for key, expected in {
                "expected": 5,
                "left_rows": 5,
                "right_rows": 4,
                "pass": 1,
                "breach": 2,
                "missing_right": 1,
                "definition_conflict": 1,
            }.items():
                assert summary[key] == expected, (key, summary[key])
            by_id = {row["identity"]["record_id"]: row for row in result["rows"]}
            assert Decimal(by_id["001"]["difference"]) == 10
            assert Decimal(by_id["002"]["difference"]) == -10
            assert by_id["004"]["status"] == "definition_conflict"
            assert by_id["004"]["difference"] is None
            group = next(
                group
                for group in result["groups"]
                if group["dimensions"]["measure"] == "PV" and group["dimensions"]["tenor"] == "5Y"
            )
            assert Decimal(group["difference"]) == 0
            assert group["status"] != "pass" and group["offsetting_breaches"]
            reported = [
                row
                for row in result["reported_totals"]
                if row["dimensions"]["measure"] == "PV" and row["dimensions"]["tenor"] == "5Y"
            ]
            assert len(reported) == 2
            assert {Decimal(row["reported"]) for row in reported} == {Decimal(300), Decimal(295)}
            assert any(row["status"] == "breach" for row in reported)
            notes = json.loads(bundle.read("review-notes.json"))
            assert isinstance(notes, list)
            assert len(notes) == 1
            assert notes[0]["fingerprint"] == result["fingerprint"]
            assert notes[0]["record_key"] == by_id["001"]["record_key"]
            assert notes[0]["decision"] == "needs_evidence"
        elif kind == "review":
            assert result["comparison_ready"] is True
            assert result["summary"]["common"] > 0
            assert all(model["metrics"]["n"] == result["summary"]["common"] for model in result["models"])
        else:
            raise ValueError(f"Unknown verification kind: {kind}")
    verification = {
        "zip": str(zip_path),
        "kind": kind,
        "fingerprint": result["fingerprint"],
        "verified": True,
    }
    print(json.dumps(verification))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", nargs="?")
    parser.add_argument("--verify")
    parser.add_argument("--kind", choices=["development", "holdout", "reconcile", "review"])
    arguments = parser.parse_args()
    if arguments.verify:
        verify(arguments.verify, arguments.kind)
    elif arguments.destination:
        make(arguments.destination)
    else:
        parser.error("Provide a new fixture destination, or --verify ZIP --kind KIND.")
