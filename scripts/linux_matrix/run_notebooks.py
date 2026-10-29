"""Run notebook dependency/install checks for wheels already gated by run.py."""

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / ".build/linux-matrix"
RESULTS = ROOT / "results/python-matrix/linux"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args()
    matrix = json.loads((RESULTS / "summary.json").read_text())
    results = {}
    for version, row in matrix.items():
        if row["status"] != "passed":
            results[version] = {"status": "blocked", "reason": "native wheel gate did not pass"}
            continue
        output = RESULTS / version
        python = BUILD / f"test-{version}/bin/python"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("LD_LIBRARY_PATH", None)
        env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
        commands = {
            "notebook-install": [
                args.uv,
                "pip",
                "install",
                "--python",
                python,
                "jupyterlab>=4,<5",
                "ipykernel>=6",
                "matplotlib>=3.7",
                "pandas>=2",
                "nbformat>=5",
                "nbclient>=0.10",
            ],
            "notebook": [
                python,
                ROOT / "scripts/linux_matrix/notebook_smoke.py",
                "--output",
                output / "notebooks",
            ],
        }
        result = results[version] = {"status": "passed"}
        for stage, command in commands.items():
            with (output / f"{stage}.log").open("w") as log:
                log.write("COMMAND: " + repr(list(map(str, command))) + "\n")
                log.flush()
                proc = subprocess.run(
                    list(map(str, command)), cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
                )
            result[stage] = proc.returncode
            if proc.returncode:
                result["status"] = "failed"
                break
        (RESULTS / "notebooks.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return int(any(row["status"] != "passed" for row in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
