"""Actual native viewer process smoke, exclusively against localhost mock robots."""

import ctypes
import json
import time
from contextlib import ExitStack
from pathlib import Path

from PIL import ImageGrab

from iimt import Robot, ci05_scene
from iimt.mock import MockRobot


def main():
    output = Path(r"\\host.lan\Data\gui")
    output.mkdir(exist_ok=True)
    for dual in (False, True):
        with ExitStack() as stack:
            mocks = [stack.enter_context(MockRobot()) for _ in range(2 if dual else 1)]
            scene = ci05_scene(dual=dual)
            if dual:
                robot = Robot.dual(
                    mocks[0].host,
                    mocks[1].host,
                    left_port=mocks[0].port,
                    right_port=mocks[1].port,
                    scene=scene,
                    enable_motion=True,
                )
            else:
                robot = Robot.single(
                    mocks[0].host, port=mocks[0].port, scene=scene, enable_motion=True
                )
            try:
                robot.connect(viewer=True)
                q = [v for arm in robot.get_state()["arms"] for v in arm["positions"]]
                q[0] += 0.01
                plan = robot.plan(q, timeout=3)
                result = robot.execute_trajectory(plan, start_delay=1).wait(15)
                assert result["status"] == "succeeded", result
                time.sleep(3)
                user = ctypes.WinDLL("user32")
                user.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
                user.FindWindowW.restype = ctypes.c_void_p
                window = user.FindWindowW(None, "IIMT — measured / target / plan")
                assert window, "Actual native viewer window is missing"
                user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
                user.SetForegroundWindow(window)
                time.sleep(1)
                ImageGrab.grab().save(output / f"{'dual' if dual else 'single'}.png")
                print(json.dumps({"dual": dual, "native_window": window, "result": result}))
            finally:
                robot.close()
    print("PASS actual single/dual native Windows viewer + RRTConnect + SDK mock execution")


if __name__ == "__main__":
    main()
