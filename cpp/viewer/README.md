# Native viewer

`iimt._viewer.Viewer` owns one GLFW/OpenGL window and Dear ImGui context in its
process. Construct, update and close it on the same thread. It has no robot SDK,
network code, planner or controller dependency; UI buttons return events only.
The public Python layer is responsible for checking and dispatching those events.
Closing a window does not itself confirm a physical robot stop.

## Rendering interface

```python
viewer = Viewer("IIMT")
viewer.set_geometry(model.geometry_local())  # upload/convert static vertices once
while True:
    event = viewer.update(
        None, target, lower, upper, status,
        workspace=[xmin, xmax, ymin, ymax], floor_z=floor,
        transforms=model.transforms(measured_q),
    )
    if not event["open"]:
        break
    target = event["target"]
    # event["action"] is None, 'plan', 'execute', or 'cancel'.
viewer.close()
```

Each static mesh needs `link`, `vertices`, `triangles`, and optionally `color` RGBA.
Vertices must be link-local, with the URDF visual origin already applied.
Transforms are row-major 4-by-4 matrices keyed by `link`. For desired/planned ghost
layers, prefix their link keys and matching transform keys, and assign a distinct
color/alpha. Missing first-frame transforms are rejected rather than showing a
plausible but incorrect pose. `meshes=None` reuses the existing geometry.
The legacy `update(world_meshes, ...)` path also accepts already transformed meshes.
NumPy arrays and nested lists are accepted for mesh coordinates and indices.

Left drag orbits; right drag pans; wheel zooms. Z is up. `Frame robot` fits current
geometry. World axes and floor grid are drawn, with workspace perimeter/uprights;
there is deliberately no ceiling. Alpha overlays are for visualization only,
not exact order-independent transparency. Joint sliders edit targets and never
produce an execute event. Plan, Execute and Cancel are separate explicit buttons.

## Build and checks

- CMake includes `cpp/viewer.cmake`; requires pybind11, OpenGL, GLFW, Dear ImGui.
- Ubuntu system package: `libglfw3-dev libgl1-mesa-dev libimgui-dev`.
- vcpkg: `glfw3`, `imgui[glfw-binding,opengl2-binding]`. Backend header layouts
  differ between Debian and vcpkg and are handled explicitly.
- Rendering requires an OpenGL 2.1-compatible display/driver; headless controller
  operation should not import this module.
- `xvfb-run -a python cpp/viewer/smoke.py` checks the installed module. An optional
  build-directory argument imports `_viewer` directly for focused development.
- Native Windows runtime/build validation is still a release gate; source paths
  and dependency configuration alone are not proof of Windows support.

Implementation references: official GLFW quick-start
(https://www.glfw.org/docs/latest/quick.html), official Dear ImGui GLFW/OpenGL2
example (https://github.com/ocornut/imgui/tree/v1.90.1/examples/example_glfw_opengl2),
and vcpkg backend packaging (https://github.com/microsoft/vcpkg/tree/master/ports/imgui).
