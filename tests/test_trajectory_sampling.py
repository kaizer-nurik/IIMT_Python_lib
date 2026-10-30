"""Offline CSV preparation: no SDK calls, no implicit smoothing or new derivatives."""

import csv

import numpy as np
import pytest

from iimt import JOINTS, Trajectory


def make_trajectory(times, *, derivatives=False):
    times = np.asarray(times)
    positions = np.outer(times - times[0], np.arange(1, 7) * 0.01)
    zeros = np.zeros_like(positions) if derivatives else None
    return Trajectory(times, positions, list(JOINTS), zeros, zeros)


def test_csv_arbitrary_timestamps_and_explicit_missing_time_rate(tmp_path):
    path = tmp_path / "input.csv"
    times = [0.0, 0.01, 0.025, 0.12]
    columns = [f"left_q{i}_rad" for i in range(1, 7)]
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["seconds", *columns])
        writer.writerows([t, *([t] * 6)] for t in times)
    original = Trajectory.from_csv(path, JOINTS, time_column="seconds")
    assert original.times.tolist() == times
    generated = Trajectory.from_csv(path, JOINTS, time_column=None, sample_rate=100)
    np.testing.assert_allclose(generated.times, [0, 0.01, 0.02, 0.03])
    assert np.array_equal(original.positions, generated.positions)
    assert generated.velocities is generated.accelerations is None
    with pytest.raises(ValueError, match="not both"):
        Trajectory.from_csv(path, JOINTS, time_column="seconds", sample_rate=100)
    with pytest.raises(ValueError, match="sample_rate"):
        Trajectory.from_csv(path, JOINTS, time_column=None)


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_invalid_sampling_and_time_scale(bad, tmp_path):
    trajectory = make_trajectory([0, 1])
    with pytest.raises(ValueError, match="positive|finite"):
        trajectory.resampled(bad)
    with pytest.raises(ValueError, match="positive|finite"):
        trajectory.time_scaled(bad)
    with pytest.raises(ValueError, match="sample_rate"):
        Trajectory.from_csv(tmp_path / "unused.csv", JOINTS, time_column=None, sample_rate=bad)


def test_100_to_30_exact_grid_and_original_row_selection():
    original = make_trajectory(np.arange(101) / 100)
    exact = original.resampled(30)
    selected = original.resampled(30, mode="select")
    np.testing.assert_allclose(exact.times, np.arange(31) / 30)
    np.testing.assert_allclose(exact.positions[:, 0], exact.times * 0.01)
    assert exact.velocities is exact.accelerations is None
    assert len(selected.times) == 31
    assert set(selected.times).issubset(original.times)
    np.testing.assert_allclose(np.diff(selected.times)[:3], [0.03, 0.04, 0.03])
    indices = np.searchsorted(original.times, selected.times)
    assert np.array_equal(selected.positions, original.positions[indices])
    assert np.array_equal(original.times, np.arange(101) / 100)


@pytest.mark.parametrize("mode", ["interpolate", "select"])
def test_resampling_retains_endpoints_nonzero_origin_and_short_tail(mode):
    original = make_trajectory([2.0, 2.04, 2.07, 2.105])
    resampled = original.resampled(30, mode=mode)
    assert resampled.times[0] == 2.0 and resampled.times[-1] == 2.105
    assert np.all(np.diff(resampled.times) > 0)
    assert np.array_equal(resampled.positions[[0, -1]], original.positions[[0, -1]])
    if mode == "interpolate":
        assert len(resampled.times) == 5
        assert resampled.times[-1] - resampled.times[-2] == pytest.approx(0.005)


def test_single_point_and_very_short_span():
    point = make_trajectory([0.2])
    copy = point.resampled(30)
    assert np.array_equal(copy.times, point.times)
    assert not np.shares_memory(copy.positions, point.positions)
    tiny = make_trajectory([0.0, 1e-16]).resampled(30)
    assert tiny.times.tolist() == [0, 1e-16]
    assert np.array_equal(point.sample(0.2, derivative=1), np.zeros(6))


def test_time_scaling_does_not_change_positions_or_add_derivatives():
    original = make_trajectory(np.arange(31) / 30)
    slow = original.time_scaled(4)
    assert np.array_equal(slow.times, original.times * 4)
    assert np.array_equal(slow.positions, original.positions)
    assert slow.velocities is slow.accelerations is None
    for t in (0.0, 0.21, 0.5, 1.0):
        np.testing.assert_allclose(slow.sample(t * 4), original.sample(t))
        np.testing.assert_allclose(
            slow.sample(t * 4, derivative=1), original.sample(t, derivative=1) / 4
        )
    assert not np.shares_memory(slow.positions, original.positions)


@pytest.mark.parametrize("quintic", [False, True])
def test_polynomial_derivatives_and_resampling(quintic):
    q = np.tile([0.0, 1.0], (6, 1)).T
    zeros = np.zeros_like(q)
    original = Trajectory([0, 1], q, list(JOINTS), zeros, zeros if quintic else None)
    for t in (0, 0.2, 0.5, 0.9, 1):
        if quintic:
            expected = [
                10 * t**3 - 15 * t**4 + 6 * t**5,
                30 * t**2 - 60 * t**3 + 30 * t**4,
                60 * t - 180 * t**2 + 120 * t**3,
            ]
        else:
            expected = [3 * t**2 - 2 * t**3, 6 * t - 6 * t**2, 6 - 12 * t]
        for order, value in enumerate(expected):
            np.testing.assert_allclose(original.sample(t, derivative=order), value, atol=1e-12)
    sampled = original.resampled(10)
    slow = sampled.time_scaled(3)
    for t in (0.13, 0.47, 0.83):
        for order in (0, 1, 2):
            np.testing.assert_allclose(
                sampled.sample(t, derivative=order),
                original.sample(t, derivative=order),
                atol=1e-10,
            )
            np.testing.assert_allclose(
                slow.sample(t * 3, derivative=order),
                original.sample(t, derivative=order) / 3**order,
                atol=1e-10,
            )


def test_sampling_budgets_and_outside_derivatives():
    trajectory = make_trajectory([0, 1])
    with pytest.raises(ValueError, match="million"):
        trajectory.resampled(1e9)
    with pytest.raises(ValueError, match="mode"):
        trajectory.resampled(30, mode="unknown")
    for t in (-1, 2):
        assert np.array_equal(trajectory.sample(t, derivative=1), np.zeros(6))
    with pytest.raises(ValueError, match="derivative"):
        trajectory.sample(0.5, derivative=3)
