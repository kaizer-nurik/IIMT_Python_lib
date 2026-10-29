"""Private authenticated localhost IPC. Native threads own all servo/read timing."""

from __future__ import annotations

import multiprocessing as mp
import socket
import threading
import traceback
from multiprocessing.connection import Listener

import numpy as np

from .config import Scene
from .trajectory import Trajectory, time_parameterize


class Service:
    def __init__(self, arms, scene):
        from ._control import Controller

        self.arms = arms
        self.names = [n for arm in arms for n in arm["joint_names"]]
        if len(set(self.names)) != len(self.names):
            raise ValueError("Arm joint names must be globally unique")
        self.scene = Scene(**scene) if scene else None
        if self.scene and self.scene.joint_names != self.names:
            raise ValueError("Scene joint order must match configured SDK arm order")
        self.model = self.scene.model() if self.scene else None
        self.lock, self.model_lock = threading.Lock(), threading.Lock()
        self.generation = 0
        self.pending = False
        self.prepared = None
        if self.model:
            limits = self.model.limits()
            for index, arm in enumerate(self.arms):
                for axis in range(6):
                    j = index * 6 + axis
                    arm["min_position"][axis] = max(arm["min_position"][axis], limits["lower"][j])
                    arm["max_position"][axis] = min(arm["max_position"][axis], limits["upper"][j])
                    arm["max_velocity"][axis] = min(
                        arm["max_velocity"][axis], limits["velocity"][j]
                    )
        self.core = Controller(self.arms)
        self.core.connect()
        self.stopping = threading.Event()
        self.closing = threading.Event()

    def measured(self):
        state = self.core.get_state()
        for arm, config in zip(state["arms"], self.arms):
            if not arm["valid"] or arm["age_s"] > config["state_timeout"]:
                raise RuntimeError(f"{arm['name']}: stale state age={arm['age_s']:.6f}s")
        return [q for arm in state["arms"] for q in arm["positions"]]

    def check_trajectory(self, trajectory, ticket):
        if self.model is None:
            raise RuntimeError("A scene is required for collision preflight")
        resolution = self.scene.collision_resolution
        if not np.isfinite(resolution) or resolution <= 0:
            raise ValueError("Positive collision_resolution required")
        # Derivative-aware sampling at least twice dispatch rate. Spatial subdivision
        # covers the resulting chord samples; this remains discrete validation.
        hz = max(a["command_rate"] for a in self.arms) * 2
        times = set(trajectory.times.tolist())
        for i in range(len(trajectory.times) - 1):
            a, b = trajectory.times[i : i + 2]
            count = max(
                1,
                int(np.ceil((b - a) * hz)),
                int(
                    np.ceil(
                        np.max(np.abs(trajectory.positions[i + 1] - trajectory.positions[i]))
                        / resolution
                    )
                ),
            )
            if count > 100000:
                raise ValueError("Trajectory collision sampling budget exceeded")
            times.update(np.linspace(a, b, count + 1).tolist())
        with self.model_lock:
            for t in sorted(times):
                with self.lock:
                    if ticket != self.generation:
                        raise RuntimeError("Trajectory preparation cancelled")
                outcome = self.model.check(trajectory.sample(t).tolist())
                if not outcome["valid"]:
                    raise ValueError(
                        f"Collision at time_from_start={t:.6f}s: {outcome['collisions']}"
                    )

    def expand(self, payload):
        q = self.measured()
        trajectory = Trajectory(**payload).reordered(self.names, q)
        if trajectory.times[0] > 0:
            zero = np.zeros((1, len(q)))
            trajectory = Trajectory(
                np.r_[0.0, trajectory.times],
                np.vstack((q, trajectory.positions)),
                self.names,
                None if trajectory.velocities is None else np.vstack((zero, trajectory.velocities)),
                (
                    None
                    if trajectory.accelerations is None
                    else np.vstack((zero, trajectory.accelerations))
                ),
            )
        return trajectory

    def prepare(self, payload):
        with self.lock:
            if self.closing.is_set():
                raise RuntimeError("Controller is closing")
            if self.pending or self.core.result()["status"] == "running":
                raise RuntimeError("Another submission or execution is active")
            self.pending = True
            self.generation += 1
            ticket = self.generation
            self.prepared = None
        try:
            trajectory = self.expand(payload)
            self.check_trajectory(trajectory, ticket)
            with self.lock:
                if ticket != self.generation:
                    raise RuntimeError("Trajectory preparation cancelled")
                self.prepared = (ticket, trajectory)
            return ticket
        finally:
            with self.lock:
                self.pending = False

    def submit(self, trajectory, start_unix_ns):
        return self.core.execute(
            trajectory.times.tolist(),
            trajectory.positions.tolist(),
            int(start_unix_ns),
            [] if trajectory.velocities is None else trajectory.velocities.tolist(),
            [] if trajectory.accelerations is None else trajectory.accelerations.tolist(),
        )

    def execute_prepared(self, ticket, start_unix_ns):
        with self.lock:
            if self.closing.is_set():
                raise RuntimeError("Controller is closing")
            if self.prepared is None or ticket != self.generation or self.prepared[0] != ticket:
                raise RuntimeError("Prepared trajectory expired, replaced or cancelled")
            trajectory = self.prepared[1]
            self.prepared = None
            return self.submit(trajectory, start_unix_ns)

    def execute(self, payload, start_unix_ns, check_collision):
        if check_collision:
            return self.execute_prepared(self.prepare(payload), start_unix_ns)
        with self.lock:
            if self.closing.is_set():
                raise RuntimeError("Controller is closing")
            if self.pending:
                raise RuntimeError("Trajectory preparation in progress")
            self.generation += 1
            self.prepared = None
            return self.submit(self.expand(payload), start_unix_ns)

    def plan(self, goal, timeout, scale):
        if self.model is None:
            raise RuntimeError("Planning requires a URDF scene")
        start = self.measured()
        with self.model_lock:
            path = self.model.plan(start, list(goal), timeout, self.scene.collision_resolution)
        limits = [
            min(v, step * a["command_rate"])
            for a in self.arms
            for v, step in zip(a["max_velocity"], a["max_step"])
        ]
        acc = [v for a in self.arms for v in a["max_acceleration"]]
        return time_parameterize(path, self.names, limits, acc, scale).to_dict()

    def dispatch(self, method, args, kwargs):
        if self.closing.is_set() and method not in {"result", "diagnostics", "get_state", "close"}:
            raise RuntimeError("Controller is closing; new work is rejected")
        if method == "execute":
            return self.execute(*args, **kwargs)
        if method == "prepare":
            return self.prepare(*args, **kwargs)
        if method == "execute_prepared":
            return self.execute_prepared(*args, **kwargs)
        if method == "plan":
            return self.plan(*args, **kwargs)
        if method == "cancel":
            with self.lock:
                result = self.core.result()
                if args and args[0] is not None and result["goal_id"] != args[0]:
                    raise RuntimeError("Goal is no longer current; refusing to cancel another goal")
                self.generation += 1
                self.prepared = None
                return self.core.cancel()
        if method == "close":
            with self.lock:
                self.generation += 1
                self.prepared = None
                self.core.cancel()
                self.closing.set()
            self.core.close()
            return {"result": self.core.result(), "diagnostics": self.core.diagnostics()}
        if method not in {"get_state", "result", "diagnostics", "drain_samples"}:
            raise ValueError(f"Unknown RPC method {method}")
        return getattr(self.core, method)(*args, **kwargs)


def _client(connection, service):
    method = None
    try:
        method, args, kwargs = connection.recv()
        result = service.dispatch(method, args, kwargs)
        connection.send((True, result))
    except Exception as exc:
        try:
            connection.send((False, f"{type(exc).__name__}: {exc}"))
        except (OSError, EOFError):
            pass
    finally:
        connection.close()
        if method == "close":
            service.stopping.set()


def serve(arms, scene, key, ready):
    service = None
    try:
        service = Service(arms, scene)
        with Listener(("127.0.0.1", 0), authkey=key) as listener:
            listener._listener._socket.settimeout(0.2)
            ready.send((True, listener.address))
            ready.close()
            while not service.stopping.is_set():
                parent = mp.parent_process()
                if parent is not None and not parent.is_alive():
                    break
                try:
                    connection = listener.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=_client, args=(connection, service), daemon=True).start()
    except Exception:
        try:
            ready.send((False, traceback.format_exc()))
        except (OSError, EOFError):
            pass
    finally:
        if service is not None:
            with service.lock:
                service.generation += 1
                service.prepared = None
                service.closing.set()
                service.stopping.set()
                service.core.cancel()
            service.core.close()
