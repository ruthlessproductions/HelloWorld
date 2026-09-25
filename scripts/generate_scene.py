#!/usr/bin/env python3
"""MCP-compatible script: generates a scene and sends Blender Python to execute via blender-mcp.

Usage:
    python scripts/generate_scene.py --prompt "a castle on a hill" --port 9876
    python scripts/generate_scene.py --scene scene.json --port 9876
    python scripts/generate_scene.py --test --port 9876
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render3d.llm.scene_parser import SceneParser
from render3d.world_model.scene_graph import SceneGraph
from render3d.schema import Scene


def scene_to_blender_code(scene_data: dict) -> str:
    lines = [
        "import bpy, math, mathutils",
        "",
        "# Clear scene",
        "bpy.ops.object.select_all(action='SELECT')",
        "bpy.ops.object.delete(use_global=False)",
        "",
    ]

    for obj in scene_data.get("objects", []):
        lines.extend(_object_code(obj))
        lines.append("")

    if scene_data.get("ground_plane", True):
        lines.extend([
            "# Ground plane",
            "bpy.ops.mesh.primitive_plane_add(size=50, location=(0, 0, 0))",
            "ground = bpy.context.active_object",
            "ground.name = 'Ground'",
            "mat = bpy.data.materials.new(name='M_Ground')",
            "mat.use_nodes = True",
            "bsdf = mat.node_tree.nodes.get('Principled BSDF')",
            "if bsdf:",
            "    bsdf.inputs['Base Color'].default_value = (0.35, 0.35, 0.33, 1.0)",
            "    bsdf.inputs['Roughness'].default_value = 0.9",
            "ground.data.materials.append(mat)",
            "",
        ])

    for light in scene_data.get("lights", []):
        lines.extend(_light_code(light))
        lines.append("")

    cam = scene_data.get("camera", {})
    pos = cam.get("position", [8, -6, 5])
    target = cam.get("target", [0, 0, 2])
    fov = cam.get("fov", 50)
    lines.extend([
        "# Camera",
        f"cam_data = bpy.data.cameras.new(name='SceneCamera')",
        f"cam_data.lens_unit = 'FOV'",
        f"cam_data.angle = math.radians({fov})",
        f"cam_obj = bpy.data.objects.new(name='SceneCamera', object_data=cam_data)",
        f"bpy.context.collection.objects.link(cam_obj)",
        f"cam_obj.location = mathutils.Vector({pos})",
        f"direction = mathutils.Vector({target}) - cam_obj.location",
        f"rot = direction.to_track_quat('-Z', 'Y')",
        f"cam_obj.rotation_euler = rot.to_euler()",
        f"bpy.context.scene.camera = cam_obj",
        "",
        "# Render settings",
        "bpy.context.scene.render.resolution_x = 1920",
        "bpy.context.scene.render.resolution_y = 1080",
    ])

    return "\n".join(lines)


def _object_code(obj: dict) -> list[str]:
    name = obj.get("name", "Object")
    prim = obj.get("primitive", "cube")
    pos = obj.get("position", [0, 0, 0])
    rot = obj.get("rotation", [0, 0, 0])
    scale = obj.get("scale", [1, 1, 1])
    mat = obj.get("material", {})
    color = mat.get("color", [0.8, 0.8, 0.8])
    roughness = mat.get("roughness", 0.5)
    metallic = mat.get("metallic", 0.0)

    lines = [f"# Object: {name}"]

    if prim == "cube":
        lines.append("bpy.ops.mesh.primitive_cube_add(size=1)")
        lines.append(f"bpy.context.active_object.scale = ({scale[0]}, {scale[1]}, {scale[2]})")
    elif prim == "sphere":
        r = max(scale) / 2
        lines.append(f"bpy.ops.mesh.primitive_uv_sphere_add(radius={r}, segments=48, ring_count=24)")
    elif prim == "cylinder":
        r = max(scale[0], scale[1]) / 2
        lines.append(f"bpy.ops.mesh.primitive_cylinder_add(radius={r}, depth={scale[2]}, vertices=48)")
    elif prim == "cone":
        r = max(scale[0], scale[1]) / 2
        lines.append(f"bpy.ops.mesh.primitive_cone_add(radius1={r}, depth={scale[2]}, vertices=48)")
    elif prim == "plane":
        lines.append("bpy.ops.mesh.primitive_plane_add(size=1)")
        lines.append(f"bpy.context.active_object.scale = ({scale[0]}, {scale[1]}, 1)")
    elif prim == "torus":
        major = max(scale[0], scale[1]) / 2
        minor = scale[2] / 4
        lines.append(f"bpy.ops.mesh.primitive_torus_add(major_radius={major}, minor_radius={minor})")
    else:
        lines.append("bpy.ops.mesh.primitive_cube_add(size=1)")

    lines.extend([
        f"obj = bpy.context.active_object",
        f"obj.name = '{name}'",
        f"obj.location = ({pos[0]}, {pos[1]}, {pos[2]})",
        f"obj.rotation_euler = (math.radians({rot[0]}), math.radians({rot[1]}), math.radians({rot[2]}))",
        f"bpy.ops.object.shade_smooth()",
        f"",
        f"mat = bpy.data.materials.new(name='M_{name}')",
        f"mat.use_nodes = True",
        f"nodes = mat.node_tree.nodes",
        f"bsdf = nodes.get('Principled BSDF')",
        f"if bsdf:",
        f"    bsdf.inputs['Base Color'].default_value = ({color[0]}, {color[1]}, {color[2]}, 1.0)",
        f"    bsdf.inputs['Roughness'].default_value = {roughness}",
        f"    bsdf.inputs['Metallic'].default_value = {metallic}",
        f"obj.data.materials.append(mat)",
    ])

    return lines


def _light_code(light: dict) -> list[str]:
    lt = light.get("type", "POINT")
    pos = light.get("position", [5, 5, 8])
    color = light.get("color", [1, 1, 1])
    intensity = light.get("intensity", 1.0)
    name = f"Light_{lt}"

    lines = [
        f"# Light: {lt}",
        f"light = bpy.data.lights.new(name='{name}', type='{lt}')",
        f"light.color = ({color[0]}, {color[1]}, {color[2]})",
        f"light.energy = {intensity}",
        f"light_obj = bpy.data.objects.new(name='{name}', object_data=light)",
        f"bpy.context.collection.objects.link(light_obj)",
        f"light_obj.location = ({pos[0]}, {pos[1]}, {pos[2]})",
    ]

    direction = light.get("direction")
    if direction and lt == "SUN":
        lines.extend([
            f"dir_vec = mathutils.Vector(({direction[0]}, {direction[1]}, {direction[2]})).normalized()",
            f"rot_q = dir_vec.to_track_quat('-Z', 'Y')",
            f"light_obj.rotation_euler = rot_q.to_euler()",
        ])

    return lines


def send_to_blender(code: str, port: int = 9876):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(("localhost", port))

        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "execute_code",
            "params": {"code": code},
            "id": 1,
        })

        sock.sendall(payload.encode("utf-8"))

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        sock.close()
        result = json.loads(response.decode("utf-8"))
        return result

    except ConnectionRefusedError:
        print(f"Could not connect to Blender on port {port}.")
        print("Make sure Blender is running with the MCP addon active.")
        return None
    except Exception as e:
        print(f"Error communicating with Blender: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Generate 3D scenes and send to Blender")
    parser.add_argument("--prompt", help="Scene description for LLM parsing")
    parser.add_argument("--scene", help="Path to a scene JSON file")
    parser.add_argument("--test", action="store_true", help="Generate a test scene (no LLM)")
    parser.add_argument("--port", type=int, default=9876, help="Blender MCP port (default: 9876)")
    parser.add_argument("--output", help="Save generated Python code to file instead of sending")
    parser.add_argument("--print-code", action="store_true", help="Print generated code to stdout")
    args = parser.parse_args()

    if args.test:
        scene_data = {
            "name": "test",
            "objects": [
                {"name": "tower", "primitive": "cylinder", "position": [0, 0, 2.5],
                 "scale": [1.5, 1.5, 5], "material": {"color": [0.55, 0.55, 0.5], "roughness": 0.85}},
                {"name": "roof", "primitive": "cone", "position": [0, 0, 6],
                 "scale": [2, 2, 2.5], "material": {"color": [0.45, 0.15, 0.1], "roughness": 0.7}},
            ],
            "lights": [{"type": "SUN", "direction": [0.5, 0.3, -1], "intensity": 3.0}],
            "camera": {"position": [8, -6, 5], "target": [0, 0, 3], "fov": 50},
            "ground_plane": True,
        }
    elif args.scene:
        with open(args.scene) as f:
            scene_data = json.load(f)
    elif args.prompt:
        print(f"Parsing scene: {args.prompt}")
        llm_parser = SceneParser()
        scene = llm_parser.parse(args.prompt)
        graph = SceneGraph()
        scene = graph.build(scene)

        from dataclasses import asdict
        scene_data = asdict(scene)
        for obj in scene_data.get("objects", []):
            _convert_enums(obj)
    else:
        parser.print_help()
        sys.exit(1)

    code = scene_to_blender_code(scene_data)

    if args.print_code:
        print(code)
        return

    if args.output:
        Path(args.output).write_text(code)
        print(f"Saved Blender script to {args.output}")
        return

    print(f"Sending to Blender on port {args.port}...")
    result = send_to_blender(code, args.port)
    if result:
        print("Scene generated in Blender!")
    else:
        print("\nAlternatively, save the script and run it in Blender:")
        print(f"  python {__file__} --prompt '...' --output scene_script.py")
        print("  Then in Blender: Scripting tab → Open → Run Script")


def _convert_enums(obj):
    if "primitive" in obj and hasattr(obj["primitive"], "value"):
        obj["primitive"] = obj["primitive"].value
    for child in obj.get("children", []):
        _convert_enums(child)


if __name__ == "__main__":
    main()
