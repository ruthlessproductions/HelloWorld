"""World model: spatial reasoning and physics constraints using only stdlib math.

Enforces ground plane constraints, resolves bounding-box collisions,
and optimizes camera framing. Uses Blender's Z-up convention.
"""

from __future__ import annotations

import math


def process(scene: dict) -> dict:
    objects = scene.get("objects", [])

    _enforce_ground(objects, scene.get("ground_plane", True))
    _resolve_collisions(objects)
    scene["camera"] = _optimize_camera(scene.get("camera", {}), objects)

    scene["objects"] = objects
    return scene


def _bbox(obj: dict) -> tuple[list[float], list[float]]:
    pos = obj.get("position", [0, 0, 0])
    scale = obj.get("scale", [1, 1, 1])
    prim = obj.get("primitive", "cube")

    half = _half_extents(prim, scale)
    return (
        [pos[i] - half[i] for i in range(3)],
        [pos[i] + half[i] for i in range(3)],
    )


def _half_extents(primitive: str, scale: list[float]) -> list[float]:
    sx, sy, sz = scale[0], scale[1], scale[2]

    if primitive == "cube":
        return [sx / 2, sy / 2, sz / 2]
    elif primitive == "sphere":
        r = max(sx, sy, sz) / 2
        return [r, r, r]
    elif primitive == "cylinder":
        r = max(sx, sy) / 2
        return [r, r, sz / 2]
    elif primitive == "cone":
        r = max(sx, sy) / 2
        return [r, r, sz / 2]
    elif primitive == "plane":
        return [sx / 2, sy / 2, 0.01]
    elif primitive == "torus":
        outer = max(sx, sy) / 2
        return [outer, outer, sz / 4]
    return [sx / 2, sy / 2, sz / 2]


def _enforce_ground(objects: list[dict], has_ground: bool):
    if not has_ground:
        return
    for obj in objects:
        bb_min, _ = _bbox(obj)
        if bb_min[2] < 0:
            obj["position"][2] += -bb_min[2]


def _intersects(a_min, a_max, b_min, b_max) -> bool:
    return all(a_min[i] <= b_max[i] and a_max[i] >= b_min[i] for i in range(3))


def _resolve_collisions(objects: list[dict]):
    for _ in range(50):
        resolved = True
        for i in range(len(objects)):
            a_min, a_max = _bbox(objects[i])
            for j in range(i + 1, len(objects)):
                b_min, b_max = _bbox(objects[j])
                if _intersects(a_min, a_max, b_min, b_max):
                    _separate(objects[i], objects[j], a_min, a_max, b_min, b_max)
                    resolved = False
        if resolved:
            return


def _separate(a: dict, b: dict, a_min, a_max, b_min, b_max):
    a_center = [(a_min[i] + a_max[i]) / 2 for i in range(3)]
    b_center = [(b_min[i] + b_max[i]) / 2 for i in range(3)]
    a_half = [(a_max[i] - a_min[i]) / 2 for i in range(3)]
    b_half = [(b_max[i] - b_min[i]) / 2 for i in range(3)]

    delta = [b_center[i] - a_center[i] for i in range(3)]
    overlap = [a_half[i] + b_half[i] - abs(delta[i]) for i in range(3)]

    best_axis = None
    best_overlap = float("inf")
    for i in range(3):
        if 0 < overlap[i] < best_overlap:
            best_overlap = overlap[i]
            best_axis = i

    if best_axis is None:
        return

    shift = best_overlap / 2 + 0.05
    direction = 1.0 if delta[best_axis] >= 0 else -1.0

    a["position"][best_axis] -= direction * shift
    b["position"][best_axis] += direction * shift


def _optimize_camera(camera: dict, objects: list[dict]) -> dict:
    if not objects:
        return camera

    all_min = [float("inf")] * 3
    all_max = [float("-inf")] * 3
    for obj in objects:
        bb_min, bb_max = _bbox(obj)
        for i in range(3):
            all_min[i] = min(all_min[i], bb_min[i])
            all_max[i] = max(all_max[i], bb_max[i])

    center = [(all_min[i] + all_max[i]) / 2 for i in range(3)]
    size = [all_max[i] - all_min[i] for i in range(3)]
    max_dim = max(size)

    fov = camera.get("fov", 50)
    fov_rad = math.radians(fov / 2)
    distance = max(max_dim * 2.0, max_dim / (2 * math.tan(fov_rad)) if fov_rad > 0 else max_dim * 2)
    distance *= 1.3

    if "position" not in camera or camera["position"] == [0, 0, 0]:
        camera["position"] = [
            center[0] + distance * 0.7,
            center[1] - distance * 0.7,
            center[2] + distance * 0.4,
        ]

    if "target" not in camera or camera["target"] == [0, 0, 0]:
        camera["target"] = center

    return camera
