"""Generate mount transforms without xacro/ROS. Meshes remain byte-identical."""

from __future__ import annotations

import copy
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from .config import ASSETS, JOINTS, Scene

LEFT_BASE = (-0.0008297, -0.538, 0.0818739, 0.0, 0.0, -0.6981317008)
RIGHT_RELATIVE = (-0.345440489323, 0.411679944176, -0.082, 0.0, 0.0, 0.0)


def transform(pose):
    x, y, z, r, p, w = np.asarray(pose, dtype=float)
    cr, sr, cp, sp, cw, sw = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(w), np.sin(w)
    t = np.eye(4)
    t[:3, :3] = [
        [cw * cp, cw * sp * sr - sw * cr, cw * sp * cr + sw * sr],
        [sw * cp, sw * sp * sr + cw * cr, sw * sp * cr - cw * sr],
        [-sp, cp * sr, cp * cr],
    ]
    t[:3, 3] = x, y, z
    return t


def ci05_scene(
    dual=False,
    *,
    left_base=None,
    right_relative=RIGHT_RELATIVE,
    margins=(0.5, 0.5, 0.5, 0.5),
    floor_z=None,
    output=None,
) -> Scene:
    """Margins: x-minus, x-plus, y-minus, y-plus; right pose is relative to LEFT.

    Default single base is world origin; dual uses calibrated ROS-package mounts.
    File is generated in a private temporary directory unless output is supplied.
    """
    left_base = left_base if left_base is not None else (LEFT_BASE if dual else (0,) * 6)
    poses = [left_base, right_relative] if dual else [left_base]
    for pose in poses:
        if len(pose) != 6 or not np.isfinite(pose).all():
            raise ValueError("Mount poses must contain six finite xyz/rpy values")
    if len(margins) != 4 or not np.isfinite(margins).all() or min(margins) <= 0:
        raise ValueError("Four finite positive workspace margins are required")
    root = ET.Element("robot", name="iimt_dual" if dual else "iimt_ci05")
    ET.SubElement(root, "link", name="world")
    template = ET.parse(ASSETS / "ci05.urdf").getroot()
    prefixes = ["left_", "right_"] if dual else [""]
    names, disabled = [], []
    base_pairs = json.loads((ASSETS / "disabled_pairs.json").read_text())
    for index, prefix in enumerate(prefixes):
        for element in template:
            element = copy.deepcopy(element)
            if element.tag not in {"link", "joint", "material"}:
                continue
            if element.tag in {"link", "joint"}:
                element.set("name", prefix + element.attrib["name"])
            for edge in list(element.iter("parent")) + list(element.iter("child")):
                edge.set("link", prefix + edge.attrib["link"])
            for mesh in element.iter("mesh"):
                mesh.set("filename", str((ASSETS / mesh.attrib["filename"]).resolve()))
            root.append(element)
        parent = "world" if index == 0 else "left_base_link"
        mount = ET.SubElement(root, "joint", name=prefix + "mount", type="fixed")
        ET.SubElement(mount, "parent", link=parent)
        ET.SubElement(mount, "child", link=prefix + "base_link")
        ET.SubElement(
            mount,
            "origin",
            xyz=" ".join(map(str, poses[index][:3])),
            rpy=" ".join(map(str, poses[index][3:])),
        )
        names.extend(prefix + j for j in JOINTS)
        disabled.extend((prefix + a, prefix + b) for a, b in base_pairs)
        disabled.append((prefix + "base_link", "__floor__"))
    left = transform(left_base)
    bases = [left[:3, 3]]
    if dual:
        bases.append((left @ transform(right_relative))[:3, 3])
    bases = np.array(bases)
    bounds = [
        float(bases[:, 0].min() - margins[0]),
        float(bases[:, 0].max() + margins[1]),
        float(bases[:, 1].min() - margins[2]),
        float(bases[:, 1].max() + margins[3]),
    ]
    floor_z = float(bases[:, 2].min()) if floor_z is None else float(floor_z)
    if not np.isfinite(floor_z):
        raise ValueError("floor_z must be finite")
    path = Path(output) if output else Path(tempfile.mkdtemp(prefix="iimt-model-")) / "robot.urdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return Scene(
        str(path.resolve()), names, disabled_collisions=disabled, workspace=bounds, floor_z=floor_z
    )
