"""Independent, hand-checkable files for the installed browser acceptance test."""

import csv
import sys
from pathlib import Path

from openpyxl import Workbook


def make(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, headers, rows in [
        ("actual.csv", ["report_month", "realised_units"], [(f"2025-0{i}", i * 10) for i in range(1, 6)]),
        (
            "candidate-a.csv",
            ["estimate_units", "for_month"],
            [(v, f"2025-0{i}") for i, v in enumerate([11, 18, 33, 39], 1)],
        ),
    ]:
        with (destination / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
    workbook = Workbook()
    cover = workbook.active
    cover.title = "Cover"
    cover.append(["Invented browser-test workbook. Choose Forecasts and header row 3."])
    forecast = workbook.create_sheet("Forecasts")
    forecast.append(["Independently invented predictions; no fitted model or external data."])
    forecast.append([])
    forecast.append(["output", "evaluation_month", "unused"])
    for period, value in enumerate([21, 28, 44, 51], 2):
        forecast.append([value, f"2025-0{period}", "preserved in original file"])
    workbook.save(destination / "candidate-b.xlsx")


if __name__ == "__main__":
    make(sys.argv[1])
