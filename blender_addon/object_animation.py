"""Object animation: generates keyframed object/bone animations from LLM descriptions.

Inspects the current scene for mesh objects and armatures, sends the
inventory to the LLM, and applies the returned keyframe specification.
Supports rigid-body transforms (location/rotation/scale) and bone poses
for articulated models.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import bpy
import mathutils


OBJECT_ANIM_SYSTEM = """You are a 3D animation director. Given a scene inventory and a motion description, output keyframe data as JSON.

You will receive a scene inventory listing every animatable object and, for armatures, their bone names. Use ONLY names from the inventory.

Return ONLY valid JSON with this structure:
{
  "duration": 5.0,
  "fps": 24,
  "tracks": [
    {
      "target": "object_name",
      "property": "location|rotation|scale",
      "keyframes": [
        {"frame": 1, "value": [x, y, z]},
        {"frame": 24, "value": [x, y, z]}
      ]
    },
    {
      "target": "armature_name",
      "bone": "bone_name",
      "property": "location|rotation|scale",
      "keyframes": [
        {"frame": 1, "value": [x, y, z]},
        {"frame": 48, "value": [x, y, z]}
      ]
    }
  ]
}

Rules:
- Z-axis is up (Blender convention).
- rotation values are in degrees (converted to radians internally).
- Bone rotations are relative to the bone's rest pose.
- location values for bones are offsets from rest position in bone-local space.
- scale values are multipliers (1.0 = no change).
- Use the object/bone names EXACTLY as listed in the inventory.
- Keep animations smooth — use enough keyframes for natural motion (every 6-12 frames for smooth arcs).
- For looping animations, make the last keyframe match the first.
- For articulated models, animate bones rather than the armature object itself.
- Frame 1 should capture the starting pose. Don't skip frame 1.
- Duration and fps define the timeline. Total frames = duration * fps.
"""


def _build_scene_inventory() -> str:
    lines = ["Scene Inventory:", ""]

    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            lines.append(
                f"  MESH: \"{obj.name}\"  pos={_fmt_vec(obj.location)}  "
                f"rot={_fmt_rot(obj.rotation_euler)}  scale={_fmt_vec(obj.scale)}"
            )
        elif obj.type == "ARMATURE":
            lines.append(f"  ARMATURE: \"{obj.name}\"")
            if obj.pose:
                for bone in obj.pose.bones:
                    lines.append(f"    BONE: \"{bone.name}\"")
        elif obj.type == "EMPTY":
            lines.append(f"  EMPTY: \"{obj.name}\"  pos={_fmt_vec(obj.location)}")

    if not any(line.strip().startswith(("MESH:", "ARMATURE:")) for line in lines):
        lines.append("  (no animatable objects found)")

    return "\n".join(lines)


def _fmt_vec(v) -> str:
    return f"[{v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f}]"


def _fmt_rot(euler) -> str:
    return f"[{math.degrees(euler.x):.1f}, {math.degrees(euler.y):.1f}, {math.degrees(euler.z):.1f}]"


def animate_objects(spec: dict):
    duration = spec.get("duration", 5.0)
    fps = spec.get("fps", 24)
    total_frames = int(duration * fps)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(scene.frame_end, total_frames)
    scene.render.fps = fps

    tracks = spec.get("tracks", [])
    animated_count = 0

    for track in tracks:
        target_name = track.get("target")
        bone_name = track.get("bone")
        prop = track.get("property", "location")
        keyframes = track.get("keyframes", [])

        obj = bpy.data.objects.get(target_name)
        if obj is None:
            continue

        if bone_name and obj.type == "ARMATURE" and obj.pose:
            bone = obj.pose.bones.get(bone_name)
            if bone is None:
                continue
            _apply_bone_keyframes(obj, bone, prop, keyframes)
        else:
            _apply_object_keyframes(obj, prop, keyframes)

        animated_count += 1

    _smooth_all_fcurves(scene)
    scene.frame_set(1)

    return animated_count


def _apply_object_keyframes(obj, prop: str, keyframes: list[dict]):
    data_path = prop
    for kf in keyframes:
        frame = kf["frame"]
        value = kf["value"]

        if prop == "location":
            obj.location = mathutils.Vector(value)
        elif prop == "rotation":
            obj.rotation_euler = mathutils.Euler(
                [math.radians(v) for v in value], "XYZ"
            )
            data_path = "rotation_euler"
        elif prop == "scale":
            obj.scale = mathutils.Vector(value)

        obj.keyframe_insert(data_path=data_path, frame=frame)


def _apply_bone_keyframes(armature_obj, bone, prop: str, keyframes: list[dict]):
    data_path_base = f'pose.bones["{bone.name}"]'

    for kf in keyframes:
        frame = kf["frame"]
        value = kf["value"]

        if prop == "location":
            bone.location = mathutils.Vector(value)
            data_path = f"{data_path_base}.location"
        elif prop == "rotation":
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = mathutils.Euler(
                [math.radians(v) for v in value], "XYZ"
            )
            data_path = f"{data_path_base}.rotation_euler"
        elif prop == "scale":
            bone.scale = mathutils.Vector(value)
            data_path = f"{data_path_base}.scale"
        else:
            continue

        armature_obj.keyframe_insert(data_path=data_path, frame=frame)


def _smooth_all_fcurves(scene):
    from .camera_animation import fcurves_of

    for obj in scene.objects:
        for fcurve in fcurves_of(obj):
            for kp in fcurve.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.handle_left_type = "AUTO_CLAMPED"
                kp.handle_right_type = "AUTO_CLAMPED"


def animate_from_prompt(
    prompt: str,
    provider: str = "claude",
    api_key: str = None,
    model: str = None,
    workspace_id: str = None,
):
    from . import llm_client

    inventory = _build_scene_inventory()
    full_prompt = f"{inventory}\n\nAnimation request: {prompt}"

    client = llm_client.LLMClient(
        provider=provider, api_key=api_key, model=model, workspace_id=workspace_id,
    )
    text = client.chat(full_prompt, system=OBJECT_ANIM_SYSTEM)
    text = llm_client._extract_json(text)
    spec = json.loads(text)

    return animate_objects(spec)
