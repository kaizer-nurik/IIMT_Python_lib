"""Desired-trajectory preview and UTC execution plots. Optional notebook extras."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_LIMIT_FIELDS = ("min_position", "max_position", "max_velocity", "max_acceleration")


def _preview_limits(trajectory, arms, scene):
    configs = [arm.to_dict() if hasattr(arm, "to_dict") else arm for arm in arms]
    names = [name for arm in configs for name in arm["joint_names"]]
    if len(set(names)) != len(names) or len({a["name"] for a in configs}) != len(configs):
        raise ValueError("Arm and joint names must be unique")
    if set(trajectory.joint_names) - set(names):
        raise ValueError("Trajectory contains unknown joints")
    urdf = scene.model().limits() if scene is not None else None
    groups = []
    for arm in configs:
        joint_names = arm["joint_names"]
        if len(joint_names) != 6:
            raise ValueError("Each arm must contain six joint names")
        limits = {name: np.array(arm[name], dtype=float, copy=True) for name in _LIMIT_FIELDS}
        if any(value.shape != (6,) or not np.isfinite(value).all() for value in limits.values()):
            raise ValueError(f"{arm['name']}: limits must contain six finite values")
        if urdf is not None:
            if set(joint_names) - set(scene.joint_names):
                raise ValueError("Scene is missing configured joints")
            indices = [scene.joint_names.index(name) for name in joint_names]
            for field, source, combine in (
                ("min_position", "lower", np.maximum),
                ("max_position", "upper", np.minimum),
                ("max_velocity", "velocity", np.minimum),
            ):
                bound = np.asarray(urdf[source], dtype=float)[indices]
                if not np.isfinite(bound).all():
                    raise ValueError("URDF limits must be finite")
                limits[field] = combine(limits[field], bound)
        if (
            np.any(limits["min_position"] >= limits["max_position"])
            or np.any(limits["max_velocity"] <= 0)
            or np.any(limits["max_acceleration"] <= 0)
        ):
            raise ValueError(f"{arm['name']}: require min < max and positive velocity/acceleration")
        present = set(joint_names) & set(trajectory.joint_names)
        if not present:
            continue
        if len(present) != 6:
            raise ValueError("Trajectory must contain each participating arm's complete six joints")
        columns = [trajectory.joint_names.index(name) for name in joint_names]
        groups.append((arm["name"], list(joint_names), columns, limits))
    return groups


def _preview_channels(trajectory):
    times, positions = trajectory.times, trajectory.positions
    if trajectory.velocities is not None:
        # Inspect inside every polynomial segment, including either side of knots.
        grid = np.unique(
            np.concatenate(
                [
                    times,
                    *[np.linspace(start, end, 33) for start, end in zip(times[:-1], times[1:])],
                    np.nextafter(times[1:], times[:-1]),
                ]
            )
        )
        channels = [
            (grid, np.array([trajectory.sample(t, derivative=d) for t in grid])) for d in range(3)
        ]
        return channels, "sampled_polynomial", "sampled_polynomial"
    dt = np.diff(times)
    velocity = np.diff(positions, axis=0) / dt[:, None]
    midpoints = times[:-1] + dt / 2
    acceleration = np.diff(velocity, axis=0) / np.diff(midpoints)[:, None]
    channels = [
        (times, positions),
        (np.repeat(times, 2)[1:-1], np.repeat(velocity, 2, axis=0)),
        (times[1:-1], acceleration),
    ]
    return channels, "segment_slope", "finite_difference_estimate"


def _preview_data(trajectory, arms, scene):
    groups = _preview_limits(trajectory, arms, scene)
    channels, velocity_kind, acceleration_kind = _preview_channels(trajectory)
    if any(not np.isfinite(values).all() for _, values in channels):
        raise ValueError("Trajectory preview derivatives overflow; check times and positions")
    report = {}
    for name, joint_names, columns, limits in groups:
        q, v, a = [values[:, columns] for _, values in channels]
        observed = {
            "min_position": q.min(axis=0),
            "max_position": q.max(axis=0),
            "max_abs_velocity": np.abs(v).max(axis=0) if len(v) else None,
            "max_abs_acceleration": np.abs(a).max(axis=0) if len(a) else None,
        }
        violations = {}
        for limit, peak in zip(_LIMIT_FIELDS, observed.values()):
            outside = (
                np.zeros(6, dtype=bool)
                if peak is None
                else (peak < limits[limit] if limit == "min_position" else peak > limits[limit])
            )
            violations[limit] = [joint for joint, bad in zip(joint_names, outside) if bad]
        report[name] = {
            "joint_names": joint_names,
            "limits": {key: value.tolist() for key, value in limits.items()},
            "observed": {
                key: None if value is None else value.tolist() for key, value in observed.items()
            },
            "violations": violations,
            "has_violations": any(violations.values()),
            "velocity_kind": velocity_kind,
            "acceleration_kind": acceleration_kind,
            "acceleration_available": bool(len(a)),
        }
    return groups, channels, report


def trajectory_limit_report(trajectory, arms, *, scene=None):
    """Offline q/v/a limits report; no connection, payload mutation or retiming.

    Positions-only velocity is the exact linear-segment slope. Acceleration is
    an interior slope-change / midpoint-spacing estimate, NOT a continuous bound:
    speed jumps at knots/start/end remain unbounded. Fewer than three positions
    provide no acceleration estimate. Explicit polynomials are sampled, not
    certified at every extremum. ``max_step`` remains a separate runtime guard.
    Scene position/velocity limits intersect manual Arm limits, as in the server.
    Any approach from a measured state before a positive first timestamp is not
    included; preview starts at the first supplied point.
    """
    return _preview_data(trajectory, arms, scene)[2]


def plot_trajectory(trajectory, arms, *, scene=None):
    """Plot desired q/v/a and effective limits; return figures and offline report.

    Time is time_from_start, not UTC: execution has not been scheduled yet.
    Numerical preview derivatives are never added to the outgoing trajectory.
    See ``trajectory_limit_report`` for the derivative and sampling limitations.
    """
    import matplotlib.pyplot as plt

    groups, channels, report = _preview_data(trajectory, arms, scene)
    figures = []
    estimated = trajectory.velocities is None
    titles = (
        "Position",
        "Segment velocity" if estimated else "Velocity (sampled)",
        "Acceleration estimate" if estimated else "Acceleration (sampled)",
    )
    for name, joint_names, columns, limits in groups:
        fig, axes = plt.subplots(6, 3, figsize=(16, 15), sharex=True)
        bounds = [
            (limits["min_position"], limits["max_position"]),
            (-limits["max_velocity"], limits["max_velocity"]),
            (-limits["max_acceleration"], limits["max_acceleration"]),
        ]
        for axis, (joint, column) in enumerate(zip(joint_names, columns)):
            for order, ((times, values), (lower, upper), unit) in enumerate(
                zip(channels, bounds, ("rad", "rad/s", "rad/s²"))
            ):
                ax = axes[axis, order]
                y = values[:, column]
                ax.plot(times, y, lw=1, label="desired" if order == 0 else titles[order])
                ax.axhline(lower[axis], color="red", ls="--", lw=0.8, label="limits")
                ax.axhline(upper[axis], color="red", ls="--", lw=0.8)
                outside = (y < lower[axis]) | (y > upper[axis])
                if outside.any():
                    ax.plot(times[outside], y[outside], ".", color="red", label="exceeds limit")
                if not len(y):
                    message = "No interior acceleration estimate" if order == 2 else "No segments"
                    ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center")
                ax.set_ylabel(f"{joint}\n{unit}" if order == 0 else unit)
                ax.grid(True, alpha=0.3)
                if axis == 0:
                    ax.set_title(titles[order])
                    ax.legend(fontsize="small")
                if axis == 5:
                    ax.set_xlabel("time_from_start, s")
        note = (
            "Acceleration is an interior estimate; speed jumps at knots/start/end are not bounded."
            if estimated
            else "Polynomial samples, not a continuous extrema certificate."
        )
        fig.suptitle(f"{name} — desired trajectory and effective limits\n{note}")
        fig.tight_layout()
        figures.append(fig)
    return figures, report


def plot_execution(execution, output=None):
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    result = execution.poll()
    trajectory = execution.trajectory
    start = result.get("start_unix_ns", 0)
    folder = Path(output) if output else None
    if folder:
        folder.mkdir(parents=True, exist_ok=True)
    figures = []
    metrics = {}
    for arm in execution.robot.arms:
        rows = [r for r in execution.samples if r["name"] == arm["name"]]
        if not rows:
            continue
        stamps = np.array([r["stamp_unix_ns"] for r in rows], dtype=np.int64)
        actual = np.array([r["positions"] for r in rows])
        elapsed = (stamps - start) / 1e9 if start else np.full(len(rows), np.nan)
        desired = np.full_like(actual, np.nan)
        for row, t in enumerate(elapsed):
            if not trajectory.times[0] <= t <= trajectory.times[-1]:
                continue
            sampled = trajectory.sample(t)
            for axis, name in enumerate(arm["joint_names"]):
                if name in trajectory.joint_names:
                    desired[row, axis] = sampled[trajectory.joint_names.index(name)]
        error = actual - desired
        x = [datetime.fromtimestamp(int(ns) / 1e9, timezone.utc) for ns in stamps]
        fig, axes = plt.subplots(6, 2, figsize=(14, 15), sharex=True)
        for axis, name in enumerate(arm["joint_names"]):
            axes[axis, 0].plot(x, actual[:, axis], label="measured", lw=1)
            if start and name in trajectory.joint_names:
                # Dense display of the exact submitted polynomial; CSV itself unchanged.
                tt = np.unique(
                    np.r_[
                        trajectory.times,
                        np.linspace(trajectory.times[0], trajectory.times[-1], 500),
                    ]
                )
                y = [trajectory.sample(t)[trajectory.joint_names.index(name)] for t in tt]
                xx = [
                    datetime.fromtimestamp((start + int(t * 1e9)) / 1e9, timezone.utc) for t in tt
                ]
                axes[axis, 0].plot(xx, y, "--", label="desired", lw=1)
            axes[axis, 0].set_ylabel(name + "\nrad")
            axes[axis, 1].plot(x, error[:, axis], lw=1)
            axes[axis, 1].axhline(0, color="k", lw=0.5)
            axes[axis, 1].set_ylabel("actual − desired, rad")
            for ax in axes[axis]:
                ax.grid(True, alpha=0.3)
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S.%f", tz=timezone.utc))
        axes[0, 0].legend()
        axes[-1, 0].set_xlabel("UTC timestamp")
        axes[-1, 1].set_xlabel("UTC timestamp")
        fig.suptitle(
            f"{arm['name']} — {result['status']} — {result['message'][:140]}\n"
            + (x[0].strftime("%Y-%m-%d UTC") if x else "")
        )
        fig.autofmt_xdate()
        fig.tight_layout()
        figures.append(fig)
        mask = np.isfinite(error).all(axis=1)
        metrics[arm["name"]] = {
            "samples": len(rows),
            "rmse_rad": np.sqrt(np.mean(error[mask] ** 2, axis=0)).tolist() if mask.any() else None,
            "max_abs_rad": np.max(np.abs(error[mask]), axis=0).tolist() if mask.any() else None,
        }
        if folder:
            fig.savefig(folder / f"{arm['name']}.png", dpi=130)
            with (folder / f"{arm['name']}_measured.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    [
                        "stamp_unix_ns",
                        *arm["joint_names"],
                        *["error_" + j for j in arm["joint_names"]],
                    ]
                )
                writer.writerows([int(stamp), *q, *e] for stamp, q, e in zip(stamps, actual, error))
    if folder:
        metadata = {
            "result": result,
            "metrics": metrics,
            "arms": execution.robot.arms,
            "timestamp_semantics": "host receipt completion; not encoder acquisition",
            "error_sign": "actual-desired",
            "trajectory": trajectory.to_dict(),
        }
        (folder / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return figures, metrics
