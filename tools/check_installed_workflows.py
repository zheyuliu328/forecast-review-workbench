"""Exercise both new installed CLI workflows outside the source checkout."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from forecast_review_workbench.experiments import experiment_example
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
        print("Both installed workflows produced complete evidence outside the checkout.")


if __name__ == "__main__":
    main()
