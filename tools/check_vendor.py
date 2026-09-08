"""Verify the packaged public kernel against its committed provenance, offline."""

import hashlib
import json
import re
from pathlib import Path


def main():
    directory = Path(__file__).resolve().parents[1] / "src/forecast_review_workbench/_vendor"
    provenance = json.loads((directory / "provenance.json").read_text())
    if not re.fullmatch(r"[a-f0-9]{40}", provenance["commit"]):
        raise ValueError("A published, immutable source commit is required.")
    if provenance["repository"] != "https://github.com/zheyuliu328/model-risk-lab":
        raise ValueError("The recorded kernel must refer to the declared public upstream.")
    for name, expected in provenance["files"].items():
        if name not in {"forecast_engine.py", "MODEL_RISK_LAB_LICENSE.txt"}:
            raise ValueError("The vendor inventory contains an unexpected file.")
        actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if actual != expected["sha256"]:
            raise ValueError(f"Vendored bytes changed: {name}. Update from reviewed public source.")
    if set(provenance["files"]) != {"forecast_engine.py", "MODEL_RISK_LAB_LICENSE.txt"}:
        raise ValueError("Kernel source and its retained license must both be accounted for.")
    print(f"Public kernel and license verified: {provenance['commit']}")


if __name__ == "__main__":
    main()
