"""Public process-isolated client. Importing this module cannot move a robot."""

from __future__ import annotations

import multiprocessing as mp
import secrets
import threading
import time
import warnings
from multiprocessing.connection import Client

from .config import Arm
from .models import ci05_scene
from .trajectory import Trajectory


def rpc(address, key, method, *args, timeout=30.0, **kwargs):
    with Client(address, authkey=key) as connection:
        connection.send((method, args, kwargs))
        if not connection.poll(timeout):
            raise TimeoutError(
                f"Controller RPC '{method}' exceeded {timeout}s; physical state is unknown"
            )
        ok, value = connection.recv()
    if not ok:
        raise RuntimeError(value)
    return value


class Execution:
    def __init__(self, robot, goal_id, trajectory):
        self.robot, self.goal_id, self.trajectory = robot, goal_id, trajectory
        self.samples = []
        self._result = None

    def poll(self):
        if self._result is not None:
            return self._result
        result = self.robot._call("result")
        if result["goal_id"] != self.goal_id:
            raise RuntimeError(
                "Goal result superseded; wait for each execution before starting another"
            )
        self.samples.extend(
            row for row in self.robot.samples() if row.get("goal_id") == self.goal_id
        )
        if result["status"] != "running":
            self._result = result
        return result

    def wait(self, timeout=None, *, raise_on_error=True):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            result = self.poll()
            if result["status"] != "running":
                break
            if deadline is not None and time.monotonic() >= deadline:
                self.cancel()
                raise TimeoutError(
                    "Execution wait expired; cancellation requested, physical stop not yet confirmed"
                )
            time.sleep(0.02)
        if raise_on_error and result["status"] != "succeeded":
            raise RuntimeError(result["message"])
        return result

    def cancel(self):
        return self.robot._call("cancel", self.goal_id)


class Robot:
    def __init__(self, arms, *, scene=None):
        self.arms = [a.to_dict() if isinstance(a, Arm) else dict(a) for a in arms]
        if len(self.arms) not in (1, 2):
            raise ValueError("Exactly one or two CI-05 arms are supported")
        self.scene = ci05_scene(dual=len(self.arms) == 2) if scene is None else scene
        if self.scene is False:
            self.scene = None
        self._process = self._viewer = None
        self._address = self._key = None
        self._last_execution = None
        self._lock = threading.RLock()

    @classmethod
    def single(cls, ip, *, port=29999, scene=None, **options):
        return cls([Arm("arm", ip, port=port, **options)], scene=scene)

    @classmethod
    def dual(cls, left_ip, right_ip, *, left_port=29999, right_port=29999, scene=None, **options):
        from .config import JOINTS

        return cls(
            [
                Arm(
                    "left",
                    left_ip,
                    port=left_port,
                    joint_names=["left_" + j for j in JOINTS],
                    **options,
                ),
                Arm(
                    "right",
                    right_ip,
                    port=right_port,
                    joint_names=["right_" + j for j in JOINTS],
                    **options,
                ),
            ],
            scene=scene,
        )

    @property
    def joint_names(self):
        return [j for arm in self.arms for j in arm["joint_names"]]

    def connect(self, *, viewer=True, timeout=30.0):
        if self._process is not None:
            raise RuntimeError("Already connected")
        from ._server import serve

        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._key = secrets.token_bytes(32)
        self._process = ctx.Process(
            target=serve,
            args=(self.arms, self.scene.to_dict() if self.scene else None, self._key, child),
        )
        self._process.start()
        child.close()
        try:
            if not parent.poll(timeout):
                raise TimeoutError("Controller startup timed out; no motion was requested")
            ok, message = parent.recv()
            if not ok:
                raise RuntimeError(message)
            self._address = message
            if viewer:
                self.open_viewer()
            return self
        except BaseException:
            self.close()
            raise
        finally:
            parent.close()

    def _call(self, method, *args, **kwargs):
        if self._process is None or not self._process.is_alive() or self._address is None:
            raise RuntimeError("Controller is not connected/alive; physical stop is NOT confirmed")
        return rpc(self._address, self._key, method, *args, **kwargs)

    def get_state(self):
        return self._call("get_state")

    def diagnostics(self):
        return self._call("diagnostics")

    def samples(self):
        return self._call("drain_samples")

    def cancel(self):
        return self._call("cancel", None)

    def plan(self, joint_goal, *, timeout=5.0, scale=0.2):
        return Trajectory(
            **self._call("plan", list(joint_goal), timeout, scale, timeout=timeout + 30)
        )

    def execute_trajectory(
        self, trajectory, *, start_unix_ns=None, start_delay=3.0, check_collision=True
    ):
        """Absolute UTC message start; delay is chosen HERE, not a controller parameter."""
        import math

        if not math.isfinite(start_delay) or start_delay < 0:
            raise ValueError("start_delay must be finite and nonnegative")
        with self._lock:
            if (
                self._last_execution is not None
                and self._last_execution.poll()["status"] == "running"
            ):
                raise RuntimeError("Previous execution is still active")
            ticket = (
                self._call("prepare", trajectory.to_dict(), timeout=120)
                if check_collision
                else None
            )
            # Expensive preflight is finished before constructing the message epoch.
            start_unix_ns = (
                int(time.time_ns() + start_delay * 1e9)
                if start_unix_ns is None
                else int(start_unix_ns)
            )
            try:
                if ticket is not None:
                    goal_id = self._call("execute_prepared", ticket, start_unix_ns)
                else:
                    goal_id = self._call("execute", trajectory.to_dict(), start_unix_ns, False)
            except (TimeoutError, EOFError, OSError):
                try:
                    self.cancel()
                except Exception as error:
                    warnings.warn(
                        f"Cancellation after lost commit reply failed: {error}; physical stop is NOT confirmed",
                        RuntimeWarning,
                    )
                raise
            self._last_execution = Execution(self, goal_id, trajectory)
            return self._last_execution

    def open_viewer(self):
        if not self.scene:
            raise ValueError("Viewer requires a scene")
        if self._viewer and self._viewer.is_alive():
            return
        from .viewer import run_viewer

        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._viewer = ctx.Process(
            target=run_viewer, args=(self._address, self._key, self.scene.to_dict(), child)
        )
        self._viewer.start()
        child.close()
        if not parent.poll(30):
            raise TimeoutError("Viewer initialization timed out")
        ok, message = parent.recv()
        parent.close()
        if not ok:
            raise RuntimeError(f"Viewer failed: {message}; use viewer=False for headless")

    def close(self, timeout=5.0):
        if self._viewer:
            if self._viewer.is_alive():
                self._viewer.terminate()
            self._viewer.join(2)
            self._viewer = None
        process = self._process
        if process is None:
            return
        outcome_received = self._address is None
        if process.is_alive() and self._address:
            try:
                outcome = self._call("close", timeout=timeout)
                outcome_received = True
                message = outcome["result"]["message"] + str(
                    outcome["diagnostics"].get("fault", "")
                )
                if "physical stop is NOT confirmed" in message:
                    warnings.warn(message, RuntimeWarning)
            except (OSError, EOFError, RuntimeError, TimeoutError):
                pass
        if not outcome_received:
            warnings.warn(
                "No controller cleanup outcome received; physical stop is NOT confirmed",
                RuntimeWarning,
            )
        process.join(timeout)
        if process.is_alive():
            process.terminate()
            process.join(2)
            warnings.warn(
                "SDK shutdown did not finish. Controller process terminated; physical stop is NOT confirmed",
                RuntimeWarning,
            )
        self._process = None
        self._address = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()
