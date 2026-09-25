"""Starter build script. Copy to scenes/<name>/build.py and replace build().

Run:
  "$BLENDER" --background --factory-startup --python scenes/<name>/build.py -- --out scenes/<name>

Writes <out>/<name>.blend. Every run starts from an empty scene, so the script is the
single source of truth: to change the scene, edit this file and run it again.
"""

import argparse
import math
import os
import sys

import bpy
import bmesh  # after bpy: the pip "bpy" module only exposes bmesh once bpy is loaded
from mathutils import Vector

NAME = "scene"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    return parser.parse_args(argv)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    return scene


def link(obj, parent=None):
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def empty(name, location=(0, 0, 0), parent=None):
    obj = bpy.data.objects.new(name, None)
    obj.location = location
    return link(obj, parent)


def material(name, color, roughness=0.5, metallic=0.0, **inputs):
    """Principled BSDF material. Extra inputs by Blender 4+/5 name, e.g. Emission_Color=(1,1,1,1)."""
    mat = bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color[:3], 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    for key, value in inputs.items():
        bsdf.inputs[key.replace("_", " ")].default_value = value
    return mat


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def smooth(obj):
    obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))
    return obj


def bevel(obj, width=0.01, segments=3):
    mod = obj.modifiers.new("Bevel", "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    return obj


def mesh_object(name, bm, mat=None, parent=None):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = link(bpy.data.objects.new(name, mesh), parent)
    return assign(obj, mat) if mat else obj


def ellipsoid(name, center, size, mat=None, parent=None, segments=32):
    """UV sphere scaled to full size (x, y, z) in meters. Good for organic masses."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=segments // 2, radius=0.5)
    obj = smooth(mesh_object(name, bm, mat, parent))
    obj.location = center
    obj.scale = size
    return obj


def rod(name, start, end, radius, mat=None, parent=None, segments=16):
    """Straight cylinder between two points. Good for spokes, legs, frame tubes."""
    start, end = Vector(start), Vector(end)
    axis = end - start
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius, depth=axis.length)
    obj = mesh_object(name, bm, mat, parent)
    obj.location = (start + end) / 2
    obj.rotation_euler = Vector((0, 0, 1)).rotation_difference(axis.normalized()).to_euler()
    return smooth(obj)


def tube(name, points, radius, mat=None, parent=None, taper_end=1.0):
    """Smooth curved tube through the points. Good for necks, tails, handlebars, cables."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 4
    curve.use_fill_caps = True
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for i, (bp, co) in enumerate(zip(spline.bezier_points, points)):
        bp.co = co
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
        bp.radius = 1.0 + (taper_end - 1.0) * i / max(len(points) - 1, 1)
    obj = link(bpy.data.objects.new(name, curve), parent)
    return assign(obj, mat) if mat else obj


def ring(name, center, major_radius, minor_radius, normal=(0, 1, 0), mat=None, parent=None):
    """Torus facing along `normal` (default: upright wheel facing +Y)."""
    bm = bmesh.new()
    major_segments, minor_segments = 64, 16
    verts = []
    for i in range(major_segments):
        a = 2 * math.pi * i / major_segments
        for j in range(minor_segments):
            b = 2 * math.pi * j / minor_segments
            r = major_radius + minor_radius * math.cos(b)
            verts.append(bm.verts.new((r * math.cos(a), r * math.sin(a), minor_radius * math.sin(b))))
    for i in range(major_segments):
        for j in range(minor_segments):
            a = i * minor_segments + j
            b = ((i + 1) % major_segments) * minor_segments + j
            c = ((i + 1) % major_segments) * minor_segments + (j + 1) % minor_segments
            d = i * minor_segments + (j + 1) % minor_segments
            bm.faces.new((verts[a], verts[b], verts[c], verts[d]))
    obj = smooth(mesh_object(name, bm, mat, parent))
    obj.location = center
    obj.rotation_euler = Vector((0, 0, 1)).rotation_difference(Vector(normal).normalized()).to_euler()
    return obj


def ground(size=40, color=(0.35, 0.35, 0.33)):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2)
    return mesh_object("Ground", bm, material("Ground", color, roughness=0.9))


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def camera(location, target, lens_mm=50):
    data = bpy.data.cameras.new("Camera")
    data.lens = lens_mm
    cam = link(bpy.data.objects.new("Camera", data))
    cam.location = location
    look_at(cam, target)
    bpy.context.scene.camera = cam
    return cam


def area_light(name, location, target, power, size=2.0, color=(1, 1, 1)):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = power
    data.size = size
    data.color = color
    obj = link(bpy.data.objects.new(name, data))
    obj.location = location
    look_at(obj, target)
    return obj


def studio_lighting(target, distance=6.0, power=500):
    t = Vector(target)
    area_light("Key", t + Vector((distance, -distance, distance)), t, power, color=(1.0, 0.96, 0.9))
    area_light("Fill", t + Vector((-distance, -distance * 0.6, distance * 0.5)), t, power * 0.4, color=(0.85, 0.9, 1.0))
    area_light("Rim", t + Vector((0, distance, distance)), t, power * 0.6)


def world_color(color=(0.05, 0.06, 0.08), strength=1.0):
    world = bpy.data.worlds.new("World")
    if bpy.app.version < (5, 0, 0):
        world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*color, 1.0)
    bg.inputs["Strength"].default_value = strength
    bpy.context.scene.world = world


def render_settings(width=1920, height=1080, engine="eevee"):
    render = bpy.context.scene.render
    available = {i.identifier for i in render.bl_rna.properties["engine"].enum_items}
    if engine == "eevee":
        render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in available else "BLENDER_EEVEE"
    else:
        render.engine = "CYCLES"
    render.resolution_x = width
    render.resolution_y = height


def save(out_dir, name=NAME):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(os.path.abspath(out_dir), f"{name}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"saved {path}")
    return path


# ---------------------------------------------------------------------------
# Scene: replace this with the real build
# ---------------------------------------------------------------------------

def build():
    wood = material("Wood", (0.45, 0.28, 0.15), roughness=0.6)
    stool = empty("Stool")
    seat = rod("Seat", (0, 0, 0.43), (0, 0, 0.47), 0.18, wood, stool, segments=48)
    bevel(seat, width=0.01)
    for i in range(3):
        a = 2 * math.pi * i / 3
        foot = (0.2 * math.cos(a), 0.2 * math.sin(a), 0.0)
        top = (0.12 * math.cos(a), 0.12 * math.sin(a), 0.44)
        rod(f"Leg_{i + 1}", foot, top, 0.018, wood, stool)

    ground()
    world_color()
    studio_lighting(target=(0, 0, 0.3), distance=2.0, power=150)
    camera(location=(1.2, -1.4, 0.9), target=(0, 0, 0.25))
    render_settings()


if __name__ == "__main__":
    args = parse_args()
    reset_scene()
    build()
    save(args.out)
