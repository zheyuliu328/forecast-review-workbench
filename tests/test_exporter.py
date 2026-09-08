import base64
import copy
import csv
import hashlib
import io
import json
import zipfile
from decimal import Decimal

import pytest

from forecast_review_workbench.engine import review
from forecast_review_workbench.example import example_request
from forecast_review_workbench.exporter import build_bundle, bundle_zip, write_bundle


def test_coverage_trap_and_export_are_recomputable():
    request = example_request()
    request["accept_common_sample"] = True
    result = review(request)
    assert result["summary"]["common"] == 7
    a, b, baseline = result["models"]
    assert Decimal(a["available_metrics"]["mae"]) < Decimal(b["available_metrics"]["mae"])
    assert a["metrics"]["mae"] == "2"
    assert b["metrics"]["mae"] == "1"
    assert baseline["metrics"]["mae"] == "3"
    files, _ = build_bundle(request, result["fingerprint"])
    rows = list(csv.DictReader(io.StringIO(files["evaluation-rows.csv"].decode("utf-8-sig"))))
    common = [row for row in rows if row["included_in_common_sample"] == "True"]
    assert len(common) == 7 and len(rows) == 12
    for model_id, expected in (("model-a", Decimal(2)), ("model-b", Decimal(1))):
        errors = [Decimal(row[f"prediction:{model_id}"]) - Decimal(row["actual"]) for row in common]
        assert sum(abs(error) for error in errors) / len(errors) == expected
    manifest = json.loads(files["manifest.json"])
    assert all(
        hashlib.sha256(files[name]).hexdigest() == digest for name, digest in manifest["files_sha256"].items()
    )
    zipped = bundle_zip(files)
    assert zipped == bundle_zip(build_bundle(request, result["fingerprint"])[0])
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        assert sorted(archive.namelist()) == sorted(files)
        assert all(archive.read(name) == data for name, data in files.items())


def test_negative_computed_numbers_remain_numeric_but_raw_text_is_escaped():
    request = example_request()
    request["scope"]["end"] = "2024-01"
    request["segments"] = []
    request["candidates"] = request["candidates"][:1]
    request["baseline"] = None
    request["actual"]["file"]["content_base64"] = base64.b64encode(b"Month,Observed\n2024-01,20\n").decode()
    request["candidates"][0]["file"]["content_base64"] = base64.b64encode(
        b"period,Forecast\n2024-01,-1\n"
    ).decode()
    request["accept_common_sample"] = True
    result = review(request)
    files, _ = build_bundle(request, result["fingerprint"])
    row = next(csv.DictReader(io.StringIO(files["evaluation-rows.csv"].decode("utf-8-sig"))))
    assert row["prediction:model-a"] == "-1"
    assert row["residual:model-a"] == "-21"
    metric = next(csv.DictReader(io.StringIO(files["metrics.csv"].decode("utf-8-sig"))))
    assert metric["bias"] == "-21"
    inputs = list(csv.DictReader(io.StringIO(files["input-rows.csv"].decode("utf-8-sig"))))
    assert inputs[1]["raw_value"] == "'-1" and inputs[1]["value"] == "-1"


@pytest.mark.parametrize("change", ["bytes", "source_note", "accepted", "unit", "scope"])
def test_changed_review_rejects_old_fingerprint_and_notes(change):
    request = example_request()
    result = review(request)
    changed = copy.deepcopy(request)
    if change == "bytes":
        file = changed["actual"]["file"]
        file["content_base64"] = base64.b64encode(base64.b64decode(file["content_base64"]) + b"\n").decode()
    elif change == "source_note":
        changed["actual"]["source_note"] = "Different provenance declaration"
    elif change == "accepted":
        changed["accept_common_sample"] = True
    elif change == "unit":
        changed["candidates"][0]["contract"]["unit"] = "EUR"
    else:
        changed["scope"]["end"] = "2024-11"
    with pytest.raises(ValueError, match="changed"):
        build_bundle(changed, result["fingerprint"])
    current = review(changed)
    with pytest.raises(ValueError, match="older"):
        build_bundle(
            changed,
            current["fingerprint"],
            [
                {
                    "model_id": "model-a",
                    "decision": "needs_evidence",
                    "text": "Review coverage",
                    "fingerprint": result["fingerprint"],
                }
            ],
        )


def test_notes_are_manual_escaped_and_require_reasons():
    request = example_request()
    request["title"] = "<img src=x onerror=alert(1)>"
    result = review(request)
    note = {
        "model_id": "model-a",
        "decision": "needs_evidence",
        "text": "<script>alert(1)</script>",
        "fingerprint": result["fingerprint"],
    }
    files, _ = build_bundle(request, result["fingerprint"], [note])
    assert b"<script>" not in files["report.html"]
    assert b"&lt;script&gt;" in files["report.html"]
    assert b"<img src=x" not in files["report.html"]
    assert json.loads(files["review-notes.json"])["notes"][0]["origin"] == "manual caller opinion"
    note["text"] = " "
    with pytest.raises(ValueError, match="reason"):
        build_bundle(request, result["fingerprint"], [note])


def test_existing_output_and_atomic_failure_leave_user_files_intact(tmp_path, monkeypatch):
    from forecast_review_workbench import exporter

    folder = tmp_path / "existing"
    folder.mkdir()
    original = folder / "original.txt"
    original.write_text("user evidence")
    with pytest.raises(FileExistsError):
        write_bundle({"report.html": b"new"}, folder)
    assert original.read_text() == "user evidence"
    new = tmp_path / "new"

    def fail(*args):
        raise OSError("simulated final publication failure")

    monkeypatch.setattr(exporter, "_publish_new", fail)
    with pytest.raises(OSError):
        write_bundle({"report.html": b"new"}, new)
    assert not new.exists()
