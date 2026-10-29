import json
import time
from pathlib import Path

import numpy as np

from iimt import Robot, Trajectory, ci05_scene
from iimt.mock import MockRobot
from iimt.plotting import plot_execution

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "results").mkdir(exist_ok=True)


def run(dual):
    scene = ci05_scene(dual=dual)
    traj = Trajectory.from_csv(
        ROOT / "data/trajectory_both_TimeGrid_30Hz.csv",
        scene.joint_names,
        arm="both" if dual else "left",
    )
    mocks = []
    robot = None
    try:
        for i in range(2 if dual else 1):
            log = ROOT / "results" / f'wire_{"dual" if dual else "single"}_{i}.jsonl'
            log.write_text("")
            mocks.append(
                MockRobot(
                    positions=traj.positions[0, i * 6 : i * 6 + 6].tolist(), log=str(log)
                ).start()
            )
        if dual:
            robot = Robot.dual(
                mocks[0].host,
                mocks[1].host,
                left_port=mocks[0].port,
                right_port=mocks[1].port,
                scene=scene,
                enable_motion=True,
            )
        else:
            robot = Robot.single(mocks[0].host, port=mocks[0].port, scene=scene, enable_motion=True)
        robot.connect(viewer=False)
        # Plan a small valid offset and approach back to CSV start as separate goals.
        q = traj.positions[0].copy()
        q[0] += 0.015
        plan = robot.plan(q, timeout=2, scale=0.2)
        print("plan", dual, len(plan.times), plan.times[-1], flush=True)
        e = robot.execute_trajectory(plan, start_delay=0.5)
        e.wait(10)
        approach = robot.plan(traj.positions[0], timeout=2, scale=0.2)
        e = robot.execute_trajectory(approach, start_delay=0.5)
        e.wait(10)
        begin = time.time_ns()
        e = robot.execute_trajectory(traj, start_delay=3)
        print("prepared", dual, (time.time_ns() - begin) / 1e9, flush=True)
        result = e.wait(15, raise_on_error=False)
        figs, metrics = plot_execution(e, ROOT / "results" / ("dual" if dual else "single"))
        report = {
            "dual": dual,
            "result": result,
            "metrics": metrics,
            "diagnostics": robot.diagnostics(),
            "interval_clock": vars(time.get_clock_info("perf_counter")),
            "cadence": [],
        }
        for i, arm in enumerate(robot.arms):
            lines = [
                json.loads(line)
                for line in (ROOT / "results" / f"wire_{'dual' if dual else 'single'}_{i}.jsonl")
                .read_text()
                .splitlines()
            ]
            sends = [
                r
                for r in lines
                if r["kind"] == "servoj" and r["unix_ns"] >= result["start_unix_ns"] - 1_000_000
            ]
            stamps = np.array([r["unix_ns"] for r in sends], dtype=np.int64)
            steady = np.array([r["monotonic_ns"] for r in sends], dtype=np.int64)
            intervals = np.diff(steady) / 1e6
            report["cadence"].append(
                {
                    "arm": arm["name"],
                    "commands": len(sends),
                    "rate_hz": float(1e9 * (len(steady) - 1) / (steady[-1] - steady[0])),
                    "first_dispatch_offset_ms": float((stamps[0] - result["start_unix_ns"]) / 1e6),
                    "last_dispatch_nominal_s": float((stamps[-1] - result["start_unix_ns"]) / 1e9),
                    "interval_ms": dict(
                        zip(
                            ["p50", "p95", "p99", "max"],
                            map(float, [*np.percentile(intervals, [50, 95, 99]), max(intervals)]),
                        )
                    ),
                }
            )
        print(json.dumps(report, indent=2), flush=True)
        assert result["status"] == "succeeded", result
        return report
    finally:
        if robot:
            robot.close()
        for mock in mocks:
            mock.close()


if __name__ == "__main__":
    reports = [run(False), run(True)]
    (ROOT / "results/benchmark_summary.json").write_text(json.dumps(reports, indent=2))
