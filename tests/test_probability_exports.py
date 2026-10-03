import copy
import hashlib
import json

import pytest

from forecast_review_workbench.example import probability_example
from forecast_review_workbench.probabilities import review_probabilities
from forecast_review_workbench.probability_exports import build_probability_bundle


def test_probability_bundle_cutoff_replay_and_integrity():
    request = probability_example()
    request["accept_common_sample"] = True
    files, result = build_probability_bundle(request)
    assert result["common"] == 2
    assert result["metrics"]["a"]["brier"] == "0.0625"
    assert result == review_probabilities(json.loads(files["request.json"]))
    manifest = json.loads(files["manifest.json"])
    for name, digest in manifest["files_sha256"].items():
        assert hashlib.sha256(files[name]).hexdigest() == digest
    changed = copy.deepcopy(request)
    changed["evaluation_as_of"] = "2025-01-04"
    with pytest.raises(ValueError, match="changed"):
        build_probability_bundle(changed, result["fingerprint"])
    files, later = build_probability_bundle(changed)
    assert later["common"] == 3
    assert later["metrics"]["a"]["brier"] == "0.375"
    assert later["metrics"]["a"]["log_loss_status"] == "infinite"
    assert later["metrics"]["a"]["impossible_events"] == 1
    assert b"Infinite" in files["report.html"]
    changed["accept_common_sample"] = False
    _, unaccepted = build_probability_bundle(changed)
    assert all(value is None for value in unaccepted["metrics"].values())
