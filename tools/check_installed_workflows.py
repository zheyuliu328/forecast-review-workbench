"""Exercise both new installed CLI workflows outside the source checkout."""

import base64
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from forecast_review_workbench.engine import review
from forecast_review_workbench.example import group_example_request
from forecast_review_workbench.experiments import experiment_example
from forecast_review_workbench.exporter import build_bundle, bundle_zip
from forecast_review_workbench.reconciliation import reconciliation_example


def main():
    with TemporaryDirectory(prefix="frw-installed-") as temporary:
        directory = Path(temporary)
        commands = [("experiment", experiment_example(), 0), ("reconcile", reconciliation_example(), 1)]
        for workflow, request, expected_exit in commands:
            settings = directory / f"{workflow}.json"
            settings.write_text(json.dumps(request), encoding="utf-8")
            output = directory / workflow
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "forecast_review_workbench.server",
                    f"--{workflow}",
                    str(settings),
                    "--output",
                    str(output),
                ],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != expected_exit:
                raise RuntimeError(completed.stderr or completed.stdout)
            result = json.loads((output / "results.json").read_text())
            if workflow == "experiment":
                assert len(result["candidates"]) == 17 and result["stage"] == "development"
                assert result["selected_on_development"] is not None
            else:
                assert result["summary"]["breach"] == 2 and result["summary"]["group_attention"] == 1
            assert (output / "report.html").is_file()
        request = group_example_request()
        request["accept_common_sample"] = True
        files, _ = build_bundle(request, review(request)["fingerprint"])
        bundle = directory / "original.zip"
        bundle.write_bytes(bundle_zip(files))
        paths = {}
        for source in [request["actual"], *request["candidates"], request["baseline"]]:
            identifier = source["id"]
            original = directory / f"{identifier}.csv"
            original.write_bytes(base64.b64decode(source["file"]["content_base64"]))
            paths[identifier] = {"path": original.name}
        source_map = directory / "sources.json"
        source_map.write_text(json.dumps({"schema_version": 1, "sources": paths}))
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "forecast_review_workbench.replay",
                str(bundle),
                "--sources",
                str(source_map),
                "--output",
                str(directory / "replayed"),
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout)
        verification = json.loads((directory / "replayed" / "replay-verification.json").read_text())
        assert verification["status"] == "reproduced" and verification["semantic_results_equal"]
        print("Installed experiment, reconciliation and original-source replay passed outside the checkout.")


if __name__ == "__main__":
    main()
