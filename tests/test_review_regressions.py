"""Regression tests for cancellation, ownership and explicit viewer motion controls."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import iimt.viewer as viewer_module
from iimt import JOINTS, Arm, Robot, Scene, Trajectory, _control, _viewer
from iimt._server import Service
from iimt.mock import DEFAULT_Q, MockRobot
from iimt.robot import Execution


class _RecordingCore:
    def __init__(self, arms):
        self.arms = arms
        self.executions = []
        self.cancelled = False
        self.closed = False

    def connect(self):
        pass

    def get_state(self):
        return {"arms": [{"name": "arm", "positions": [0.0] * 6, "valid": True, "age_s": 0.0}]}

    def result(self):
        return {"goal_id": 0, "status": "idle", "message": ""}

    def diagnostics(self):
        return {"fault": ""}

    def execute(self, *args):
        self.executions.append(args)
        return 1

    def cancel(self):
        self.cancelled = True

    def close(self):
        self.closed = True


class _BlockingModel:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def limits(self):
        return {"lower": [-3.0] * 6, "upper": [3.0] * 6, "velocity": [1.0] * 6}

    def check(self, positions):
        self.entered.set()
        assert self.release.wait(3), "Test failed to release collision validation"
        return {"valid": True, "collisions": []}


@pytest.fixture
def service(monkeypatch):
    model = _BlockingModel()
    monkeypatch.setattr(_control, "Controller", _RecordingCore)
    monkeypatch.setattr(Scene, "model", lambda self: model)
    arm = Arm("arm", "127.0.0.1", enable_motion=True)
    scene = Scene("unused-test-model.urdf", list(JOINTS))
    instance = Service([arm.to_dict()], scene.to_dict())
    yield instance, model
    model.release.set()


def _payload():
    return Trajectory([0.0, 0.1], [[0.0] * 6, [0.01] * 6], list(JOINTS)).to_dict()


def test_cancel_during_collision_preflight_does_not_dispatch(service):
    controller, model = service
    with ThreadPoolExecutor(max_workers=2) as work:
        preparation = work.submit(controller.prepare, _payload())
        assert model.entered.wait(1), "Preflight did not reach collision validation"
        cancelled = threading.Event()

        def cancel():
            controller.dispatch("cancel", (None,), {})
            cancelled.set()

        cancellation = work.submit(cancel)
        try:
            assert cancelled.wait(1), "Cancellation blocked behind collision validation"
        finally:
            model.release.set()
        cancellation.result(timeout=1)
        with pytest.raises(RuntimeError, match="cancelled"):
            preparation.result(timeout=2)
    assert controller.core.cancelled
    assert controller.core.executions == []
    assert controller.prepared is None


@pytest.mark.parametrize(
    ("method", "arguments"),
    [
        ("prepare", (_payload(),)),
        ("execute", (_payload(), 1, False)),
        ("execute_prepared", (1, 1)),
        ("plan", ([0.0] * 6, 1.0, 0.2)),
    ],
)
def test_closing_service_rejects_new_work(service, method, arguments):
    controller, _ = service
    controller.dispatch("close", (), {})
    with pytest.raises(RuntimeError, match="closing"):
        controller.dispatch(method, arguments, {})
    assert controller.core.executions == []


def test_cached_terminal_result_does_not_consume_another_goals_samples():
    class RobotWithOtherGoal:
        def samples(self):
            pytest.fail("An old execution consumed samples belonging to the current goal")

        def _call(self, *args):
            pytest.fail("A cached terminal execution queried the current goal")

    execution = Execution(RobotWithOtherGoal(), 1, None)
    terminal = {"goal_id": 1, "status": "succeeded", "message": "done"}
    execution._result = terminal
    assert execution.poll() is terminal


def test_close_warns_when_sdk_cannot_confirm_stop():
    with MockRobot(fail_stop=True) as mock:
        robot = Robot.single(mock.host, port=mock.port, scene=False, enable_motion=True)
        try:
            robot.connect(viewer=False)
            goal = list(DEFAULT_Q)
            goal[0] += 0.02
            trajectory = Trajectory([0.0, 2.0], [DEFAULT_Q, goal], list(JOINTS))
            robot.execute_trajectory(trajectory, start_delay=0.15, check_collision=False)
            deadline = time.monotonic() + 3
            while robot.diagnostics()["arms"][0]["sends"] == 0:
                assert time.monotonic() < deadline, "No command was sent before shutdown test"
                time.sleep(0.01)
            with pytest.warns(RuntimeWarning, match="physical stop is NOT confirmed"):
                robot.close(timeout=3)
        finally:
            robot.close()


def test_viewer_discards_plan_for_target_changed_while_planning(monkeypatch):
    submissions = []
    frames = []
    ready_messages = []

    class Model:
        def geometry_local(self):
            return []

        def limits(self):
            return {"lower": [-3.0] * 6, "upper": [3.0] * 6}

        def transforms(self, positions):
            return {}

    class Viewer:
        def __init__(self, title):
            pass

        def set_geometry(self, meshes):
            pass

        def update(self, meshes, target, lower, upper, status, *args):
            frames.append(status)
            events = [
                {"open": True, "target": [0.0] * 6, "action": "plan"},
                {"open": True, "target": [0.1] * 6, "action": None},
                {"open": True, "target": [0.1] * 6, "action": "execute"},
                {"open": False, "target": [0.1] * 6, "action": None},
            ]
            return events[len(frames) - 1]

        def close(self):
            pass

    class DelayedPlan:
        def __init__(self):
            self.checks = 0

        def done(self):
            self.checks += 1
            return self.checks >= 2

        def result(self):
            return Trajectory([0.0, 1.0], [[0.0] * 6, [0.0] * 6], list(JOINTS)).to_dict()

    class Executor:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, function, *args):
            submissions.append((function, args))
            return DelayedPlan()

    class Ready:
        def send(self, message):
            ready_messages.append(message)

        def close(self):
            pass

    def rpc(address, key, method, *args, **kwargs):
        assert method == "get_state", "Unexpected command escaped the fake GUI executor"
        return {"arms": [{"positions": [0.0] * 6}]}

    monkeypatch.setattr(_viewer, "Viewer", Viewer)
    monkeypatch.setattr(Scene, "model", lambda self: Model())
    monkeypatch.setattr(viewer_module, "ThreadPoolExecutor", Executor)
    monkeypatch.setattr(viewer_module, "rpc", rpc)
    monkeypatch.setattr(viewer_module.time, "sleep", lambda duration: None)
    viewer_module.run_viewer(None, None, Scene("unused.urdf", list(JOINTS)).to_dict(), Ready())
    assert ready_messages == [(True, None)], ready_messages
    assert len(frames) == 4
    assert len(submissions) == 1, "Execute submitted a stale plan for the previous target"
    assert "discarded" in frames[2]
    assert "Plan first" in frames[3]
