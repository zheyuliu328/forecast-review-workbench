"""Independent fixed-fixture check of a downloaded public forecast bundle.
No project imports; no authentication, coverage-universe or model-approval claim.
"""

import argparse
import csv
import hashlib
import io
import json
from decimal import Decimal, localcontext
from pathlib import Path
from zipfile import ZipFile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("bundle", type=Path, help="ZIP exported from the original hidden-deterioration example")
SOURCE = parser.parse_args().bundle


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def verify(blobs):
    def table(name):
        return list(csv.DictReader(io.StringIO(blobs[name].decode("utf-8-sig"))))

    manifest = json.loads(blobs["manifest.json"])
    require(set(manifest["files_sha256"]) == set(blobs) - {"manifest.json"}, "Incomplete digest inventory")
    for name, expected in manifest["files_sha256"].items():
        require(hashlib.sha256(blobs[name]).hexdigest() == expected, "Digest mismatch: " + name)
    observations = table("evaluation-rows.csv")
    require(len(observations) == 4, "Expected four original example observations")
    keys = [(r["origin"], r["period"], r["entity"]) for r in observations]
    require(len(set(keys)) == 4, "Duplicate evaluation keys")
    require({r["entity"] for r in observations} == {"Large", "Small"}, "Unexpected entities")
    checks = []
    with localcontext() as context:
        context.prec = 100

        def close(actual, expected, field):
            value = Decimal(actual)
            require(value.is_finite(), "Non-finite value: " + field)
            require(abs(value - expected) <= Decimal("1e-37") * max(Decimal(1), abs(expected)), field)
            checks.append(field)

        def metrics(rows, model):
            errors = [Decimal(r["prediction:" + model]) - Decimal(r["actual"]) for r in rows]
            for r, e in zip(rows, errors):
                close(r["residual:" + model], e, "row residual " + model)
            n = Decimal(len(errors))
            return {
                "mae": sum(abs(e) for e in errors) / n,
                "rmse": (sum(e * e for e in errors) / n).sqrt(),
                "bias": sum(errors) / n,
            }

        common = [r for r in observations if r["included_in_common_sample"] == "True"]
        require(len(common) == 4, "Expected four common observations")
        for name in ["metrics.csv", "horizon-metrics.csv", "group-metrics.csv"]:
            reports = table(name)
            require(len(reports) == (6 if name == "group-metrics.csv" else 3), "Wrong metric row count")
            identities = {(r.get("entity", ""), r.get("horizon", ""), r["model_id"]) for r in reports}
            expected_ids = {
                (entity, horizon, model)
                for entity in (["Large", "Small"] if name == "group-metrics.csv" else [""])
                for horizon in ([""] if name == "metrics.csv" else ["1"])
                for model in ("a", "b", "baseline")
            }
            require(identities == expected_ids, "Missing or duplicated metric identities")
            for report in reports:
                selected = [
                    r
                    for r in common
                    if ("horizon" not in report or r["horizon"] == report["horizon"])
                    and ("entity" not in report or r["entity"] == report["entity"])
                ]
                require(len(selected) == int(report.get("n", report.get("common"))), "Metric sample size")
                expected = metrics(selected, report["model_id"])
                for metric, value in expected.items():
                    close(report[metric], value, name + " " + report["model_id"] + " " + metric)
                if name == "group-metrics.csv":
                    base = metrics(selected, "baseline")
                    for metric in ("mae", "rmse"):
                        gain = (base[metric] - expected[metric]) / base[metric] * 100
                        close(report[metric + "_gain_pct"], gain, "group gain " + metric)
    return len(checks)


with ZipFile(SOURCE) as archive:
    members = archive.infolist()
    if len(members) > 100 or sum(item.file_size for item in members) > 50 * 1024 * 1024:
        raise ValueError("Bundle exceeds this fixed-example checker size limit.")
    if len({item.filename for item in members}) != len(members):
        raise ValueError("Duplicate ZIP entries are ambiguous.")
    blobs = {name: archive.read(name) for name in archive.namelist()}
count = verify(blobs)
# Negative control: alter one prediction, then recompute its self-declared digest.
# A consistent hash manifest alone must not make the inconsistent metrics pass.
changed = dict(blobs)
changed["evaluation-rows.csv"] = changed["evaluation-rows.csv"].replace(b"1000,1050,50", b"1000,1060,50", 1)
require(
    changed["evaluation-rows.csv"] != blobs["evaluation-rows.csv"], "Expected original example row absent"
)
manifest = json.loads(changed["manifest.json"])
manifest["files_sha256"]["evaluation-rows.csv"] = hashlib.sha256(changed["evaluation-rows.csv"]).hexdigest()
changed["manifest.json"] = json.dumps(manifest).encode()
try:
    verify(changed)
except ValueError as failure:
    detected = str(failure)
else:
    raise ValueError("Inconsistent source row was not detected")
result = {
    "source_zip_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "independent_numeric_checks": count,
    "arithmetic_precision": 100,
    "comparison_tolerance": "1e-37 relative/absolute for reported decimal rounding",
    "negative_control_detected": detected,
    "project_engine_imported": False,
    "scope": "One invented fixture: residuals, aggregate/horizon/group metrics and baseline gains.",
    "limits": [
        "Hashes identify bytes, not authorship or authenticity.",
        "Declared expected universe and original input files are not reconstructed.",
        "No new model validation, blind test or human adoption evidence.",
    ],
}
print(json.dumps(result))
