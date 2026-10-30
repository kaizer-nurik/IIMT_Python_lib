"""Joint trajectories: preserve CSV input unless resampling/retiming is requested."""

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
    def from_csv(
        cls, path, joint_names, *, arm="left", time_column="t", columns=None, sample_rate=None
    ):
        """Read arbitrary increasing times in seconds and joint positions in radians.

        Without timestamps, explicitly use time_column=None and sample_rate in Hz.
        No derivatives, entry/exit points or unit conversions are invented.
        """
        if time_column is None:
            if sample_rate is None or not np.isfinite(sample_rate) or sample_rate <= 0:
                raise ValueError("CSV without a time column requires a positive finite sample_rate")
        elif sample_rate is not None:
            raise ValueError("Choose CSV timestamps or sample_rate, not both")
        if columns is None:
            arms = ("left", "right") if arm == "both" else (arm,)
            columns = [f"{a}_q{i}_rad" for a in arms for i in range(1, 7)]
        with Path(path).open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError("CSV is empty")
        required = columns if time_column is None else [time_column, *columns]
        missing = set(required) - rows[0].keys()
        if missing:
            raise ValueError(f"CSV missing columns: {sorted(missing)}; available: {list(rows[0])}")
        return cls(
            (
                np.arange(len(rows), dtype=float) / sample_rate
                if time_column is None
                else [float(r[time_column]) for r in rows]
            ),
            [[float(r[c]) for c in columns] for r in rows],
            list(joint_names),
        )

    def time_scaled(self, factor):
        """Return a copy with t *= factor: 2 is twice slower, 0.5 twice faster.

        Positions are unchanged; explicit dq/ddq scale by 1/factor and 1/factor².
        No derivatives are created for positions-only input.
        """
        if not np.isfinite(factor) or factor <= 0:
            raise ValueError("Time scale factor must be positive and finite")
        return Trajectory(
            self.times * factor,
            self.positions,
            list(self.joint_names),
            None if self.velocities is None else self.velocities / factor,
            None if self.accelerations is None else self.accelerations / factor / factor,
        )

    def resampled(self, rate_hz, *, mode="interpolate"):
        """Resample over the original time span, preserving both endpoints.

        interpolate: exact Hz grid (last interval may be shorter), sampled from
        the submitted polynomial. Positions-only input stays positions-only.
        select: nearest ORIGINAL rows/timestamps, no invented points; noninteger
        ratios (100 -> 30 Hz) give irregular intervals, not an exact 30 Hz clock.
        Neither mode filters/anti-aliases; removing knots can change the path.
        """
        if not np.isfinite(rate_hz) or rate_hz <= 0:
            raise ValueError("Resampling rate must be positive and finite")
        if mode not in {"interpolate", "select"}:
            raise ValueError("Resampling mode must be 'interpolate' or 'select'")
        if len(self.times) == 1:
            return self.time_scaled(1.0)
        span = self.times[-1] - self.times[0]
        count = span * rate_hz
        if not np.isfinite(count) or count > 1_000_000:
            raise ValueError("Resampling exceeds one million intervals; reduce rate or duration")
        grid = self.times[0] + np.arange(int(np.floor(count)) + 1) / rate_hz
        grid = grid[grid < self.times[-1]]
        epsilon = 8 * np.spacing(max(1.0, abs(self.times[0]), abs(self.times[-1])))
        if len(grid) > 1 and self.times[-1] - grid[-1] <= epsilon:
            grid[-1] = self.times[-1]
        else:
            grid = np.r_[grid, self.times[-1]]
        if mode == "select":
            right = np.minimum(np.searchsorted(self.times, grid), len(self.times) - 1)
            left = np.maximum(right - 1, 0)
            nearest = np.where(grid - self.times[left] <= self.times[right] - grid, left, right)
            indices = np.unique(np.r_[0, nearest, len(self.times) - 1])
            return Trajectory(
                self.times[indices],
                self.positions[indices],
                list(self.joint_names),
                None if self.velocities is None else self.velocities[indices],
                None if self.accelerations is None else self.accelerations[indices],
            )
        positions = (
            np.column_stack([np.interp(grid, self.times, q) for q in self.positions.T])
            if self.velocities is None
            else [self.sample(t) for t in grid]
        )
        return Trajectory(
            grid,
            positions,
            list(self.joint_names),
            None if self.velocities is None else [self.sample(t, derivative=1) for t in grid],
            None if self.accelerations is None else [self.sample(t, derivative=2) for t in grid],
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

    def sample(self, t, *, derivative=0):
        """Evaluate the native linear/cubic/quintic polynomial or its derivatives.

        Derivatives are zero outside the data horizon, right-sided at interior
        knots and left-sided at the final knot. Linear acceleration is zero only
        INSIDE segments; velocity jumps at knots have no finite acceleration.
        Calling this method never adds derivatives to the trajectory payload.
        """
        if derivative not in (0, 1, 2) or not np.isfinite(t):
            raise ValueError("Require finite sample time and derivative order 0, 1 or 2")
        if derivative == 0:
            if t <= self.times[0]:
                return self.positions[0].copy()
            if t >= self.times[-1]:
                return self.positions[-1].copy()
        elif len(self.times) == 1 or t < self.times[0] or t > self.times[-1]:
            return np.zeros(len(self.joint_names))
        i = min(np.searchsorted(self.times, t, side="right") - 1, len(self.times) - 2)
        h = self.times[i + 1] - self.times[i]
        u = (t - self.times[i]) / h
        q0, q1 = self.positions[i : i + 2]
        delta = q1 - q0
        if self.velocities is None:
            if derivative == 0:
                return q0 + delta * u
            return delta / h if derivative == 1 else np.zeros_like(q0)
        coefficients = self._segment_coefficients(i)
        for _ in range(derivative):
            coefficients = [power * c for power, c in enumerate(coefficients) if power]
        result = np.zeros_like(q0)
        for c in reversed(coefficients):
            result = result * u + c
        return result / h**derivative

    def _segment_coefficients(self, i):
        h = self.times[i + 1] - self.times[i]
        q0, q1 = self.positions[i : i + 2]
        delta = q1 - q0
        v0, v1 = self.velocities[i : i + 2] * h
        if self.accelerations is None:
            return [q0, v0, 3 * delta - 2 * v0 - v1, -2 * delta + v0 + v1]
        a0, a1 = self.accelerations[i : i + 2] * h * h
        c2 = a0 / 2
        d, e, f = delta - v0 - c2, v1 - v0 - 2 * c2, a1 - 2 * c2
        return [q0, v0, c2, 10 * d - 4 * e + f / 2, -15 * d + 7 * e - f, 6 * d - 3 * e + f / 2]


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
