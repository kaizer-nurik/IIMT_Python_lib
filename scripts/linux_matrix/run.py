"""Build genuine native Linux ABI wheels and gate each in a fresh interpreter.

Requires uv, the native CMake dependencies, and Xvfb. No robot hardware is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / ".build/linux-matrix"
RESULTS = ROOT / "results/python-matrix/linux"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv")
    parser.add_argument(
        "--versions", nargs="+", default=["3.10", "3.11", "3.12", "3.13", "3.14", "3.15"]
    )
    args = parser.parse_args()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("LD_LIBRARY_PATH", None)
    env.update(UV_PYTHON_INSTALL_DIR=str(BUILD / "python"), CMAKE_BUILD_PARALLEL_LEVEL="2")
    RESULTS.mkdir(parents=True, exist_ok=True)
    summary = {}
    for version in args.versions:
        output = RESULTS / version
        output.mkdir(exist_ok=True)
        result = summary[version] = {"status": "running", "stages": {}}

        def run(stage, command):
            start = time.monotonic()
            with (output / f"{stage}.log").open("w") as log:
                log.write("COMMAND: " + repr(list(map(str, command))) + "\n")
                log.flush()
                proc = subprocess.run(
                    list(map(str, command)), cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
                )
            result["stages"][stage] = {
                "returncode": proc.returncode,
                "seconds": round(time.monotonic() - start, 2),
            }
            (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2))
            if proc.returncode:
                raise RuntimeError(f'{stage} failed; see {output / (stage + ".log")}')

        try:
            venv = BUILD / f"build-{version}"
            run("venv", [args.uv, "venv", "--clear", "--python", version, venv])
            python = venv / "bin/python"
            run(
                "build-dependencies",
                [
                    args.uv,
                    "pip",
                    "install",
                    "--python",
                    python,
                    "pip",
                    "scikit-build-core>=0.10,<2",
                    "pybind11>=3.1,<4",
                    "auditwheel",
                    "patchelf",
                ],
            )
            env["PATH"] = str(venv / "bin") + os.pathsep + os.environ.get("PATH", "")
            env["SKBUILD_BUILD_DIR"] = str(BUILD / f"cmake-{version}")
            staging = BUILD / f"wheels-{version}"
            run(
                "build",
                [
                    python,
                    ROOT / "scripts/build_wheels.py",
                    "--output",
                    staging,
                    "--platform",
                    "manylinux_2_39_x86_64",
                ],
            )
            wheels = list(staging.glob("*.whl"))
            assert len(wheels) == 1, wheels
            wheel = wheels[0]
            abi = "cp" + version.replace(".", "")
            assert f"-{abi}-{abi}-manylinux_2_39_x86_64.whl" in wheel.name, wheel.name
            result["wheel"] = wheel.name
            result["sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
            testvenv = BUILD / f"test-{version}"
            run("test-venv", [args.uv, "venv", "--clear", "--python", version, testvenv])
            testpython = testvenv / "bin/python"
            env["PATH"] = str(testvenv / "bin") + os.pathsep + os.environ.get("PATH", "")
            run(
                "install",
                [
                    args.uv,
                    "pip",
                    "install",
                    "--python",
                    testpython,
                    wheel,
                    "pytest>=8",
                    "matplotlib>=3.7",
                    "pandas>=2",
                ],
            )
            run(
                "identity",
                [
                    testpython,
                    "-c",
                    'import sys, sysconfig, iimt; print(sys.version); print(sysconfig.get_config_var("SOABI")); print(iimt.__file__); assert not sysconfig.get_config_var("Py_GIL_DISABLED")',
                ],
            )
            run("wheel-smoke", [testpython, ROOT / "scripts/wheel_smoke.py"])
            junit = output / "tests.xml"
            run("tests", [testpython, "-m", "pytest", "-q", ROOT / "tests", f"--junitxml={junit}"])
            run("zero-skips", [testpython, ROOT / "scripts/wheel_smoke.py", "--junit", junit])
            run("gui", ["xvfb-run", "-a", testpython, ROOT / "scripts/linux_matrix/gui_smoke.py"])
            destination = ROOT / "wheelhouse" / wheel.name
            destination.write_bytes(wheel.read_bytes())
            result["status"] = "passed"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
        (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return int(any(result["status"] != "passed" for result in summary.values()))


if __name__ == "__main__":
    raise SystemExit(main())
