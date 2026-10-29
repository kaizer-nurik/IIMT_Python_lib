"""Measure actual native Windows SDK dispatch against independent localhost mocks."""

import json
import os
import platform
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from iimt.config import Arm, sdk_path
from iimt.mock import MockRobot

try:
    from iimt import _control
except ImportError:
    import _control


def main():
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "runs": [],
        "clocks": {
            name: vars(time.get_clock_info(name)) for name in ("time", "monotonic", "perf_counter")
        },
    }
    for count in (1, 2):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            paths = [Path(directory) / f"arm-{i}.jsonl" for i in range(count)]
            mocks = [stack.enter_context(MockRobot(positions=[0.0] * 6, log=str(p))) for p in paths]
            configs = [
                Arm(
                    f"arm{i}",
                    mock.host,
                    mock.port,
                    enable_motion=True,
                    joint_names=[f"arm{i}_joint_{j}" for j in range(6)],
                    sdk_library=os.environ.get("IIMT_TEST_SDK", sdk_path()),
                ).to_dict()
                for i, mock in enumerate(mocks)
            ]
            core = _control.Controller(configs)
            core.connect()
            try:
                start = time.time_ns() + 500_000_000
                core.execute([0.0, 5.0], [[0.0] * (6 * count), [0.01] * (6 * count)], start)
                deadline = time.monotonic() + 12
                while core.result()["status"] == "running" and time.monotonic() < deadline:
                    time.sleep(0.01)
                result = core.result()
                diagnostics = core.diagnostics()
            finally:
                core.close()
            arms = []
            for path in paths:
                records = [json.loads(line) for line in path.read_text().splitlines()]
                stamps = [r["monotonic_ns"] for r in records if r["kind"] == "servoj"]
                intervals = np.diff(stamps) / 1e6
                arms.append(
                    {
                        "commands": len(stamps),
                        "mean_hz": 1000 / float(intervals.mean()) if intervals.size else 0,
                        "interval_ms_p50_p95_p99_max": (
                            np.percentile(intervals, [50, 95, 99, 100]).tolist()
                            if intervals.size
                            else []
                        ),
                        "reads": sum(r["kind"] == "read" for r in records),
                    }
                )
            report["runs"].append(
                {"arms": count, "result": result, "wire": arms, "diagnostics": diagnostics}
            )
    print(json.dumps(report, indent=2))
    if any(run["result"]["status"] != "succeeded" for run in report["runs"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
