"""Offline desired-trajectory plots; never connect to SDK or robot processes."""

import copy
from types import SimpleNamespace

import numpy as np
import pytest

from iimt import JOINTS, Arm, Trajectory
from iimt.plotting import plot_trajectory, trajectory_limit_report


def trajectory(times, first_axis, names=JOINTS):
    q = np.zeros((len(times), len(names)))
    q[:, 0] = first_axis
    return Trajectory(times, q, list(names))


def arm(name="left", names=JOINTS, **limits):
    return Arm(name, "127.0.0.1", joint_names=list(names), **limits)


@pytest.fixture
def pyplot(monkeypatch):
    monkeypatch.setenv("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


@pytest.mark.parametrize(
    "times,positions,velocity,acceleration",
    [
        ([0, 1, 2], [0, 1, 3], 2, 1),
        ([0, 1, 3], [0, 1, 5], 2, 2 / 3),
    ],
)
def test_linear_profile_uses_segment_slopes_and_midpoint_acceleration(
    times, positions, velocity, acceleration
):
    report = trajectory_limit_report(trajectory(times, positions), [arm()])["left"]
    assert report["observed"]["max_abs_velocity"][0] == pytest.approx(velocity)
    assert report["observed"]["max_abs_acceleration"][0] == pytest.approx(acceleration)
    assert report["velocity_kind"] == "segment_slope"
    assert report["acceleration_kind"] == "finite_difference_estimate"
    assert report["acceleration_available"]


def test_time_scaling_reduces_velocity_and_acceleration_without_new_payload_derivatives():
    original = trajectory([0, 0.2, 0.5, 1], [0, 0.1, 0.4, 0.6])
    slow = Trajectory(original.times * 3, original.positions, original.joint_names)
    a = trajectory_limit_report(original, [arm()])["left"]["observed"]
    b = trajectory_limit_report(slow, [arm()])["left"]["observed"]
    np.testing.assert_allclose(b["max_abs_velocity"], np.asarray(a["max_abs_velocity"]) / 3)
    np.testing.assert_allclose(b["max_abs_acceleration"], np.asarray(a["max_abs_acceleration"]) / 9)
    assert original.velocities is slow.velocities is None
    assert original.accelerations is slow.accelerations is None


def test_dual_joint_name_mapping_and_partial_complete_arm():
    left, right = ["left_" + j for j in JOINTS], ["right_" + j for j in JOINTS]
    arms = [arm("left", left), arm("right", right)]
    names = (left + right)[::-1]
    q = np.zeros((2, 12))
    q[-1, names.index(left[1])] = 0.2
    q[-1, names.index(right[4])] = 0.3
    report = trajectory_limit_report(Trajectory([0, 1], q, names), arms)
    assert report["left"]["joint_names"] == left
    assert report["left"]["observed"]["max_abs_velocity"] == [0, 0.2, 0, 0, 0, 0]
    assert report["right"]["observed"]["max_abs_velocity"] == [0, 0, 0, 0, 0.3, 0]
    assert list(trajectory_limit_report(trajectory([0, 1], [0, 0.1], right), arms)) == ["right"]


def test_preview_intersects_urdf_limits_by_joint_names_without_mutation():
    configured = arm(min_position=[-2] * 6, max_position=[2] * 6, max_velocity=[2] * 6)
    before = copy.deepcopy(configured.to_dict())
    path = trajectory([0, 0.1, 0.2], [0, 0.15, 0.2])
    original = copy.deepcopy(path.to_dict())
    scene = SimpleNamespace(
        joint_names=list(JOINTS)[::-1],
        model=lambda: SimpleNamespace(
            limits=lambda: {
                "lower": [-1] * 6,
                "upper": [1, 1, 1, 1, 1, 0.1],
                "velocity": [1] * 6,
            }
        ),
    )
    result = trajectory_limit_report(path, [configured], scene=scene)["left"]
    assert result == trajectory_limit_report(path, [configured.to_dict()], scene=scene)["left"]
    assert result["limits"]["min_position"] == [-1] * 6
    assert result["limits"]["max_position"] == [0.1, 1, 1, 1, 1, 1]
    assert result["limits"]["max_velocity"] == [1] * 6
    assert result["limits"]["max_acceleration"] == configured.max_acceleration
    assert result["violations"]["max_position"] == [JOINTS[0]]
    assert result["violations"]["max_velocity"] == [JOINTS[0]]
    assert result["violations"]["max_acceleration"] == [JOINTS[0]]
    assert result["has_violations"]
    assert configured.to_dict() == before
    assert path.to_dict() == original


@pytest.mark.parametrize("count", [1, 2])
def test_short_trajectory_has_no_invented_acceleration(count, pyplot):
    path = trajectory(np.arange(count), np.arange(count) * 0.1)
    figures, report = plot_trajectory(path, [arm()])
    observed = report["left"]["observed"]
    assert observed["max_abs_acceleration"] is None
    assert report["left"]["acceleration_available"] is False
    assert len(figures) == 1 and len(figures[0].axes) == 18
    assert "No interior acceleration estimate" in figures[0].axes[2].texts[0].get_text()
    for axes in figures[0].axes:
        for line in axes.lines:
            assert np.isfinite(line.get_ydata()).all()
    assert (observed["max_abs_velocity"] is None) == (count == 1)


def test_plot_marks_exceedances_and_does_not_mutate(pyplot):
    path = trajectory([0, 1, 2], [0, 0.2, 0.8])
    configured = arm(max_position=[0.5] * 6, max_velocity=[0.3] * 6, max_acceleration=[0.2] * 6)
    before = (copy.deepcopy(path.to_dict()), copy.deepcopy(configured.to_dict()))
    figures, report = plot_trajectory(path, [configured])
    assert report == trajectory_limit_report(path, [configured])
    for axes in figures[0].axes[:3]:
        red = [line for line in axes.lines if line.get_label() == "exceeds limit"]
        assert red and red[0].get_color() == "red"
        assert len(red[0].get_xdata()) > 0
        assert len([line for line in axes.lines if line.get_linestyle() == "--"]) == 2
    assert figures[0].axes[-1].get_xlabel() == "time_from_start, s"
    assert "estimate" in figures[0].axes[2].get_title()
    assert path.to_dict() == before[0] and configured.to_dict() == before[1]


def test_explicit_derivative_plan_is_sampled_between_zero_derivative_knots(pyplot):
    path = trajectory([0, 1], [0, 1])
    path = Trajectory(
        path.times, path.positions, path.joint_names, np.zeros((2, 6)), np.zeros((2, 6))
    )
    figures, report = plot_trajectory(path, [arm()])
    result = report["left"]
    assert result["acceleration_kind"] == "sampled_polynomial"
    assert result["observed"]["max_abs_velocity"][0] == pytest.approx(1.875)
    assert result["observed"]["max_abs_acceleration"][0] > 5
    assert result["has_violations"]
    assert len(figures[0].axes[1].lines[0].get_xdata()) > 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_position", [-1] * 5),
        ("max_position", [float("nan")] * 6),
        ("max_velocity", [0] * 6),
        ("max_acceleration", [-1] * 6),
        ("min_position", [10] * 6),
    ],
)
def test_invalid_limits_rejected_without_hardware(field, value):
    with pytest.raises(ValueError):
        trajectory_limit_report(trajectory([0, 1], [0, 0.1]), [arm(**{field: value})])


def test_unknown_duplicate_or_mixed_arm_joints_rejected():
    path = trajectory([0, 1], [0, 0.1])
    with pytest.raises(ValueError, match="unknown"):
        trajectory_limit_report(path, [arm(names=["unknown_" + j for j in JOINTS])])
    with pytest.raises(ValueError, match="unique"):
        trajectory_limit_report(path, [arm(), arm("right")])
    left, right = ["left_" + j for j in JOINTS], ["right_" + j for j in JOINTS]
    with pytest.raises(ValueError, match="complete"):
        trajectory_limit_report(
            trajectory([0, 1], [0, 0.1], left[:3] + right[:3]),
            [arm("left", left), arm("right", right)],
        )
