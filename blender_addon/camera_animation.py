"""Camera animation: generates keyframed camera paths from motion presets or LLM descriptions.

Supports turntable, dolly, crane, push-in, pull-out, orbit-rise, fly-through,
and dynamic loop with speed ramping. All animations use Bezier interpolation
and create a camera rig (camera + tracking target) with native Blender keyframes.
"""

from __future__ import annotations

import json
import math
from enum import Enum
from typing import Optional

import bpy
import mathutils


class MotionType(Enum):
    TURNTABLE = "turntable"
    DOLLY_ZOOM = "dolly_zoom"
    CRANE = "crane"
    ORBIT_RISE = "orbit_rise"
    PUSH_IN = "push_in"
    PULL_OUT = "pull_out"
    FLY_THROUGH = "fly_through"
    DYNAMIC_LOOP = "dynamic_loop"


CAMERA_PARSE_SYSTEM = """You are a camera motion designer for 3D scenes. Given a description of a camera move, output a JSON specification.

Return ONLY valid JSON with this structure:
{
  "motion_type": "turntable|dolly_zoom|crane|orbit_rise|push_in|pull_out|fly_through|dynamic_loop",
  "duration": 5.0,
  "fps": 24,
  "target": [x, y, z],
  "start_distance": 8.0,
  "end_distance": 8.0,
  "start_height": 3.0,
  "end_height": 3.0,
  "start_angle": 0,
  "end_angle": 360,
  "fov_start": 50,
  "fov_end": 50,
  "ease_in": true,
  "ease_out": true,
  "speed_ramp": false
}

Rules:
- Z-axis is up (Blender convention).
- Angles are in degrees.
- distance is camera distance from target in meters.
- For turntable: start_angle=0, end_angle=360 for full orbit.
- For dolly_zoom: change both distance and fov to create vertigo effect.
- For crane: change start_height to end_height (low to high = reveal).
- For push_in: start_distance > end_distance.
- For pull_out: start_distance < end_distance.
- For orbit_rise: orbit + increasing height.
- For dynamic_loop: speed_ramp=true, full 360 with slow reveals on faces.
- Default duration is 5 seconds, fps 24.
"""


def animate_camera(
    motion_type: str,
    duration: float = 5.0,
    fps: int = 24,
    target: tuple[float, float, float] = (0, 0, 1.5),
    start_distance: float = 8.0,
    end_distance: float = 8.0,
    start_height: float = 3.0,
    end_height: float = 3.0,
    start_angle: float = 0,
    end_angle: float = 360,
    fov_start: float = 50,
    fov_end: float = 50,
    ease_in: bool = True,
    ease_out: bool = True,
    speed_ramp: bool = False,
):
    _cleanup_camera_rig()

    total_frames = int(duration * fps)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = total_frames
    scene.render.fps = fps

    tgt_obj = bpy.data.objects.new("CamTarget", None)
    tgt_obj.empty_display_type = "PLAIN_AXES"
    tgt_obj.empty_display_size = 0.3
    tgt_obj.location = mathutils.Vector(target)
    bpy.context.collection.objects.link(tgt_obj)

    cam_data = bpy.data.cameras.new(name="AnimCamera")
    cam_data.lens_unit = "FOV"
    cam_data.angle = math.radians(fov_start)
    cam_data.clip_end = 500

    cam_obj = bpy.data.objects.new("AnimCamera", cam_data)
    bpy.context.collection.objects.link(cam_obj)

    constraint = cam_obj.constraints.new(type="TRACK_TO")
    constraint.target = tgt_obj
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"

    scene.camera = cam_obj

    motion = motion_type.lower().replace(" ", "_").replace("-", "_")

    if motion == "turntable":
        _animate_turntable(cam_obj, tgt_obj, total_frames, target,
                          start_distance, start_height, start_angle, end_angle)
    elif motion == "dolly_zoom":
        _animate_dolly_zoom(cam_obj, cam_data, tgt_obj, total_frames, target,
                           start_distance, end_distance, start_height,
                           fov_start, fov_end, start_angle)
    elif motion == "crane":
        _animate_crane(cam_obj, tgt_obj, total_frames, target,
                      start_distance, start_height, end_height, start_angle)
    elif motion == "orbit_rise":
        _animate_orbit_rise(cam_obj, tgt_obj, total_frames, target,
                           start_distance, start_height, end_height,
                           start_angle, end_angle)
    elif motion == "push_in":
        _animate_push(cam_obj, tgt_obj, total_frames, target,
                     start_distance, end_distance, start_height, start_angle)
    elif motion == "pull_out":
        _animate_push(cam_obj, tgt_obj, total_frames, target,
                     start_distance, end_distance, start_height, start_angle)
    elif motion == "fly_through":
        _animate_fly_through(cam_obj, tgt_obj, total_frames, target,
                            start_distance, end_distance, start_height, end_height)
    elif motion == "dynamic_loop":
        _animate_dynamic_loop(cam_obj, tgt_obj, total_frames, target,
                             start_distance, start_height)
    else:
        _animate_turntable(cam_obj, tgt_obj, total_frames, target,
                          start_distance, start_height, start_angle, end_angle)

    _set_interpolation(cam_obj, ease_in, ease_out)
    if tgt_obj.animation_data and tgt_obj.animation_data.action:
        _set_interpolation(tgt_obj, ease_in, ease_out)

    if fov_start != fov_end and motion != "dolly_zoom":
        _animate_fov(cam_data, total_frames, fov_start, fov_end)

    scene.frame_set(1)

    return cam_obj, tgt_obj


def animate_from_prompt(
    prompt: str,
    provider: str = "claude",
    api_key: str = None,
    model: str = None,
    workspace_id: str = None,
):
    from . import llm_client

    client = llm_client.LLMClient(
        provider=provider, api_key=api_key, model=model, workspace_id=workspace_id,
    )
    text = client.chat(prompt, system=CAMERA_PARSE_SYSTEM)
    text = llm_client._extract_json(text)
    spec = json.loads(text)

    return animate_camera(
        motion_type=spec.get("motion_type", "turntable"),
        duration=spec.get("duration", 5.0),
        fps=spec.get("fps", 24),
        target=tuple(spec.get("target", [0, 0, 1.5])),
        start_distance=spec.get("start_distance", 8.0),
        end_distance=spec.get("end_distance", 8.0),
        start_height=spec.get("start_height", 3.0),
        end_height=spec.get("end_height", 3.0),
        start_angle=spec.get("start_angle", 0),
        end_angle=spec.get("end_angle", 360),
        fov_start=spec.get("fov_start", 50),
        fov_end=spec.get("fov_end", 50),
        ease_in=spec.get("ease_in", True),
        ease_out=spec.get("ease_out", True),
        speed_ramp=spec.get("speed_ramp", False),
    )


def _cleanup_camera_rig():
    for name in ("AnimCamera", "CamTarget"):
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
    cam = bpy.data.cameras.get("AnimCamera")
    if cam:
        bpy.data.cameras.remove(cam)


def _cam_pos(target, distance, height, angle_deg):
    angle = math.radians(angle_deg)
    x = target[0] + distance * math.cos(angle)
    y = target[1] + distance * math.sin(angle)
    z = target[2] + height
    return (x, y, z)


def _animate_turntable(cam, tgt, frames, target, distance, height, start_deg, end_deg):
    for f in range(1, frames + 1):
        t = (f - 1) / max(frames - 1, 1)
        angle = start_deg + t * (end_deg - start_deg)
        cam.location = _cam_pos(target, distance, height, angle)
        cam.keyframe_insert(data_path="location", frame=f)


def _animate_dolly_zoom(cam, cam_data, tgt, frames, target,
                        dist_start, dist_end, height, fov_start, fov_end, angle):
    for f in range(1, frames + 1):
        t = (f - 1) / max(frames - 1, 1)
        dist = dist_start + t * (dist_end - dist_start)
        fov = fov_start + t * (fov_end - fov_start)
        cam.location = _cam_pos(target, dist, height, angle)
        cam.keyframe_insert(data_path="location", frame=f)
        cam_data.angle = math.radians(fov)
        cam_data.keyframe_insert(data_path="lens", frame=f)


def _animate_crane(cam, tgt, frames, target, distance, h_start, h_end, angle):
    for f in range(1, frames + 1):
        t = (f - 1) / max(frames - 1, 1)
        height = h_start + t * (h_end - h_start)
        cam.location = _cam_pos(target, distance, height, angle)
        cam.keyframe_insert(data_path="location", frame=f)
        tgt_h = target[2] + t * (h_end - h_start) * 0.3
        tgt.location.z = tgt_h
        tgt.keyframe_insert(data_path="location", index=2, frame=f)


def _animate_orbit_rise(cam, tgt, frames, target, distance,
                        h_start, h_end, start_deg, end_deg):
    for f in range(1, frames + 1):
        t = (f - 1) / max(frames - 1, 1)
        angle = start_deg + t * (end_deg - start_deg)
        height = h_start + t * (h_end - h_start)
        cam.location = _cam_pos(target, distance, height, angle)
        cam.keyframe_insert(data_path="location", frame=f)


def _animate_push(cam, tgt, frames, target, dist_start, dist_end, height, angle):
    for f in range(1, frames + 1):
        t = (f - 1) / max(frames - 1, 1)
        dist = dist_start + t * (dist_end - dist_start)
        cam.location = _cam_pos(target, dist, height, angle)
        cam.keyframe_insert(data_path="location", frame=f)


def _animate_fly_through(cam, tgt, frames, target, dist_start, dist_end,
                         h_start, h_end):
    start_pos = mathutils.Vector((
        target[0] + dist_start,
        target[1] - dist_start * 0.5,
        target[2] + h_start,
    ))
    end_pos = mathutils.Vector((
        target[0] - dist_end * 0.3,
        target[1] + dist_end * 0.5,
        target[2] + h_end,
    ))
    mid_pos = mathutils.Vector((
        target[0],
        target[1],
        target[2] + max(h_start, h_end) * 1.2,
    ))

    for f in range(1, frames + 1):
        t = (f - 1) / max(frames - 1, 1)
        p1 = start_pos.lerp(mid_pos, t)
        p2 = mid_pos.lerp(end_pos, t)
        pos = p1.lerp(p2, t)
        cam.location = pos
        cam.keyframe_insert(data_path="location", frame=f)


def _animate_dynamic_loop(cam, tgt, frames, target, distance, height):
    kf_angle = [
        (0.000, 0),
        (0.125, 10),
        (0.188, 90),
        (0.312, 100),
        (0.375, 180),
        (0.500, 190),
        (0.562, 270),
        (0.688, 280),
        (0.750, 330),
        (0.875, 340),
        (0.938, 355),
        (1.000, 360),
    ]

    kf_height_offset = [
        (0.000, 0),
        (0.125, 0),
        (0.312, 0.5),
        (0.500, 0),
        (0.562, -0.8),
        (0.688, -1.5),
        (0.750, -2.5),
        (0.875, -1.0),
        (1.000, 0),
    ]

    for t_norm, angle_deg in kf_angle:
        f = max(1, int(t_norm * frames) + 1)
        h_offset = 0
        for i in range(len(kf_height_offset) - 1):
            t0, h0 = kf_height_offset[i]
            t1, h1 = kf_height_offset[i + 1]
            if t0 <= t_norm <= t1:
                local_t = (t_norm - t0) / (t1 - t0) if t1 > t0 else 0
                h_offset = h0 + local_t * (h1 - h0)
                break

        cam.location = _cam_pos(target, distance, height + h_offset, angle_deg)
        cam.keyframe_insert(data_path="location", frame=f)

    for fcurve in fcurves_of(cam):
        for kp in fcurve.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = "AUTO"
            kp.handle_right_type = "AUTO"


def fcurves_of(id_data) -> list:
    """F-curves of an ID's active action. Blender 5 removed Action.fcurves in favor of slotted channelbags."""
    anim = id_data.animation_data
    if not anim or not anim.action:
        return []
    if hasattr(anim.action, "fcurves"):
        return list(anim.action.fcurves)
    from bpy_extras import anim_utils
    bag = anim_utils.action_get_channelbag_for_slot(anim.action, anim.action_slot)
    return list(bag.fcurves) if bag else []


def _animate_fov(cam_data, frames, fov_start, fov_end):
    # "angle" is derived from lens and can't be keyframed; setting it updates lens.
    cam_data.angle = math.radians(fov_start)
    cam_data.keyframe_insert(data_path="lens", frame=1)
    cam_data.angle = math.radians(fov_end)
    cam_data.keyframe_insert(data_path="lens", frame=frames)


def _set_interpolation(obj, ease_in: bool, ease_out: bool):
    for fcurve in fcurves_of(obj):
        for kp in fcurve.keyframe_points:
            kp.interpolation = "BEZIER"
            if ease_in and ease_out:
                kp.handle_left_type = "AUTO_CLAMPED"
                kp.handle_right_type = "AUTO_CLAMPED"
            elif ease_in:
                kp.handle_left_type = "AUTO_CLAMPED"
                kp.handle_right_type = "VECTOR"
            elif ease_out:
                kp.handle_left_type = "VECTOR"
                kp.handle_right_type = "AUTO_CLAMPED"


MOTION_PRESETS = {
    "turntable": {
        "motion_type": "turntable", "duration": 5.0, "start_angle": 0, "end_angle": 360,
        "start_distance": 8.0, "start_height": 3.0,
    },
    "slow_zoom": {
        "motion_type": "push_in", "duration": 4.0, "start_distance": 10.0,
        "end_distance": 4.0, "start_height": 2.0, "start_angle": -30,
    },
    "dramatic_reveal": {
        "motion_type": "crane", "duration": 6.0, "start_distance": 8.0,
        "start_height": -1.0, "end_height": 6.0, "start_angle": 45,
    },
    "orbit_rise": {
        "motion_type": "orbit_rise", "duration": 6.0, "start_angle": 0, "end_angle": 270,
        "start_distance": 8.0, "start_height": 1.0, "end_height": 6.0,
    },
    "vertigo": {
        "motion_type": "dolly_zoom", "duration": 4.0, "start_distance": 12.0,
        "end_distance": 4.0, "fov_start": 25, "fov_end": 80,
        "start_height": 2.0, "start_angle": 0,
    },
    "showcase_loop": {
        "motion_type": "dynamic_loop", "duration": 10.0, "start_distance": 8.0,
        "start_height": 3.0, "speed_ramp": True,
    },
    "fly_over": {
        "motion_type": "fly_through", "duration": 6.0, "start_distance": 12.0,
        "end_distance": 6.0, "start_height": 1.0, "end_height": 8.0,
    },
    "pull_back": {
        "motion_type": "pull_out", "duration": 4.0, "start_distance": 3.0,
        "end_distance": 12.0, "start_height": 2.0, "start_angle": 0,
    },
}


def animate_preset(preset_name: str, target: tuple[float, float, float] = (0, 0, 1.5),
                   fps: int = 24):
    preset = MOTION_PRESETS.get(preset_name)
    if not preset:
        raise ValueError(f"Unknown preset: {preset_name}. Available: {list(MOTION_PRESETS.keys())}")

    params = {**preset, "target": target, "fps": fps}
    return animate_camera(**params)
