"""Wire cadence and simulated lag need a high-resolution monotonic clock."""

import io
import json

import iimt.mock as mock_module


def test_mock_records_high_resolution_clock(monkeypatch):
    state = mock_module._State({})
    state.log = io.StringIO()
    monkeypatch.setattr(mock_module.time, "perf_counter_ns", lambda: 123456789)
    monkeypatch.setattr(mock_module.time, "monotonic_ns", lambda: 0)
    state.record("servoj")
    assert json.loads(state.log.getvalue())["monotonic_ns"] == 123456789


def test_mock_lag_uses_same_high_resolution_clock(monkeypatch):
    state = mock_module._State({})
    expected = [0.1] * 6
    state.queue.append((10.008, expected))
    monkeypatch.setattr(mock_module.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(mock_module.time, "perf_counter", lambda: 10.007)
    state.apply_due()
    assert state.q != expected
    monkeypatch.setattr(mock_module.time, "perf_counter", lambda: 10.009)
    state.apply_due()
    assert state.q == expected
