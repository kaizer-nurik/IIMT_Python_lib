"""Render installed CI05 meshes in native OpenGL/ImGui under Xvfb, offline."""

from iimt import _viewer, ci05_scene
from iimt.mock import DEFAULT_Q

for dual in (False, True):
    scene = ci05_scene(dual=dual)
    model = scene.model()
    q = list(DEFAULT_Q) * (2 if dual else 1)
    limits = model.limits()
    geometry = model.geometry_local()
    assert geometry and any(len(mesh["vertices"]) for mesh in geometry)
    viewer = _viewer.Viewer("Linux ABI smoke", 640, 480)
    try:
        viewer.set_geometry(geometry)
        for _ in range(4):
            result = viewer.update(
                None,
                q,
                limits["lower"],
                limits["upper"],
                "Offline ABI smoke",
                transforms=model.transforms(q),
            )
            assert isinstance(result, dict), result
    finally:
        viewer.close()
print(
    "PASS native GUI: actual CI05 meshes, cached transforms, single/dual frames, close/reopen; no robot connections"
)
