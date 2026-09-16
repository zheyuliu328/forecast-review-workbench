"""Recompute browser-exported evidence without importing the review engine."""

import csv
import hashlib
import io
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path


def verify(zip_path, output, browser=False):
    output = Path(output)
    with zipfile.ZipFile(zip_path) as bundle:
        result = json.loads(bundle.read("results.json"))
        assert result["summary"]["common"] == 3
        assert len(result["input_rows"]) == 13
        for source in result["sources"]:
            assert source["sha256"] == hashlib.sha256((output / source["file_name"]).read_bytes()).hexdigest()
        records = list(csv.DictReader(io.StringIO(bundle.read("evaluation-rows.csv").decode("utf-8-sig"))))
        # CSV layout is explicitly tested so the downloaded values remain independently usable.
        residuals = [
            Decimal(row["residual:model-a"]) for row in records if row["included_in_common_sample"] == "True"
        ]
        assert residuals == [Decimal(-2), Decimal(3), Decimal(-1)]
        assert sum(abs(value) for value in residuals) / len(residuals) == Decimal(2)
        notes = json.loads(bundle.read("review-notes.json"))["notes"]
        assert len(notes) == 1
        assert notes[0]["fingerprint"] == result["fingerprint"]
        assert notes[0]["decision"] == "needs_evidence"
        # Only the application's fixed, verified filenames are extracted in this test.
        expected = {
            "report.html",
            "results.json",
            "review-notes.json",
            "evaluation-rows.csv",
            "input-rows.csv",
            "issues.csv",
            "metrics.csv",
            "config.json",
            "manifest.json",
        }
        if browser:
            expected.add("browser-build.json")
        assert set(bundle.namelist()) == expected
        manifest = json.loads(bundle.read("manifest.json"))
        assert set(manifest["files_sha256"]) == expected - {"manifest.json"}
        if browser:
            runtime = json.loads(bundle.read("browser-build.json"))
            assert runtime["pyodide_version"] == "314.0.6"
            assert manifest["execution"] == "Browser-local Pyodide Worker; input files are not uploaded."
        for name, fingerprint in manifest["files_sha256"].items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == fingerprint
        destination = output / "unpacked"
        destination.mkdir(exist_ok=True)
        for name in expected:
            (destination / name).write_bytes(bundle.read(name))


if __name__ == "__main__":
    verify(sys.argv[1], sys.argv[2], browser="--browser" in sys.argv[3:])
