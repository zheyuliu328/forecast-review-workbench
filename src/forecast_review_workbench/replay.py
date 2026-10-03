"""Replay a downloaded forecast review against explicitly supplied original files.

This checks reproducibility with the installed engine, not independent model accuracy
or source authenticity. The archive never supplies paths to open on this computer.
"""

import argparse
import base64
import hashlib
import io
import json
import stat
import sys
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .exporter import build_bundle, write_bundle
from .server import load_json
from .tableio import MAX_BYTES

MAX_BUNDLE = 50 * 1024 * 1024


def _read(path, limit):
    path = Path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError(f"Select a regular file of at most {limit} bytes: {path}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    after = path.stat()
    if any(
        getattr(before, key) != getattr(after, key)
        for key in ("st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    ):
        raise ValueError(f"File changed during reading; use a stable copy: {path}")
    if len(data) > limit:
        raise ValueError(f"File exceeds the {limit}-byte limit: {path}")
    return data


def _archive(path):
    raw = _read(path, MAX_BUNDLE)
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (
                len(entries) > 100
                or len(set(names)) != len(names)
                or sum(entry.file_size for entry in entries) > MAX_BUNDLE
                or any(
                    entry.is_dir()
                    or entry.flag_bits & 1
                    or "/" in entry.filename
                    or "\\" in entry.filename
                    or entry.filename in (".", "..")
                    for entry in entries
                )
            ):
                raise ValueError("Archive has unsafe, duplicate, encrypted or oversized entries.")
            blobs = {name: archive.read(name) for name in names}
    except (BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Select an unencrypted valid forecast-review ZIP.") from exc
    required = {"manifest.json", "config.json", "results.json", "review-notes.json"}
    if not required <= set(blobs):
        raise ValueError("Unsupported bundle: forecast review metadata is missing.")
    manifest = load_json(blobs["manifest.json"])
    hashes = manifest.get("files_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(blobs) - {"manifest.json"}:
        raise ValueError("Manifest must inventory every bundle member exactly once.")
    for name, digest in hashes.items():
        if hashlib.sha256(blobs[name]).hexdigest() != digest:
            raise ValueError(f"Bundle digest mismatch: {name}")
    return blobs, manifest, hashlib.sha256(raw).hexdigest()


def replay_bundle(bundle, source_map):
    """Return a newly generated report plus explicit original-versus-replay statuses."""
    blobs, manifest, bundle_hash = _archive(bundle)
    config = load_json(blobs["config.json"])
    saved = load_json(blobs["results.json"])
    notes = load_json(blobs["review-notes.json"])
    version = config.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Unsupported bundle: explicit forecast schema_version 1 or 2 is required.")
    if any(item.get("fingerprint") != saved.get("fingerprint") for item in (config, manifest, notes)):
        raise ValueError("Bundle metadata fingerprints disagree.")
    mapping = load_json(_read(source_map, 1024 * 1024))
    if (
        type(mapping.get("schema_version")) is not int
        or mapping["schema_version"] != 1
        or not isinstance(mapping.get("sources"), dict)
    ):
        raise ValueError("Source map needs schema_version 1 and a sources object keyed by source ID.")
    sources = config.get("sources")
    if not isinstance(sources, list) or not 2 <= len(sources) <= 7:
        raise ValueError("Bundle source inventory is missing or unsupported.")
    identifiers = [source["id"] for source in sources]
    if len(set(identifiers)) != len(identifiers) or set(mapping["sources"]) != set(identifiers):
        raise ValueError("Source map must contain every declared source ID, with no extra IDs.")
    request = {
        "schema_version": version,
        "title": saved["title"],
        "scope": config["scope"],
        "contract": config["contract"],
        "segments": config.get("segments", []),
        "accept_common_sample": config["accepted_common_sample"],
        "candidates": [],
    }
    input_hashes = []
    total_bytes = 0
    for source in sources:
        identifier = source["id"]
        supplied = mapping["sources"][identifier]
        if (
            not isinstance(supplied, dict)
            or set(supplied) != {"path"}
            or not isinstance(supplied["path"], str)
        ):
            raise ValueError(f"{identifier}: supply exactly one original file path.")
        path = Path(source_map).absolute().parent / supplied["path"]
        content = _read(path, MAX_BYTES)
        total_bytes += len(content)
        if total_bytes > 40 * 1024 * 1024:
            raise ValueError("Combined original files exceed 40 MiB.")
        digest = hashlib.sha256(content).hexdigest()
        if digest != source["sha256"]:
            raise ValueError(f"{identifier}: original file SHA-256 differs from the report.")
        definition = {key: source[key] for key in ("id", "name", "mapping", "contract", "source_note")}
        definition["file"] = {
            "name": source["file_name"],
            "content_base64": base64.b64encode(content).decode(),
        }
        definition["sheet"] = source["sheet"]
        definition["header_row"] = source["header_row"]
        if source["role"] == "candidate":
            request["candidates"].append(definition)
        elif source["role"] in ("actual", "baseline") and source["role"] not in request:
            request[source["role"]] = definition
        else:
            raise ValueError(f"{identifier}: invalid or repeated source role.")
        input_hashes.append({"id": identifier, "sha256": digest})
    expected_inputs = [
        {"id": source["id"], "file_name": source["file_name"], "sha256": source["sha256"]}
        for source in sources
    ]
    if manifest.get("inputs") != expected_inputs:
        raise ValueError("Manifest input inventory disagrees with source metadata.")
    # The archived fingerprint must also agree with the reconstructed input contract.
    files, result = build_bundle(request, saved["fingerprint"], notes.get("notes"))
    regenerated = load_json(files["manifest.json"])
    provenance_names = {"browser-build.json", "replay-verification.json"}
    # These record the earlier execution environment, not native calculations.
    # Unknown extra files still count as differences.
    for name in provenance_names & set(blobs):
        load_json(blobs[name])
    names = sorted((set(files) | set(blobs)) - {"manifest.json"} - provenance_names)
    differences = [name for name in names if files.get(name) != blobs.get(name)]
    semantic_equal = result == saved
    verification = {
        "schema_version": 1,
        "status": "reproduced" if not differences and semantic_equal else "different",
        "bundle_sha256": bundle_hash,
        "bundle_integrity": "passed",
        "original_source_hashes": input_hashes,
        "input_fingerprint": result["fingerprint"],
        "semantic_results_equal": semantic_equal,
        "different_files": differences,
        "archived_code_sha256": manifest.get("source_code_sha256"),
        "installed_code_sha256": regenerated["source_code_sha256"],
        "same_recorded_code": manifest.get("source_code_sha256") == regenerated["source_code_sha256"],
        "comparison_ready": result["comparison_ready"],
        "compared_artifacts": names,
        "preserved_browser_build": "browser-build.json" in blobs,
        "prior_replay_record_sha256": (
            hashlib.sha256(blobs["replay-verification.json"]).hexdigest()
            if "replay-verification.json" in blobs
            else None
        ),
        "replay_environment": {"execution": "Installed native Python", "python": sys.version},
        "limits": [
            "Reproducibility uses the installed engine; it is not independent numerical validation.",
            "Hashes match supplied bytes, not authorship, authentic market data or truthful timing.",
            "A reproduced report can still have missing data or an unaccepted common sample.",
            "Changed code can legitimately change results; differences are never silently accepted.",
            "The original ZIP and original files are not modified or copied into this output.",
        ],
    }
    if "browser-build.json" in blobs:
        files["browser-build.json"] = blobs["browser-build.json"]
        regenerated["files_sha256"]["browser-build.json"] = hashlib.sha256(
            files["browser-build.json"]
        ).hexdigest()
    files["replay-verification.json"] = (json.dumps(verification, indent=2) + "\n").encode()
    # Keep the regenerated report bundle complete and internally hash-consistent.
    regenerated["files_sha256"]["replay-verification.json"] = hashlib.sha256(
        files["replay-verification.json"]
    ).hexdigest()
    files["manifest.json"] = (json.dumps(regenerated, indent=2) + "\n").encode()
    return files, verification


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Downloaded forecast review ZIP (schema 1 or 2)")
    parser.add_argument("--sources", type=Path, required=True, help="Source-ID to original-path JSON map")
    parser.add_argument("--output", type=Path, required=True, help="New directory; never replaced")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError("Choose a new output directory; existing paths are never replaced.")
        files, verification = replay_bundle(args.bundle, args.sources)
        write_bundle(files, args.output)
        print(json.dumps(verification, indent=2))
        return 0 if verification["status"] == "reproduced" else 1
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as exc:
        parser.exit(2, f"Replay failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
