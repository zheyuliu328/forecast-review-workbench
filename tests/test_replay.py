import base64
import hashlib
import json

import pytest

from forecast_review_workbench.engine import review
from forecast_review_workbench.example import example_request, group_example_request, origin_example_request
from forecast_review_workbench.exporter import build_bundle, bundle_zip
from forecast_review_workbench.replay import main, replay_bundle


def inputs(tmp_path, request):
    result = review(request)
    files, _ = build_bundle(request, result["fingerprint"])
    bundle = tmp_path / "report.zip"
    bundle.write_bytes(bundle_zip(files))
    sources = [request["actual"], *request["candidates"]]
    if request.get("baseline"):
        sources.append(request["baseline"])
    paths = {}
    for i, source in enumerate(sources):
        # Identical file basenames in different folders must not identify sources.
        folder = tmp_path / str(i)
        folder.mkdir()
        path = folder / "renamed.csv"
        path.write_bytes(base64.b64decode(source["file"]["content_base64"]))
        identifier = "actual" if i == 0 else source["id"]
        paths[identifier] = {"path": str(path.relative_to(tmp_path))}
    source_map = tmp_path / "sources.json"
    source_map.write_text(json.dumps({"schema_version": 1, "sources": paths}))
    return bundle, source_map, files


@pytest.mark.parametrize("factory", [example_request, origin_example_request, group_example_request])
@pytest.mark.parametrize("accepted", [True, False])
def test_original_files_reproduce_all_artifacts_with_renamed_paths(tmp_path, factory, accepted):
    request = factory()
    request["accept_common_sample"] = accepted
    bundle, source_map, originals = inputs(tmp_path, request)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    files, result = replay_bundle(bundle, source_map)
    assert result["status"] == "reproduced"
    assert result["comparison_ready"] is accepted
    assert result["same_recorded_code"] is True
    assert result["semantic_results_equal"] is True
    for name in set(originals) - {"manifest.json"}:
        assert files[name] == originals[name]
    assert all(p.read_bytes() == content for p, content in before.items())
    manifest = json.loads(files["manifest.json"])
    assert all(hashlib.sha256(files[n]).hexdigest() == h for n, h in manifest["files_sha256"].items())


def test_wrong_missing_and_extra_originals_fail(tmp_path):
    bundle, source_map, _ = inputs(tmp_path, example_request())
    paths = json.loads(source_map.read_text())
    paths["sources"]["unused"] = {"path": "irrelevant.csv"}
    source_map.write_text(json.dumps(paths))
    with pytest.raises(ValueError, match="every declared source ID"):
        replay_bundle(bundle, source_map)
    del paths["sources"]["unused"]
    source_map.write_text(json.dumps(paths))
    (tmp_path / paths["sources"]["actual"]["path"]).write_text("different bytes")
    with pytest.raises(ValueError, match="actual: original file SHA-256"):
        replay_bundle(bundle, source_map)


def test_changed_metric_detected_even_with_rehashed_manifest(tmp_path):
    request = group_example_request()
    request["accept_common_sample"] = True
    bundle, source_map, files = inputs(tmp_path, request)
    saved = json.loads(files["results.json"])
    saved["models"][0]["metrics"]["mae"] = "999"
    files["results.json"] = json.dumps(saved).encode()
    bundle.write_bytes(bundle_zip(files))
    with pytest.raises(ValueError, match="digest mismatch: results.json"):
        replay_bundle(bundle, source_map)
    manifest = json.loads(files["manifest.json"])
    manifest["files_sha256"]["results.json"] = hashlib.sha256(files["results.json"]).hexdigest()
    files["manifest.json"] = json.dumps(manifest).encode()
    bundle.write_bytes(bundle_zip(files))
    _, result = replay_bundle(bundle, source_map)
    assert result["status"] == "different"
    assert result["semantic_results_equal"] is False
    assert result["different_files"] == ["results.json"]
    assert main([str(bundle), "--sources", str(source_map), "--output", str(tmp_path / "different")]) == 1


def test_cli_no_replace_and_success(tmp_path):
    bundle, source_map, _ = inputs(tmp_path, origin_example_request())
    output = tmp_path / "replayed"
    argv = [str(bundle), "--sources", str(source_map), "--output", str(output)]
    assert main(argv) == 0
    evidence = json.loads((output / "replay-verification.json").read_text())
    assert evidence["status"] == "reproduced"
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2


def test_conflicting_contract_is_reproducible_not_approved(tmp_path):
    request = example_request()
    request["accept_common_sample"] = True
    request["candidates"][0]["contract"]["unit"] = "EUR"
    bundle, source_map, _ = inputs(tmp_path, request)
    _, result = replay_bundle(bundle, source_map)
    assert result["status"] == "reproduced"
    assert result["comparison_ready"] is False


def test_archive_rejects_duplicate_and_path_entries(tmp_path):
    from zipfile import ZipFile

    bundle, source_map, files = inputs(tmp_path, example_request())
    for name in ["../report.html", "/report.html", "folder/report.html", "report.html"]:
        bundle.write_bytes(bundle_zip(files))
        with ZipFile(bundle, "a") as archive:
            archive.writestr(name, b"not read or extracted")
        with pytest.raises(ValueError, match="unsafe, duplicate"):
            replay_bundle(bundle, source_map)


def test_browser_provenance_is_preserved_not_recomputed(tmp_path):
    bundle, source_map, files = inputs(tmp_path, group_example_request())
    files["browser-build.json"] = b'{"execution":"Browser-local Pyodide Worker","source_commit":"test"}'
    manifest = json.loads(files["manifest.json"])
    manifest["files_sha256"]["browser-build.json"] = hashlib.sha256(files["browser-build.json"]).hexdigest()
    files["manifest.json"] = json.dumps(manifest).encode()
    bundle.write_bytes(bundle_zip(files))
    replayed, result = replay_bundle(bundle, source_map)
    assert result["status"] == "reproduced"
    assert result["preserved_browser_build"]
    assert replayed["browser-build.json"] == files["browser-build.json"]
    bundle.write_bytes(bundle_zip(replayed))
    _, repeated = replay_bundle(bundle, source_map)
    assert repeated["status"] == "reproduced"
    assert repeated["prior_replay_record_sha256"]
