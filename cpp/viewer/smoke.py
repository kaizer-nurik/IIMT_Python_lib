"""Display smoke: xvfb-run -a python cpp/viewer/smoke.py [module-build-directory]."""

import sys
import threading

if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])
    from _viewer import Viewer
else:
    from iimt._viewer import Viewer

import numpy as np


def reject(call, text):
    try:
        call()
    except (ValueError, RuntimeError) as error:
        assert text in str(error), (text, str(error))
    else:
        raise AssertionError(f"Expected rejection containing {text!r}")


q = [0.0] * 6
lo, hi = [-3.0] * 6, [3.0] * 6
mesh = {
    "name": "link/0",
    "link": "link",
    "vertices": np.array([[0, 0, 0], [0.2, 0, 0.3], [0, 0.2, 0.3]]),
    "triangles": np.array([[0, 1, 2]], dtype=np.int32),
    "color": [0.3, 0.7, 0.9, 1.0],
}
viewer = Viewer("IIMT native viewer smoke", 900, 700)
try:
    reject(lambda: Viewer("duplicate"), "Only one")
    for _ in range(4):
        result = viewer.update(
            [mesh], q, lo, hi, "Test: no robot transport", [-1, 1, -1, 1], 0.0
        )
        assert result == {"open": True, "target": q, "action": None}
    reject(lambda: viewer.update(None, [0], [0], [1], "bad"), "6 or 12")
    reject(lambda: viewer.update(None, q, lo, hi, "bad", [1, -1, -1, 1]), "xmin")
    bad = dict(mesh, triangles=[[0, 1, 99]])
    reject(lambda: viewer.update([bad], q, lo, hi, "bad"), "triangle index")
    viewer.set_geometry([mesh])
    reject(lambda: viewer.update(None, q, lo, hi, "missing"), "requires transforms")
    reject(
        lambda: viewer.update(None, q, lo, hi, "missing", transforms={}),
        "Missing transform",
    )
    transform = np.eye(4).tolist()
    for index in range(10):
        transform[0][3] = index * 0.01
        result = viewer.update(
            None,
            q,
            lo,
            hi,
            "Cached mesh / pose-only updates",
            transforms={"link": transform},
        )
        assert result["action"] is None
    # 12-joint controls render without introducing an implicit execution event.
    result = viewer.update(None, q * 2, lo * 2, hi * 2, "Dual arm targets")
    assert result["target"] == q * 2 and result["action"] is None
    errors = []

    def wrong_thread():
        try:
            viewer.close()
        except RuntimeError as error:
            errors.append(str(error))

    thread = threading.Thread(target=wrong_thread)
    thread.start()
    thread.join()
    assert len(errors) == 1 and "creating thread" in errors[0]
finally:
    viewer.close()
viewer.close()
assert not viewer.update(None, q, lo, hi, "closed")["open"]
# Closing releases GLFW/ImGui ownership and allows a replacement viewer.
replacement = Viewer("Replacement", 640, 480)
replacement.close()
print(
    "PASS: viewer render, cached transforms, single/dual controls, input validation, thread ownership, close/reopen"
)
