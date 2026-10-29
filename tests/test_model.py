"""Native geometry checks. All fixtures are local URDFs; no robot connections."""

import math

import numpy as np
import pytest

from iimt import _model

NAMES = [f"j{i}" for i in range(6)]


def write_model(tmp_path, *, obstacle=False, change="", names=NAMES):
    # Six independent branches make FK/collision assertions easy to inspect.
    parts = ['<robot name="fixture"><link name="base"/>']
    for i, name in enumerate(names):
        parts.append(f"""
          <link name="l{i}">
            <collision><origin xyz="1 0 .5"/>
              <geometry><sphere radius=".1"/></geometry></collision>
            <visual><origin xyz="1 0 .5"/>
              <geometry><sphere radius=".1"/></geometry></visual>
          </link>
          <joint name="{name}" type="revolute">
            <parent link="base"/><child link="l{i}"/>
            <origin xyz="{i * 3} 0 0"/><axis xyz="0 0 1"/>
            <limit lower="-3" upper="3" velocity="2" effort="1"/>
          </joint>""")
    if obstacle:
        parts.append("""<link name="obstacle"><collision>
          <origin xyz="1 0 .5"/><geometry><sphere radius=".1"/></geometry>
          </collision></link><joint name="mount" type="fixed">
          <parent link="base"/><child link="obstacle"/></joint>""")
    parts.append(change)
    parts.append("</robot>")
    path = tmp_path / "model.urdf"
    path.write_text("".join(parts))
    return path


def test_fk_and_mesh_transform(tmp_path):
    model = _model.Model(str(write_model(tmp_path)), NAMES)
    q = [0.7, 0, 0, 0, 0, 0]
    transform = np.asarray(model.transforms(q)["l0"])
    assert np.allclose(
        transform[:3, :3],
        [
            [math.cos(0.7), -math.sin(0.7), 0],
            [math.sin(0.7), math.cos(0.7), 0],
            [0, 0, 1],
        ],
    )
    local = model.geometry_local()[0]
    world = model.geometry(q)[0]
    expected = np.asarray(local["vertices"]) @ transform[:3, :3].T + transform[:3, 3]
    assert np.allclose(expected, world["vertices"])
    assert local["link"] == "l0"
    assert model.limits()["velocity"] == [2.0] * 6


def test_rrtconnect_checked_path(tmp_path):
    model = _model.Model(str(write_model(tmp_path)), NAMES)
    start, goal = [0.0] * 6, [0.3, -0.2, 0.1, 0.0, 0.0, 0.2]
    path = model.plan(start, goal, timeout=1.0, resolution=0.02)
    assert path[0] == start
    assert path[-1] == goal
    assert all(model.check(q)["valid"] for q in path)
    # A straight free-space connection stays sparse: checking samples are not stops.
    assert len(path) == 2
    for left, right in zip(path, path[1:]):
        steps = max(1, int(np.ceil(np.max(np.abs(np.array(right) - left)) / 0.02)))
        assert all(model.check(q.tolist())["valid"] for q in np.linspace(left, right, steps + 1))


def test_interlink_collision_is_not_implicitly_disabled(tmp_path):
    path = write_model(tmp_path, obstacle=True)
    model = _model.Model(str(path), NAMES)
    result = model.check([0.0] * 6)
    assert not result["valid"]
    assert ("l0", "obstacle") in result["collisions"]
    with pytest.raises(ValueError, match="Invalid planning start"):
        model.plan([0.0] * 6, [0.5] * 6)
    assert _model.Model(str(path), NAMES, disabled_collisions=[("l0", "obstacle")]).check(
        [0.0] * 6
    )["valid"]


def test_floor_workspace_and_no_ceiling(tmp_path):
    path = str(write_model(tmp_path))
    q = [0.0] * 6
    assert _model.Model(path, NAMES, floor_z=0.0, workspace=[-1.0, 20.0, -2.0, 2.0]).check(q)[
        "valid"
    ]
    assert not _model.Model(path, NAMES, floor_z=0.5).check(q)["valid"]
    result = _model.Model(path, NAMES, workspace=[-1.0, 0.9, -2.0, 2.0]).check(q)
    assert not result["valid"]
    assert any("__x_max__" in pair for pair in result["collisions"])
    with pytest.raises(ValueError, match="Only fixed base"):
        _model.Model(path, NAMES, floor_z=0.5, disabled_collisions=[("l0", "__floor__")])
    # A plane has no hidden ceiling or solid half-space below it.
    assert _model.Model(path, NAMES, floor_z=10.0).check(q)["valid"]


def test_joint_limits_and_nonfinite(tmp_path):
    model = _model.Model(str(write_model(tmp_path)), NAMES)
    assert not model.check([4.0] * 6)["valid"]
    with pytest.raises(ValueError, match="Nonfinite"):
        model.check([float("nan")] * 6)
    with pytest.raises(ValueError, match="dimension"):
        model.check([0.0])
    with pytest.raises(ValueError, match="resolution"):
        model.plan([0.0] * 6, [0.0] * 6, resolution=0.0)


def test_invalid_urdf_fails_closed(tmp_path):
    path = write_model(tmp_path)
    text = path.read_text().replace('type="revolute"', 'type="prismatic"', 1)
    path.write_text(text)
    with pytest.raises(ValueError, match="Unsupported joint"):
        _model.Model(str(path), NAMES)
    path = write_model(tmp_path)
    text = path.read_text().replace('<sphere radius=".1"/>', '<capsule radius=".1"/>', 1)
    path.write_text(text)
    with pytest.raises(ValueError, match="Unsupported URDF geometry"):
        _model.Model(str(path), NAMES)


def test_dual_twelve_joints(tmp_path):
    names = [f"j{i}" for i in range(12)]
    model = _model.Model(str(write_model(tmp_path, names=names)), names)
    assert model.check([0.0] * 12)["valid"]
    assert len(model.limits()["lower"]) == 12


def test_collision_free_endpoints_do_not_allow_crossing_obstacle(tmp_path):
    model = _model.Model(str(write_model(tmp_path, obstacle=True)), NAMES)
    start, goal = [-0.5, 0, 0, 0, 0, 0], [0.5, 0, 0, 0, 0, 0]
    assert model.check(start)["valid"] and model.check(goal)["valid"]
    with pytest.raises(RuntimeError, match="exact collision-checked solution"):
        model.plan(start, goal, timeout=0.05, resolution=0.02)


def test_assimp_mesh_scale_package_mapping_and_missing_mesh(tmp_path):
    (tmp_path / "triangle.stl").write_text("""solid triangle
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 1 0 0
vertex 0 1 0
endloop
endfacet
endsolid triangle
""")
    path = write_model(tmp_path)
    path.write_text(
        path.read_text().replace(
            '<sphere radius=".1"/>',
            '<mesh filename="package://fixtures/triangle.stl" scale="2 3 4"/>',
            2,
        )
    )
    model = _model.Model(str(path), NAMES, package_paths={"fixtures": str(tmp_path)})
    vertices = model.geometry_local()[0]["vertices"]
    assert {tuple(row) for row in vertices} == {
        (1.0, 0.0, 0.5),
        (3.0, 0.0, 0.5),
        (1.0, 3.0, 0.5),
    }
    with pytest.raises(ValueError, match="package path mapping"):
        _model.Model(str(path), NAMES)
    (tmp_path / "triangle.stl").unlink()
    with pytest.raises(ValueError, match="does not exist"):
        _model.Model(str(path), NAMES, package_paths={"fixtures": str(tmp_path)})


def test_floor_exemption_limited_to_fixed_mount(tmp_path):
    path = write_model(
        tmp_path,
        change="""
      <link name="fixed_foot"><collision><geometry><box size=".2 .2 .2"/>
      </geometry></collision></link>
      <joint name="foot_mount" type="fixed"><parent link="base"/>
      <child link="fixed_foot"/></joint>""",
    )
    blocked = _model.Model(str(path), NAMES, floor_z=0.0)
    assert not blocked.check([0.0] * 6)["valid"]
    allowed = _model.Model(
        str(path), NAMES, floor_z=0.0, disabled_collisions=[("fixed_foot", "__floor__")]
    )
    assert allowed.check([0.0] * 6)["valid"]
    with pytest.raises(ValueError, match="Unknown/self"):
        _model.Model(str(path), NAMES, disabled_collisions=[("absent", "l0")])


@pytest.mark.parametrize("package_uri", [False, True])
def test_unicode_urdf_directory_filename_and_mesh(tmp_path, package_uri):
    directory = tmp_path / "робот_机器人"
    directory.mkdir()
    mesh = directory / "звено_三角.stl"
    mesh.write_text(
        "solid triangle\nfacet normal 0 0 1\nouter loop\n"
        "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
        "endloop\nendfacet\nendsolid triangle\n",
        encoding="utf-8",
    )
    path = write_model(directory).rename(directory / "модель_机械臂.urdf")
    uri = f"package://fixtures/{mesh.name}" if package_uri else mesh.name
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '<sphere radius=".1"/>', f'<mesh filename="{uri}"/>', 2
        ),
        encoding="utf-8",
    )
    model = _model.Model(str(path), NAMES, package_paths={"fixtures": str(directory)})
    assert len(model.geometry_local()[0]["vertices"]) == 3
    assert len(model.transforms([0.0] * 6)) == 7
