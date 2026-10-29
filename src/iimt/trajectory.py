"""Joint trajectories: preserve CSV times/positions; only plans receive timing."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Trajectory:
    times: object
    positions: object
    joint_names: list[str]
    velocities: object = None
    accelerations: object = None

    def __post_init__(self):
        self.times = np.asarray(self.times, dtype=float).copy()
        self.positions = np.asarray(self.positions, dtype=float).copy()
        n, d = len(self.times), len(self.joint_names)
        if n == 0 or d not in (6, 12) or len(set(self.joint_names)) != d:
            raise ValueError("Require nonempty trajectory and six/twelve unique joint names")
        if (
            self.times.shape != (n,)
            or not np.isfinite(self.times).all()
            or self.times[0] < 0
            or np.any(np.diff(self.times) <= 0)
        ):
            raise ValueError("Times must be finite, nonnegative and strictly increasing")
        for name in ("positions", "velocities", "accelerations"):
            value = getattr(self, name)
            if value is None:
                continue
            value = np.asarray(value, dtype=float).copy()
            if value.shape != (n, d) or not np.isfinite(value).all():
                raise ValueError(f"{name}: expected finite shape {(n,d)}, received {value.shape}")
            setattr(self, name, value)
        if self.accelerations is not None and self.velocities is None:
            raise ValueError("Accelerations require explicit velocities")
        if self.velocities is not None and np.max(np.abs(self.velocities[-1])) > 1e-9:
            raise ValueError("Terminal velocity must be zero; CSV without derivatives is allowed")

    def to_dict(self):
        return {
            "times": self.times.tolist(),
            "positions": self.positions.tolist(),
            "joint_names": list(self.joint_names),
            "velocities": None if self.velocities is None else self.velocities.tolist(),
            "accelerations": None if self.accelerations is None else self.accelerations.tolist(),
        }

    @classmethod
    def from_csv(cls, path, joint_names, *, arm="left", time_column="t", columns=None):
        """No retiming, derivatives, entry/exit points or unit conversion are invented."""
        if columns is None:
            arms = ("left", "right") if arm == "both" else (arm,)
            columns = [f"{a}_q{i}_rad" for a in arms for i in range(1, 7)]
        with Path(path).open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError("CSV is empty")
        missing = set([time_column, *columns]) - rows[0].keys()
        if missing:
            raise ValueError(f"CSV missing columns: {sorted(missing)}; available: {list(rows[0])}")
        return cls(
            [float(r[time_column]) for r in rows],
            [[float(r[c]) for c in columns] for r in rows],
            list(joint_names),
        )

    def reordered(self, names, hold=None):
        """Allow exactly all axes, or one complete arm while holding the other."""
        if set(self.joint_names) - set(names):
            raise ValueError("Trajectory contains unknown joints")
        if set(self.joint_names) != set(names):
            if (
                len(names) != 12
                or len(self.joint_names) != 6
                or set(self.joint_names) not in (set(names[:6]), set(names[6:]))
            ):
                raise ValueError("Partial goals must contain exactly one complete six-joint arm")
            if hold is None:
                raise ValueError("Fresh measured hold position required for inactive arm")
        arrays = {}
        for field in ("positions", "velocities", "accelerations"):
            values = getattr(self, field)
            if values is None:
                arrays[field] = None
                continue
            expanded = np.zeros((len(self.times), len(names)))
            for j, name in enumerate(names):
                if name in self.joint_names:
                    expanded[:, j] = values[:, self.joint_names.index(name)]
                elif field == "positions":
                    expanded[:, j] = hold[j]
            arrays[field] = expanded
        return Trajectory(self.times, joint_names=list(names), **arrays)

    def sample(self, t):
        """Same linear/cubic/quintic position polynomial as the C++ controller."""
        if t <= self.times[0]:
            return self.positions[0].copy()
        if t >= self.times[-1]:
            return self.positions[-1].copy()
        i = np.searchsorted(self.times, t, side="right") - 1
        h = self.times[i + 1] - self.times[i]
        u = (t - self.times[i]) / h
        q0, q1 = self.positions[i : i + 2]
        delta = q1 - q0
        if self.velocities is None:
            return q0 + delta * u
        v0, v1 = self.velocities[i : i + 2] * h
        if self.accelerations is None:
            return q0 + u * (v0 + u * ((3 * delta - 2 * v0 - v1) + u * (-2 * delta + v0 + v1)))
        a0, a1 = self.accelerations[i : i + 2] * h * h
        c2 = a0 / 2
        d, e, f = delta - v0 - c2, v1 - v0 - 2 * c2, a1 - 2 * c2
        return q0 + u * (
            v0
            + u
            * (
                c2
                + u
                * (
                    (10 * d - 4 * e + f / 2)
                    + u * ((-15 * d + 7 * e - f) + u * (6 * d - 3 * e + f / 2))
                )
            )
        )


def time_parameterize(path, names, max_velocity, max_acceleration, scale=0.2):
    """Conservative stop-at-waypoint quintics for RRT paths, never for CSV input.

    This is deliberately not MoveIt's time-optimal retimer. A shared monotone
    quintic progress on each segment preserves its checked joint-space line.
    """
    if not np.isfinite(scale) or not 0 < scale <= 1:
        raise ValueError("Planning scale must be in (0,1]")
    q = np.asarray(path, dtype=float)
    v, a = np.asarray(max_velocity) * scale, np.asarray(max_acceleration) * scale
    if min(v) <= 0 or min(a) <= 0:
        raise ValueError("Positive finite planning limits required")
    times = [0.0]
    for delta in np.abs(np.diff(q, axis=0)):
        duration = max(
            0.1, float(np.max(1.875 * delta / v)), float(np.max(np.sqrt(5.774 * delta / a)))
        )
        times.append(times[-1] + duration)
    return Trajectory(times, q, list(names), np.zeros_like(q), np.zeros_like(q))
