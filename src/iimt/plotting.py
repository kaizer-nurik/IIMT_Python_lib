"""UTC plots without lag fitting or timestamp shifting. Optional notebook extras."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


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
