"""Render quick preview images of a .blend from several angles, without modifying the file.

Usage:
  "$BLENDER" --background --factory-startup --python render_preview.py -- \
      --blend scene.blend --out previews/ [--views camera,front,right,three_quarter,top] \
      [--res 640] [--engine eevee|workbench|cycles] [--samples 16]

"camera" renders through the scene's own camera at the scene's aspect ratio; the other
views use temporary 4:3 cameras that frame the whole subject (large flat ground planes
are ignored for framing). --res is the image width.
Prints the path of each PNG written.
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}
# Viewpoints named like Blender's numpad views: "front" looks from -Y toward +Y.
VIEW_DIRECTIONS = {
    "front": (0.0, -1.0, 0.25),
    "back": (0.0, 1.0, 0.25),
    "right": (1.0, 0.0, 0.25),
    "left": (-1.0, 0.0, 0.25),
    "three_quarter": (1.0, -1.0, 0.6),
    "top": (0.0, -0.001, 1.0),
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--views", default="camera,front,right,three_quarter")
    parser.add_argument("--res", type=int, default=640, help="width in pixels; height is 3/4 of it")
    parser.add_argument("--engine", default="eevee", choices=["eevee", "workbench", "cycles"])
    parser.add_argument("--samples", type=int, default=16)
    return parser.parse_args(argv)


def engine_id(name):
    available = {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    if name == "eevee":
        return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in available else "BLENDER_EEVEE"
    return {"workbench": "BLENDER_WORKBENCH", "cycles": "CYCLES"}[name]


def world_points(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    if obj.type != "MESH":
        # Blender 5.0 reports evaluated curve bounds merged with a unit cube; measure the real geometry.
        mesh = evaluated.to_mesh()
        try:
            if mesh is not None and len(mesh.vertices):
                return [evaluated.matrix_world @ v.co for v in mesh.vertices]
        finally:
            evaluated.to_mesh_clear()
    return [evaluated.matrix_world @ Vector(c) for c in evaluated.bound_box]


def subject_bounds(scene):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in scene.objects:
        if obj.type not in GEOMETRY_TYPES or not obj.visible_get():
            continue
        corners = world_points(obj, depsgraph)
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        zs = [c.z for c in corners]
        is_ground = (max(xs) - min(xs) > 20 or max(ys) - min(ys) > 20) and max(zs) - min(zs) < 0.2
        if not is_ground:
            points.extend(corners)
    if not points:
        return Vector((0, 0, 1)), 2.0
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return (lo + hi) / 2, max((hi - lo).length / 2, 0.1)


def framing_camera(scene, center, radius, direction):
    data = bpy.data.cameras.new("PreviewCam")
    data.lens_unit = "FOV"
    data.angle = math.radians(40)
    data.clip_start = max(radius / 1000, 0.001)
    data.clip_end = radius * 100
    cam = bpy.data.objects.new("PreviewCam", data)
    scene.collection.objects.link(cam)
    distance = radius / math.sin(data.angle / 2) * 1.05
    d = Vector(direction).normalized()
    cam.location = center + d * distance
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    return cam


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=args.blend)
    scene = bpy.context.scene
    os.makedirs(args.out, exist_ok=True)

    render = scene.render
    camera_aspect = render.resolution_y / render.resolution_x
    render.engine = engine_id(args.engine)
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    if args.engine == "eevee":
        scene.eevee.taa_render_samples = args.samples
    elif args.engine == "cycles":
        scene.cycles.samples = args.samples
    elif args.engine == "workbench":
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"

    if args.engine != "workbench" and not any(o.type == "LIGHT" for o in scene.objects) and scene.world is None:
        sun = bpy.data.objects.new("PreviewSun", bpy.data.lights.new("PreviewSun", "SUN"))
        sun.data.energy = 3.0
        sun.rotation_euler = (math.radians(45), 0, math.radians(30))
        scene.collection.objects.link(sun)

    center, radius = subject_bounds(scene)
    stem = os.path.splitext(os.path.basename(args.blend))[0]
    original_camera = scene.camera

    for view in [v.strip() for v in args.views.split(",") if v.strip()]:
        render.resolution_x = args.res
        if view == "camera":
            if original_camera is None:
                print("skip camera view: scene has no camera")
                continue
            scene.camera = original_camera
            render.resolution_y = round(args.res * camera_aspect)
        elif view in VIEW_DIRECTIONS:
            scene.camera = framing_camera(scene, center, radius, VIEW_DIRECTIONS[view])
            render.resolution_y = round(args.res * 3 / 4)
        else:
            print(f"skip unknown view '{view}' (choose from camera, {', '.join(VIEW_DIRECTIONS)})")
            continue
        render.filepath = os.path.join(os.path.abspath(args.out), f"{stem}_{view}.png")
        bpy.ops.render.render(write_still=True)
        print(f"wrote {render.filepath}")


main()
