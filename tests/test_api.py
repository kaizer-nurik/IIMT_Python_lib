import time
from pathlib import Path

import numpy as np
import pytest

from iimt import JOINTS, Robot, Trajectory, ci05_scene
from iimt.mock import DEFAULT_Q, MockRobot


def trajectory(names=JOINTS, duration=0.25):
    q = np.array(DEFAULT_Q)
    goal = q.copy()
    goal[0] += 0.01
    return Trajectory([0.0, duration], [q, goal], list(names))


def test_python_subprocess_lifecycle_and_execution():
    with MockRobot() as mock:
        robot = Robot.single(mock.host, port=mock.port, scene=False, enable_motion=True)
        try:
            robot.connect(viewer=False)
            assert robot.get_state()["arms"][0]["valid"]
            future = robot.execute_trajectory(trajectory(), start_delay=0.15, check_collision=False)
            result = future.wait(4)
            assert result["status"] == "succeeded"
            assert len(future.samples) > 10
            assert all(row["goal_id"] == future.goal_id for row in future.samples)
            size = len(future.samples)
            future.poll()
            assert len(future.samples) == size
        finally:
            robot.close()


def test_prepared_cancel_cannot_commit():
    with MockRobot() as mock:
        robot = Robot.single(mock.host, port=mock.port, enable_motion=True)
        try:
            robot.connect(viewer=False)
            ticket = robot._call("prepare", trajectory().to_dict())
            robot.cancel()
            with pytest.raises(RuntimeError, match="cancelled"):
                robot._call("execute_prepared", ticket, time.time_ns() + 500_000_000)
            assert robot.diagnostics()["arms"][0]["sends"] == 0
        finally:
            robot.close()


def test_csv_read_preserves_positions_times_without_derivatives():
    path = Path(__file__).parents[1] / "data/trajectory_both_TimeGrid_30Hz.csv"
    t = Trajectory.from_csv(path, JOINTS)
    original = np.genfromtxt(path, delimiter=",", names=True)
    assert np.array_equal(t.times, original["t"])
    assert np.array_equal(t.positions[:, 0], original["left_q1_rad"])
    assert t.velocities is None and t.accelerations is None


def test_models_mounts_and_csv_start():
    scene = ci05_scene(dual=True)
    model = scene.model()
    assert model.check(DEFAULT_Q * 2)["valid"]
    poses = model.transforms(DEFAULT_Q * 2)
    assert np.allclose(
        np.array(poses["right_base_link"])[:3, 3], [-0.0008297, -0.00059, -0.0001261], atol=1e-8
    )


def test_unknown_joint_or_partial_arm_rejected():
    with pytest.raises(ValueError):
        trajectory().reordered(["unknown"] * 6)
    with pytest.raises(ValueError):
        Trajectory([0, 0], np.zeros((2, 6)), list(JOINTS))
    with pytest.raises(ValueError):
        Trajectory([0, 1], np.full((2, 6), np.nan), list(JOINTS))


def test_abort_keeps_partial_utc_plots(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    from iimt.plotting import plot_execution

    with MockRobot() as mock:
        robot = Robot.single(
            mock.host,
            port=mock.port,
            scene=False,
            enable_motion=True,
            state_timeout=0.08,
            read_timeout=0.02,
        )
        try:
            robot.connect(viewer=False)
            motion = robot.execute_trajectory(
                trajectory(duration=2), start_delay=0.1, check_collision=False
            )
            deadline = time.monotonic() + 2
            while robot.diagnostics()["arms"][0]["sends"] < 3:
                assert time.monotonic() < deadline
                time.sleep(0.01)
            mock.set_faults(read_delay=0.3)
            result = motion.wait(4, raise_on_error=False)
            assert result["status"] == "aborted"
            figures, metrics = plot_execution(motion, tmp_path)
            assert figures and metrics["arm"]["samples"] > 0
            assert (tmp_path / "arm.png").stat().st_size > 1000
            assert (tmp_path / "metadata.json").exists()
            assert figures[0].axes[-1].get_xlabel() == "UTC timestamp"
            for figure in figures:
                plt.close(figure)
        finally:
            robot.close()
