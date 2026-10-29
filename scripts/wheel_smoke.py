"""Run from an installed wheel, without build-tree imports or vcpkg PATH entries."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def check_junit(path):
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    assert cases, "No native tests executed"
    for case in cases:
        assert case.find("skipped") is None, f"Release gate cannot skip {case.attrib}"
        assert case.find("failure") is None and case.find("error") is None, case.attrib
    print(f"PASS: {len(cases)} tests, no failures/errors/skips")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path)
    args = parser.parse_args()
    if args.junit:
        check_junit(args.junit)
        return
    os.environ.pop("PYTHONPATH", None)
    os.environ.pop("LD_LIBRARY_PATH", None)
    if sys.platform == "win32":
        system = Path(os.environ["SystemRoot"])
        os.environ["PATH"] = os.pathsep.join(
            map(str, [system / "System32", system, Path(sys.executable).parent])
        )
    import iimt
    from iimt import _control, _model, _viewer
    from iimt.config import Arm, sdk_path
    from iimt.mock import MockRobot

    for module in (iimt, _control, _model, _viewer):
        assert "site-packages" in str(Path(module.__file__)), module.__file__
    library = Path(sdk_path())
    assert library.is_file() and "site-packages" in str(library), library
    with MockRobot(positions=[0.0] * 6) as mock:
        core = _control.Controller(
            [Arm("wheel", mock.host, mock.port, enable_motion=True).to_dict()]
        )
        core.connect()
        try:
            core.execute([0.0, 0.2], [[0.0] * 6, [0.01] * 6], time.time_ns() + 200_000_000)
            deadline = time.monotonic() + 5
            while core.result()["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert core.result()["status"] == "succeeded", core.result()
            assert core.diagnostics()["arms"][0]["sends"] > 0
        finally:
            core.close()
    sdk = ctypes.CDLL(str(library))
    for symbol in (
        "API_Login",
        "API_Logout",
        "API_Servoj",
        "API_Stop",
        "API_ClearUnfinishedTrajectory",
    ):
        assert getattr(sdk, symbol)
    print(
        "PASS: installed wheel imports, vendor dynamic loading, actual SDK/local TCP mock motion and stop"
    )


if __name__ == "__main__":
    main()
