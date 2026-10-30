"""Check actual spawned viewer pixels in an isolated Xvfb display, using local mocks."""

import argparse
import os
import time
from contextlib import ExitStack
from pathlib import Path

from PIL import ImageGrab

from iimt import Robot
from iimt.mock import MockRobot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/gui-smoke"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for dual in (False, True):
        with ExitStack() as stack:
            mocks = [stack.enter_context(MockRobot()) for _ in range(2 if dual else 1)]
            robot = (
                Robot.dual(
                    mocks[0].host,
                    mocks[1].host,
                    left_port=mocks[0].port,
                    right_port=mocks[1].port,
                )
                if dual
                else Robot.single(mocks[0].host, port=mocks[0].port)
            )
            try:
                robot.connect(viewer=True)
                deadline = time.monotonic() + 5
                while True:
                    assert robot._viewer.is_alive(), "Spawned viewer exited before rendering"
                    frame = ImageGrab.grab(xdisplay=os.environ["DISPLAY"])
                    # This display contains only our window. A successful update()
                    # alone did not detect the old split-GLdispatch all-black frame.
                    rendered = frame.getcolors(maxcolors=64) is None
                    if rendered or time.monotonic() >= deadline:
                        break
                    time.sleep(0.1)
                frame.save(args.output / f"{'dual' if dual else 'single'}.png")
                assert rendered, "Viewer produced no rendered scene/UI pixels"
                print(f"PASS actual spawned viewer, dual={dual}: rendered pixels saved", flush=True)
            finally:
                robot.close()


if __name__ == "__main__":
    main()
