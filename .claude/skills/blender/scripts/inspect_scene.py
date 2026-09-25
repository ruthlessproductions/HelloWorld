"""Report what is in a .blend file: sizes, placement problems, bones, materials.

Usage:
  "$BLENDER" --background --factory-startup --python inspect_scene.py -- --blend scene.blend [--json]

Flags per object:
  BELOW_GROUND  lowest point is under z=0
  FLOATING      touches no other object's bounding box and is above the ground
  Sizes are world-space dimensions including modifiers, in meters.
"""

import argparse
import json
import sys

import bpy
from mathutils import Vector

GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}
TOUCH_TOLERANCE = 0.02


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser.parse_args(argv)


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


def world_bbox(obj, depsgraph):
    points = world_points(obj, depsgraph)
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return lo, hi


def boxes_touch(a, b, tol=TOUCH_TOLERANCE):
    return all(a[0][i] - tol <= b[1][i] and a[1][i] + tol >= b[0][i] for i in range(3))


def unlinked_nodes(tree):
    linked = set()
    for link in tree.links:
        linked.add(link.from_node.name)
        linked.add(link.to_node.name)
    skip = {"FRAME", "REROUTE"}
    return [n.name for n in tree.nodes if n.name not in linked and n.type not in skip]


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=args.blend)
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    geometry = [o for o in scene.objects if o.type in GEOMETRY_TYPES and o.visible_get()]
    boxes = {o.name: world_bbox(o, depsgraph) for o in geometry}

    objects = []
    for obj in geometry:
        lo, hi = boxes[obj.name]
        dims = hi - lo
        flags = []
        if lo.z < -TOUCH_TOLERANCE:
            flags.append("BELOW_GROUND")
        touches_other = any(
            boxes_touch(boxes[obj.name], boxes[other]) for other in boxes if other != obj.name
        )
        if not touches_other and lo.z > TOUCH_TOLERANCE:
            flags.append("FLOATING")
        objects.append({
            "name": obj.name,
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else None,
            "size_m": [round(v, 3) for v in dims],
            "min_z": round(lo.z, 3),
            "center": [round(v, 3) for v in (lo + hi) / 2],
            "materials": [s.material.name for s in obj.material_slots if s.material],
            "flags": flags,
        })

    if boxes:
        all_lo = Vector((min(b[0].x for b in boxes.values()), min(b[0].y for b in boxes.values()), min(b[0].z for b in boxes.values())))
        all_hi = Vector((max(b[1].x for b in boxes.values()), max(b[1].y for b in boxes.values()), max(b[1].z for b in boxes.values())))
        scene_size = [round(v, 3) for v in all_hi - all_lo]
    else:
        scene_size = [0, 0, 0]

    armatures = [
        {"name": o.name, "bones": [b.name for b in o.data.bones]}
        for o in scene.objects if o.type == "ARMATURE"
    ]

    materials = []
    for mat in bpy.data.materials:
        if mat.users and mat.node_tree:
            loose = unlinked_nodes(mat.node_tree)
            if loose:
                materials.append({"name": mat.name, "unlinked_nodes": loose})

    report = {
        "blender": bpy.app.version_string,
        "file": args.blend,
        "render_engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "frames": [scene.frame_start, scene.frame_end, scene.render.fps],
        "camera": scene.camera.name if scene.camera else None,
        "lights": [o.name for o in scene.objects if o.type == "LIGHT"],
        "scene_size_m": scene_size,
        "objects": objects,
        "armatures": armatures,
        "materials_with_unlinked_nodes": materials,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"Blender {report['blender']}  file: {args.blend}")
    print(f"engine {report['render_engine']}  res {report['resolution']}  frames {report['frames']}  "
          f"camera {report['camera']}  lights {len(report['lights'])}")
    print(f"scene extent (m): {scene_size}")
    print(f"{'object':32} {'type':6} {'size x,y,z (m)':>24} {'min z':>7}  flags  parent")
    for o in objects:
        size = ", ".join(f"{v:.2f}" for v in o["size_m"])
        print(f"{o['name'][:32]:32} {o['type'][:6]:6} {size:>24} {o['min_z']:7.2f}  "
              f"{','.join(o['flags']) or '-'}  {o['parent'] or ''}")
    for a in armatures:
        print(f"armature {a['name']}: {len(a['bones'])} bones: {', '.join(a['bones'][:40])}")
    for m in materials:
        print(f"material {m['name']} has unlinked nodes: {', '.join(m['unlinked_nodes'])}")
    flagged = [o["name"] for o in objects if o["flags"]]
    print(f"{len(objects)} objects, {len(flagged)} flagged")


main()
