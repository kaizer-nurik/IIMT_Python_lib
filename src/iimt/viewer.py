"""Separate GUI process. Target changes are never implicitly executed."""

import time
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor

from .config import Scene
from .robot import rpc
from .trajectory import Trajectory


def _execute_plan(address, key, plan):
    ticket = rpc(address, key, "prepare", plan, timeout=120)
    try:
        return rpc(address, key, "execute_prepared", ticket, time.time_ns() + 3_000_000_000)
    except (TimeoutError, EOFError, OSError):
        try:
            rpc(address, key, "cancel", None, timeout=2)
        except Exception as error:
            warnings.warn(
                f"Cancellation failed: {error}; physical stop is NOT confirmed", RuntimeWarning
            )
        raise


def run_viewer(address, key, scene_data, ready):
    viewer = None
    try:
        from ._viewer import Viewer

        scene = Scene(**scene_data)
        model = scene.model()
        viewer = Viewer("IIMT — measured / target / plan")
        geometry = model.geometry_local()
        measured = [dict(mesh, link="actual:" + mesh["link"]) for mesh in geometry]
        target_mesh = [
            dict(mesh, link="target:" + mesh["link"], color=[0.2, 0.7, 1.0, 0.25])
            for mesh in geometry
        ]
        plan_mesh = [
            dict(mesh, link="plan:" + mesh["link"], color=[0.2, 1.0, 0.4, 0.2]) for mesh in geometry
        ]
        desired_mesh = [
            dict(mesh, link="desired:" + mesh["link"], color=[1.0, 0.7, 0.1, 0.2])
            for mesh in geometry
        ]
        viewer.set_geometry(measured + target_mesh + plan_mesh + desired_mesh)
        limits = model.limits()
        state = rpc(address, key, "get_state")
        q = [v for arm in state["arms"] for v in arm["positions"]]
        target = q.copy()
        plan = None
        preview = None
        pending = None
        pending_target = None
        pending_kind = None
        preview_start = 0.0
        status = "Target sliders do not move hardware"
        ready.send((True, None))
        ready.close()
        with ThreadPoolExecutor(max_workers=1) as work:
            while True:
                started = time.monotonic()
                if pending is not None and pending.done():
                    kind, future = pending_kind, pending
                    pending = None
                    try:
                        value = future.result()
                        if kind == "plan":
                            if pending_target == target:
                                plan = value
                                preview = Trajectory(**value)
                                preview_start = time.monotonic()
                                status = f"Plan ready: {len(plan['times'])} points, {plan['times'][-1]:.2f}s"
                            else:
                                status = "Old plan discarded: target changed while planning"
                        else:
                            status = f"{kind}: {value}"
                    except Exception as exc:
                        status = str(exc)
                try:
                    state = rpc(address, key, "get_state", timeout=1)
                    q = [v for arm in state["arms"] for v in arm["positions"]]
                except Exception as exc:
                    status = str(exc)
                transforms = {"actual:" + k: v for k, v in model.transforms(q).items()}
                transforms.update({"target:" + k: v for k, v in model.transforms(target).items()})
                shown_plan = (
                    preview.sample((time.monotonic() - preview_start) % max(0.1, preview.times[-1]))
                    if preview is not None
                    else target
                )
                transforms.update({"plan:" + k: v for k, v in model.transforms(shown_plan).items()})
                desired = [
                    v
                    for arm in state["arms"]
                    for v in (arm.get("desired_positions") or arm["positions"])
                ]
                transforms.update({"desired:" + k: v for k, v in model.transforms(desired).items()})
                event = viewer.update(
                    None,
                    target,
                    limits["lower"],
                    limits["upper"],
                    status,
                    scene.workspace,
                    scene.floor_z,
                    transforms,
                )
                if not event["open"]:
                    break
                if list(event["target"]) != target:
                    target = list(event["target"])
                    plan = None
                    preview = None
                    status = "Target changed: Plan required before Execute"
                action = event["action"]
                if action == "cancel":
                    # Cancellation must not queue behind a planner future.
                    try:
                        rpc(address, key, "cancel", None, timeout=2)
                        status = "Cancellation requested"
                    except Exception as exc:
                        status = str(exc)
                elif action == "plan" and pending is None:
                    pending_target = target.copy()
                    pending = work.submit(rpc, address, key, "plan", pending_target, 5.0, 0.2)
                    pending_kind = "plan"
                    status = "Planning RRTConnect…"
                elif action == "execute" and pending is None:
                    if plan is None:
                        status = "Plan first; no motion sent"
                    else:
                        pending = work.submit(_execute_plan, address, key, plan)
                        pending_kind = "execute"
                        plan = None
                        status = "Submitting explicit execution…"
                time.sleep(max(0, 1 / 30 - (time.monotonic() - started)))
    except Exception:
        try:
            ready.send((False, traceback.format_exc()))
        except (OSError, EOFError):
            pass
    finally:
        if viewer is not None:
            viewer.close()
