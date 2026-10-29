"""Serializable CI-05 configuration. Distances in metres, joint angles in radians."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

JOINTS = (
    "shoulder_joint",
    "upper_arm_joint",
    "forearm_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)
ASSETS = Path(__file__).parent / "assets"


def sdk_path() -> str:
    name = "iimtcl.dll" if sys.platform == "win32" else "libiimtcl.so"
    installed = Path(__file__).parent / "vendor" / name
    if installed.exists():
        return str(installed)
    # Editable/source builds only. Wheels always use the packaged platform library.
    return str(
        Path(__file__).resolve().parents[2]
        / "vendor"
        / ("windows" if sys.platform == "win32" else "linux")
        / name
    )


@dataclass
class Arm:
    name: str
    ip: str
    port: int = 29999
    joint_names: list[str] = field(default_factory=lambda: list(JOINTS))
    sdk_library: str = field(default_factory=sdk_path)
    command_rate: float = 125.0
    read_rate: float = 125.0
    read_timeout: float = 0.1
    state_timeout: float = 0.2
    enable_motion: bool = False
    allow_protective_stop_release: bool = False
    startup_timeout: float = 5.0
    clock_jump_tolerance: float = 0.1
    windows_timer_resolution_ms: int = 1
    servo_a: float = 5.0
    servo_v: float = 3.0
    lookahead_time: float = 0.012
    gain: float = 0.0
    advance_ms: float = 0.0
    start_tolerance: float = 0.02
    path_tolerance: float = 3.0
    goal_tolerance: float = 0.003
    goal_time_tolerance: float = 2.0
    jitter_warning: float = 0.004
    min_position: list[float] = field(
        default_factory=lambda: [-6.2832, -2.6167, -2.8783, -3.0528, -3.0528, -6.2832]
    )
    max_position: list[float] = field(
        default_factory=lambda: [6.2832, 2.6167, 2.8783, 3.0528, 3.0528, 6.2832]
    )
    max_velocity: list[float] = field(default_factory=lambda: [3.1415] * 6)
    max_acceleration: list[float] = field(
        default_factory=lambda: [1.875, 2.5, 3.75, 3.125, 3.75, 3.75]
    )
    max_step: list[float] = field(default_factory=lambda: [0.02] * 6)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Scene:
    urdf: str
    joint_names: list[str]
    package_paths: dict[str, str] = field(default_factory=dict)
    disabled_collisions: list[tuple[str, str]] = field(default_factory=list)
    workspace: list[float] | None = None  # xmin, xmax, ymin, ymax in world
    floor_z: float | None = None
    collision_resolution: float = 0.02  # maximum joint-space checking step, rad

    def to_dict(self) -> dict:
        return asdict(self)

    def model(self):
        from ._model import Model

        return Model(
            self.urdf,
            self.joint_names,
            self.package_paths,
            self.disabled_collisions,
            self.floor_z,
            self.workspace,
        )
