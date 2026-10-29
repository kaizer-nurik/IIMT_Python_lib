"""Native controller integration: real vendor SDK, external localhost-only simulator."""

import importlib
import os
import time
from pathlib import Path

import pytest

from iimt.config import Arm, sdk_path
from iimt.mock import MockRobot

try:
    native = importlib.import_module(os.environ.get("IIMT_NATIVE_MODULE", "iimt._control"))
except ImportError:
    native = pytest.importorskip("_control")  # Standalone native-target developer build.


def arm(mock, name="single", **changes):
    library = os.environ.get("IIMT_TEST_SDK", sdk_path())
    if not Path(library).is_file():
        pytest.skip("Native vendor SDK unavailable for this platform")
    config = Arm(
        name,
        mock.host,
        mock.port,
        enable_motion=True,
        joint_names=[f"{name}_joint_{i}" for i in range(6)],
        sdk_library=library,
    ).to_dict()
    config.update(changes)
    return config


def wait_result(core, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = core.result()
        if result["status"] != "running":
            return result
        time.sleep(0.005)
    raise AssertionError(f"Controller still running: {core.diagnostics()}")


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Condition not reached before deadline")


def test_native_positions_only_absolute_start_and_samples():
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock)])
        core.connect()
        try:
            start = time.time_ns() + 200_000_000
            goal = core.execute([0.0, 0.4], [[0.0] * 6, [0.04] + [0.0] * 5], start)
            result = wait_result(core)
            assert result["status"] == "succeeded", result
            assert result["goal_id"] == goal
            assert result["start_unix_ns"] == start
            stats = core.diagnostics()["arms"][0]
            assert stats["sends"] >= 35  # Target 50, not a hard-real-time guarantee.
            assert abs(stats["first_send_stamp"] - start) < 100_000_000
            rows = [r for r in core.drain_samples() if r["goal_id"] == goal]
            assert len(rows) > 30
            for row in rows:
                assert abs((row["stamp_unix_ns"] - start) / 1e9 - row["nominal_elapsed_s"]) < 0.01
                assert row["desired_positions"][0] == pytest.approx(
                    min(0.04, max(0.0, row["nominal_elapsed_s"] * 0.1))
                )
            assert core.get_state()["arms"][0]["positions"][0] == pytest.approx(0.04, abs=0.003)
        finally:
            core.close()


def test_native_dual_advance_and_shared_nominal_start():
    with MockRobot(positions=[0.0] * 6) as left, MockRobot(positions=[0.0] * 6) as right:
        core = native.Controller([arm(left, "left", advance_ms=80), arm(right, "right")])
        core.connect()
        try:
            start = time.time_ns() + 250_000_000
            core.execute([0.0, 0.3], [[0.0] * 12, [0.03] * 12], start)
            result = wait_result(core)
            assert result["status"] == "succeeded", result
            stats = core.diagnostics()["arms"]
            assert abs(stats[0]["first_send_stamp"] - (start - 80_000_000)) < 40_000_000
            assert abs(stats[1]["first_send_stamp"] - start) < 40_000_000
        finally:
            core.close()


def test_native_timeout_does_not_refresh_stamp_and_aborts_stale():
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock, read_timeout=0.02, state_timeout=0.08)])
        core.connect()
        try:
            core.execute([0.0, 2.0], [[0.0] * 6, [0.1] * 6])
            wait_for(lambda: core.diagnostics()["arms"][0]["sends"] > 2)
            mock.set_faults(read_delay=0.3)
            wait_for(lambda: core.diagnostics()["arms"][0]["read_timeouts"] >= 2)
            stamp = core.get_state()["arms"][0]["stamp_unix_ns"]
            time.sleep(0.05)
            assert core.get_state()["arms"][0]["stamp_unix_ns"] == stamp
            result = wait_result(core)
            assert result["status"] == "aborted", result
            assert "No fresh state" in result["message"]
            assert core.drain_samples()  # Failure still retains measurements for plotting.
        finally:
            core.close()


def test_native_dual_cancel_stops_both():
    with MockRobot(positions=[0.0] * 6) as left, MockRobot(positions=[0.0] * 6) as right:
        core = native.Controller([arm(left, "left"), arm(right, "right")])
        core.connect()
        try:
            core.execute([0.0, 2.0], [[0.0] * 12, [0.1] * 12])
            wait_for(lambda: all(s["sends"] > 2 for s in core.diagnostics()["arms"]))
            core.cancel()
            assert wait_result(core)["status"] == "cancelled"
            before = [s["sends"] for s in core.diagnostics()["arms"]]
            time.sleep(0.05)
            assert before == [s["sends"] for s in core.diagnostics()["arms"]]
        finally:
            core.close()


def test_native_stop_failure_latches_and_preserves_original_reason():
    with MockRobot(positions=[0.0] * 6, fail_clear=True) as mock:
        core = native.Controller([arm(mock, allow_protective_stop_release=True)])
        core.connect()
        try:
            core.execute([0.0, 2.0], [[0.0] * 6, [0.1] * 6])
            wait_for(lambda: core.diagnostics()["arms"][0]["sends"] > 2)
            core.cancel()
            result = wait_result(core)
            assert result["status"] == "aborted"
            for text in [
                "Cancelled by client",
                "Stop/Clear failed",
                "arm=single",
                "joint=single_joint_0",
                "desired_rad",
                "actual_rad",
                "physical stop is NOT confirmed",
            ]:
                assert text in result["message"]
            assert core.diagnostics()["fault"]
            with pytest.raises(RuntimeError, match="fault latched"):
                core.execute([0.0], [[0.0] * 6])
        finally:
            core.close()


def test_native_endpoint_requires_measured_arrival():
    with MockRobot(positions=[0.0] * 6, lag=1.0) as mock:
        core = native.Controller([arm(mock, goal_time_tolerance=0.08)])
        core.connect()
        try:
            core.execute([0.0, 0.2], [[0.0] * 6, [0.02] * 6])
            result = wait_result(core)
            assert result["status"] == "aborted", result
            assert "Missed endpoint deadline" in result["message"]
        finally:
            core.close()


def test_native_rejects_start_mismatch_and_bad_derivatives_without_motion():
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock)])
        core.connect()
        try:
            with pytest.raises(ValueError, match="Start mismatch"):
                core.execute([0.0, 1.0], [[1.0] * 6, [1.1] * 6])
            with pytest.raises(ValueError, match="Accelerations require velocities"):
                core.execute([0.0, 1.0], [[0.0] * 6, [0.1] * 6], 0, [], [[0.0] * 6] * 2)
            with pytest.raises(ValueError, match="strictly increasing"):
                core.execute([0.0, 0.0], [[0.0] * 6, [0.1] * 6])
            assert core.diagnostics()["arms"][0]["sends"] == 0
        finally:
            core.close()


@pytest.mark.parametrize(
    "key,value",
    [
        ("command_rate", 126),
        ("read_timeout", float("nan")),
        ("gain", float("inf")),
        ("advance_ms", -1),
    ],
)
def test_native_rejects_invalid_configuration(key, value):
    config = Arm("single", "127.0.0.1").to_dict()
    config[key] = value
    with pytest.raises(ValueError):
        native.Controller([config])


@pytest.mark.parametrize("derivatives", [1, 2])
def test_native_explicit_derivative_interpolation(derivatives):
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock)])
        core.connect()
        try:
            zero = [[0.0] * 6] * 2
            goal = core.execute(
                [0.0, 0.5], [[0.0] * 6, [0.02] * 6], 0, zero, zero if derivatives == 2 else []
            )
            result = wait_result(core)
            assert result["status"] == "succeeded", result
            for row in core.drain_samples():
                if row["goal_id"] != goal:
                    continue
                u = min(1.0, max(0.0, row["nominal_elapsed_s"] / 0.5))
                blend = (
                    3 * u * u - 2 * u**3 if derivatives == 1 else 10 * u**3 - 15 * u**4 + 6 * u**5
                )
                assert row["desired_positions"][0] == pytest.approx(0.02 * blend)
        finally:
            core.close()


def test_native_rate_and_servoj_parameters_reach_wire(tmp_path):
    import json

    log = tmp_path / "wire.jsonl"
    with MockRobot(positions=[0.0] * 6, log=str(log)) as mock:
        core = native.Controller(
            [
                arm(
                    mock,
                    command_rate=30.0,
                    read_rate=60.0,
                    servo_a=4.0,
                    servo_v=2.0,
                    lookahead_time=0.02,
                    gain=10.0,
                )
            ]
        )
        core.connect()
        try:
            core.execute([0.0, 0.3], [[0.0] * 6, [0.01] * 6])
            assert wait_result(core)["status"] == "succeeded"
        finally:
            core.close()
    commands = [
        row
        for line in log.read_text().splitlines()
        if (row := json.loads(line))["kind"] == "servoj"
    ]
    assert 6 <= len(commands) <= 20
    for row in commands:
        assert row["parameters"] == pytest.approx([4.0, 2.0, 1 / 30, 0.02, 10.0], abs=1e-5)


def test_native_unknown_parameter_is_not_silently_ignored():
    config = Arm("single", "127.0.0.1").to_dict()
    config["state_timout"] = 0.1
    with pytest.raises(ValueError, match="Unknown arm parameter: state_timout"):
        native.Controller([config])


def test_native_servo_loop_does_not_depend_on_python_gil():
    import sys

    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock)])
        core.connect()
        interval = sys.getswitchinterval()
        try:
            core.execute([0.0, 0.6], [[0.0] * 6, [0.03] * 6])
            wait_for(lambda: core.diagnostics()["arms"][0]["sends"] >= 3)
            before = core.diagnostics()["arms"][0]["sends"]
            sys.setswitchinterval(1.0)
            finish = time.monotonic() + 0.25
            while time.monotonic() < finish:
                pass  # Python owns the GIL continuously; native I/O must continue.
            after = core.diagnostics()["arms"][0]["sends"]
            assert after - before >= 20
            assert wait_result(core)["status"] == "succeeded"
        finally:
            sys.setswitchinterval(interval)
            core.close()


def test_native_rejects_concurrent_goal_and_negative_start():
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock)])
        core.connect()
        try:
            with pytest.raises(ValueError, match="nonnegative"):
                core.execute([0.0], [[0.0] * 6], -(2**63))
            original = core.execute([0.0, 0.4], [[0.0] * 6, [0.02] * 6])
            with pytest.raises(RuntimeError, match="Another goal"):
                core.execute([0.0], [[0.0] * 6])
            assert wait_result(core)["goal_id"] == original
        finally:
            core.close()


def test_native_reconnect_never_replays_previous_goal():
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock)])
        core.connect()
        core.execute([0.0, 0.2], [[0.0] * 6, [0.01] * 6])
        assert wait_result(core)["status"] == "succeeded"
        core.close()
        before = core.diagnostics()["arms"][0]["sends"]
        core.connect()
        try:
            time.sleep(0.1)
            assert core.diagnostics()["arms"][0]["sends"] == before
            assert not core.get_state()["active"]
        finally:
            core.close()


def test_native_default_cleanup_never_releases_protective_stop(tmp_path):
    import json

    log = tmp_path / "no_unlock.jsonl"
    with MockRobot(positions=[0.0] * 6, fail_clear=True, log=str(log)) as mock:
        core = native.Controller([arm(mock)])
        core.connect()
        try:
            core.execute([0.0, 0.15], [[0.0] * 6, [0.01] * 6])
            result = wait_result(core)
            assert result["status"] == "succeeded", result
            assert "API_Clear skipped" in result["message"]
            assert "queue purge is NOT confirmed" in result["message"]
            assert core.diagnostics()["arms"][0]["clear_status"] == "skipped_not_authorized"
        finally:
            core.close()
    kinds = [json.loads(line)["kind"] for line in log.read_text().splitlines()]
    assert "stop" in kinds
    assert "clear" not in kinds


def test_native_state_desired_reference_is_nominal_and_keeps_measurement_stamp():
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock, advance_ms=150.0, read_rate=1.0, state_timeout=2.0)])
        core.connect()
        try:
            measured = core.get_state()["arms"][0]
            assert measured["desired_positions"] is None
            assert measured["goal_id"] is None
            start = time.time_ns() + 300_000_000
            goal = core.execute([0.0, 0.5], [[0.0] * 6, [0.05] * 6], start)
            wait_for(lambda: time.time_ns() >= start + 50_000_000)
            current = core.get_state()["arms"][0]
            assert current["goal_id"] == goal
            assert current["start_unix_ns"] == start
            assert current["stamp_unix_ns"] == measured["stamp_unix_ns"]
            assert current["received_monotonic_ns"] == measured["received_monotonic_ns"]
            assert current["positions"] == measured["positions"]
            elapsed = current["nominal_elapsed_s"]
            assert 0.0 <= elapsed < 0.4
            assert current["desired_positions"][0] == pytest.approx(0.1 * elapsed)
            assert current["desired_positions"][0] != pytest.approx(0.1 * (elapsed + 0.15))
            assert abs((current["desired_stamp_unix_ns"] - start) / 1e9 - elapsed) < 0.01
            core.cancel()
            assert wait_result(core)["status"] == "cancelled"
            ended = core.get_state()["arms"][0]
            for key in (
                "desired_positions",
                "goal_id",
                "start_unix_ns",
                "desired_stamp_unix_ns",
                "nominal_elapsed_s",
            ):
                assert ended[key] is None
        finally:
            core.close()


def test_final_target_is_sent_even_when_previous_point_is_within_tolerance(tmp_path):
    import json

    log = tmp_path / "wire.jsonl"
    with MockRobot(positions=[0.0] * 6, log=str(log)) as mock:
        core = native.Controller([arm(mock, command_rate=20, goal_tolerance=0.01)])
        core.connect()
        try:
            # End time lies between send ticks; previous tick is already in tolerance.
            core.execute([0.0, 0.075], [[0.0] * 6, [0.001] * 6])
            assert wait_result(core)["status"] == "succeeded"
            sends = [
                row
                for row in map(json.loads, log.read_text().splitlines())
                if row["kind"] == "servoj"
            ]
            assert sends[-1]["positions"] == [0.001] * 6
        finally:
            core.close()


@pytest.mark.parametrize("resolution", [0, 1])
def test_native_windows_timer_request_is_scoped_to_connected_controller(resolution):
    import sys

    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock, windows_timer_resolution_ms=resolution)])
        core.connect()
        try:
            diagnostics = core.diagnostics()
            assert diagnostics["arms"][0]["windows_timer_resolution_ms"] == resolution
            expected = (
                ("disabled_by_configuration" if resolution == 0 else "requested_1_ms_best_effort")
                if sys.platform == "win32"
                else "not_applicable_on_this_platform"
            )
            assert diagnostics["windows_timer_status"] == expected
        finally:
            core.close()
        assert core.diagnostics()["windows_timer_status"] == "released_on_close"
        # Repeated close must not decrement another controller's timer request.
        core.close()
        assert core.diagnostics()["windows_timer_status"] == "released_on_close"


def test_native_timer_request_released_when_sdk_loading_fails(tmp_path):
    import sys

    config = Arm("single", "127.0.0.1").to_dict()
    config["sdk_library"] = str(tmp_path / "missing_机器人.dll")
    config["windows_timer_resolution_ms"] = 1
    core = native.Controller([config])
    try:
        with pytest.raises(RuntimeError, match="Cannot load SDK") as failure:
            core.connect()
        if sys.platform == "win32":
            assert "resolved='" in str(failure.value)
            assert "missing_机器人.dll" in str(failure.value)
            assert "Win32 error=" in str(failure.value)
        assert core.diagnostics()["windows_timer_status"] == "released_after_startup_failure"
    finally:
        core.close()


@pytest.mark.parametrize("resolution", [-1, 1001])
def test_native_rejects_invalid_windows_timer_resolution(resolution):
    config = Arm("single", "127.0.0.1").to_dict()
    config["windows_timer_resolution_ms"] = resolution
    with pytest.raises(ValueError, match="windows_timer_resolution_ms"):
        native.Controller([config])


def test_native_slow_reads_do_not_add_a_second_idle_period():
    with MockRobot(positions=[0.0] * 6, read_delay=0.045) as mock:
        core = native.Controller([arm(mock, read_rate=25.0, read_timeout=0.2)])
        core.connect()
        try:
            before = core.diagnostics()["arms"][0]["read_calls"]
            started = time.monotonic()
            time.sleep(0.8)
            elapsed = time.monotonic() - started
            count = core.diagnostics()["arms"][0]["read_calls"] - before
            # A 45 ms transaction should run near its available ~22 Hz, not
            # 45 ms + an unnecessary 40 ms sleep (~12 Hz). Allow OS jitter.
            assert count / elapsed > 16.0
        finally:
            core.close()


def test_native_cancel_interrupts_long_future_start_and_next_goal_resets_cancel():
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock)])
        core.connect()
        try:
            core.execute([0.0, 0.2], [[0.0] * 6, [0.01] * 6], time.time_ns() + 6_000_000_000)
            time.sleep(0.03)
            started = time.monotonic()
            core.cancel()
            assert wait_result(core, timeout=0.8)["status"] == "cancelled"
            assert time.monotonic() - started < 0.8
            assert core.diagnostics()["arms"][0]["sends"] == 0
            core.execute([0.0, 0.2], [[0.0] * 6, [0.01] * 6])
            assert wait_result(core)["status"] == "succeeded"
        finally:
            core.close()


def test_native_close_interrupts_reader_wait():
    with MockRobot(positions=[0.0] * 6) as mock:
        core = native.Controller([arm(mock, read_rate=1.0, state_timeout=2.0)])
        core.connect()
        time.sleep(0.03)
        started = time.monotonic()
        core.close()
        assert time.monotonic() - started < 0.8


@pytest.mark.parametrize("key", ["command_rate", "read_rate"])
@pytest.mark.parametrize("value", [1e-300, float.fromhex("0x0.0000000000001p-1022"), 0.009999])
def test_native_rejects_tiny_finite_rates_before_sdk_loading(key, value):
    config = Arm("single", "127.0.0.1").to_dict()
    config["sdk_library"] = "must-not-load-sdk-for-invalid-rate"
    config[key] = value
    with pytest.raises(ValueError, match=rf"{key}.*0\.01\.\.125 Hz"):
        native.Controller([config])


@pytest.mark.parametrize("rate", [0.01, 0.05, 125.0])
def test_native_accepts_representable_rate_bounds_without_connecting(rate):
    config = Arm("single", "127.0.0.1").to_dict()
    config["sdk_library"] = "no-sdk-loading-during-construction"
    config["command_rate"] = config["read_rate"] = rate
    core = native.Controller([config])
    try:
        assert not core.get_state()["connected"]
    finally:
        core.close()


@pytest.mark.parametrize("key", ["servo_a", "servo_v"])
@pytest.mark.parametrize("value", [1e-300, float.fromhex("0x0.0000000000001p-1022")])
def test_native_rejects_servo_values_that_underflow_sdk_float(key, value):
    config = Arm("single", "127.0.0.1").to_dict()
    config["sdk_library"] = "must-not-load-sdk-for-invalid-servo-value"
    config[key] = value
    with pytest.raises(ValueError, match=rf"{key}.*encoded as an SDK float"):
        native.Controller([config])
