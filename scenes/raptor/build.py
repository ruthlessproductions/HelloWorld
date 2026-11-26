"""A movie-scale Velociraptor with a rig and a run cycle.

Model: "Velociraptor" by Tomas Ibar (https://www.artstation.com/artwork/4XgZd8), CC BY 4.0,
source/Velo_sketchfab.fbx. See ATTRIBUTION.md for the changes made here.

Run:
  "$BLENDER" --background --factory-startup --python scenes/raptor/build.py -- --out scenes/raptor

Writes <out>/raptor.blend: the raptor running across a plain ground, for checking the rig. Other
scenes import this file and call build_raptor() and run_along().

Axes: the raptor faces +X, +Z is up, +Y is its left.
"""

import argparse
import math
import os
import sys

import bpy
import bmesh  # after bpy: the pip "bpy" module only exposes bmesh once bpy is loaded
from mathutils import Matrix, Vector

NAME = "raptor"


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
    mat.diffuse_color = (*color[:3], 1.0)    # viewport color: what Workbench previews show
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
# The raptor: imported from the Sketchfab FBX, rigged here, and animated with a run cycle
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
FBX = os.path.join(HERE, "source", "Velo_sketchfab.fbx")
TEXTURES = os.path.join(HERE, "textures")     # 2K copies of the Sketchfab 4K maps

# Joint positions measured from the mesh (meters; raptor faces +X, feet on z=0, left is +Y)
SPINE = {   # bone: (head, tail, parent)
    "pelvis": ((-0.55, 0, 0.93), (-0.30, 0, 0.96), None),
    "spine": ((-0.30, 0, 0.96), (-0.02, 0, 1.08), "pelvis"),
    "neck1": ((-0.02, 0, 1.08), (0.08, 0, 1.33), "spine"),
    "neck2": ((0.08, 0, 1.33), (0.20, 0, 1.52), "neck1"),
    "head": ((0.20, 0, 1.52), (0.76, 0, 1.58), "neck2"),
    "tail1": ((-0.55, 0, 0.93), (-1.00, 0, 0.94), "pelvis"),
    "tail2": ((-1.00, 0, 0.94), (-1.45, 0, 1.03), "tail1"),
    "tail3": ((-1.45, 0, 1.03), (-1.90, 0, 1.08), "tail2"),
    "tail4": ((-1.90, 0, 1.08), (-2.25, 0, 1.03), "tail3"),
    "tail5": ((-2.25, 0, 1.03), (-2.53, 0, 0.90), "tail4"),
}
LEG = [   # bone, head, tail (left side; the right mirrors y), parent
    ("thigh", (-0.50, 0.16, 0.86), (-0.36, 0.19, 0.57), "pelvis"),
    ("shin", (-0.36, 0.19, 0.57), (-0.58, 0.19, 0.26), "thigh"),
    ("meta", (-0.58, 0.19, 0.26), (-0.42, 0.20, 0.05), "shin"),
    ("toe", (-0.42, 0.20, 0.05), (-0.20, 0.21, 0.02), "meta"),
]
ARM = [
    ("upperarm", (-0.02, 0.22, 0.95), (-0.03, 0.33, 0.74), "spine"),
    ("forearm", (-0.03, 0.33, 0.74), (0.14, 0.35, 0.50), "upperarm"),
    ("hand", (0.14, 0.35, 0.50), (0.06, 0.34, 0.33), "forearm"),
]
RIGID_TO_HEAD = ("cornea", "velo_eye_low", "velo_top_teeth_low", "velo_bottom_teeth_low", "velo_gums_low",
                 "velo_tongue_low")


def import_raptor_meshes():
    """Import the FBX, bake its 0.01 scale and Y-forward orientation into the meshes, stand it on z=0
    facing +X, and drop the FBX's empty and camera."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=FBX)
    bpy.context.view_layer.update()
    fix = Matrix.Translation((0, 0, 0.243)) @ Matrix.Rotation(math.radians(90), 4, "Z")
    meshes = {}
    for obj in set(bpy.data.objects) - before:
        if obj.type == "MESH":
            obj.data.transform(fix @ obj.matrix_world)
            obj.parent = None
            obj.matrix_world = Matrix.Identity(4)
            meshes[obj.name] = obj
    for obj in set(bpy.data.objects) - before:
        if obj.type != "MESH":
            bpy.data.objects.remove(obj)
    return meshes


def skin_material():
    """PBR skin from the texture set. The normal map is DirectX-style, so its green channel is flipped
    for Blender; the baked AO darkens the base color's crevices."""
    mat = material("Raptor_Skin", (0.45, 0.33, 0.18), roughness=0.6)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]

    def image(name, color_data):
        node = nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(os.path.join(TEXTURES, name), check_existing=True)
        node.image.colorspace_settings.name = "sRGB" if color_data else "Non-Color"
        return node

    base, ao, rough, normal = (image("Base_Color_2k.png", True), image("Mixed_AO_2k.png", False),
                               image("Roughness_2k.png", False), image("Normal_DirectX_2k.png", False))
    ao_range = nodes.new("ShaderNodeMapRange")
    ao_range.inputs["To Min"].default_value = 0.45
    shade = nodes.new("ShaderNodeVectorMath")
    shade.operation = "SCALE"
    links.new(ao.outputs["Color"], ao_range.inputs["Value"])
    links.new(base.outputs["Color"], shade.inputs[0])
    links.new(ao_range.outputs["Result"], shade.inputs["Scale"])
    links.new(shade.outputs["Vector"], bsdf.inputs["Base Color"])
    links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])

    split = nodes.new("ShaderNodeSeparateColor")
    flip = nodes.new("ShaderNodeMath")
    flip.operation = "SUBTRACT"
    flip.inputs[0].default_value = 1.0
    join = nodes.new("ShaderNodeCombineColor")
    normal_map = nodes.new("ShaderNodeNormalMap")
    links.new(normal.outputs["Color"], split.inputs["Color"])
    links.new(split.outputs["Red"], join.inputs["Red"])
    links.new(split.outputs["Green"], flip.inputs[1])
    links.new(flip.outputs["Value"], join.inputs["Green"])
    links.new(split.outputs["Blue"], join.inputs["Blue"])
    links.new(join.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def build_armature(parent=None):
    data = bpy.data.armatures.new("Raptor_Rig")
    arm = link(bpy.data.objects.new("Raptor_Rig", data), parent)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    specs = [(name, head, tail, par) for name, (head, tail, par) in SPINE.items()]
    for side, suffix in ((1, "L"), (-1, "R")):
        for chain in (LEG, ARM):
            for name, head, tail, par in chain:
                mirror = lambda p: (p[0], p[1] * side, p[2])
                specs.append((f"{name}.{suffix}", mirror(head), mirror(tail),
                              par if par in SPINE else f"{par}.{suffix}"))
    for name, head, tail, par in specs:
        bone = data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        # Roll so local X points left (+Y): a rotation about X then pitches the bone in the side view
        bone.align_roll(Vector((0, 1, 0)).cross((Vector(tail) - Vector(head)).normalized()))
        if par:
            bone.parent = data.edit_bones[par]
            bone.use_connect = (Vector(head) - bone.parent.tail).length < 1e-4
    bpy.ops.object.mode_set(mode="OBJECT")
    for pbone in arm.pose.bones:
        pbone.rotation_mode = "XYZ"
    return arm


def bind(arm, meshes):
    """Skin the body with automatic (bone heat) weights; the eyes, teeth, gums and tongue ride the head."""
    body = meshes["velo_body_low"]
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    if not body.vertex_groups or all(len(v.groups) == 0 for v in body.data.vertices[:200]):
        raise RuntimeError("automatic weights failed")
    bpy.context.view_layer.update()
    for name in RIGID_TO_HEAD:
        obj = meshes[name]
        world = obj.matrix_world.copy()
        obj.parent, obj.parent_type, obj.parent_bone = arm, "BONE", "head"
        obj.matrix_world = world


def leg_controls(arm):
    """IK: the thigh and shin reach an ankle target with the knee aimed forward by a pole; the
    metatarsus and toes aim at ball and toe-tip targets. All targets are children of the rig."""
    targets = {}
    for suffix, side in (("L", 1), ("R", -1)):
        bones = {name: arm.data.bones[f"{name}.{suffix}"] for name in ("shin", "meta", "toe")}
        for key, point in (("ankle", bones["shin"].tail_local), ("ball", bones["meta"].tail_local),
                           ("toe", bones["toe"].tail_local),
                           ("pole", bones["shin"].head_local + Vector((0.8, 0, 0.05)))):
            targets[f"{key}.{suffix}"] = empty(f"Raptor_{key.title()}_{suffix}", point, arm)
            targets[f"{key}.{suffix}"].empty_display_size = 0.05
        ik = arm.pose.bones[f"shin.{suffix}"].constraints.new("IK")
        ik.target, ik.pole_target, ik.chain_count = targets[f"ankle.{suffix}"], targets[f"pole.{suffix}"], 2
        for bone, key in (("meta", "ball"), ("toe", "toe")):
            track = arm.pose.bones[f"{bone}.{suffix}"].constraints.new("DAMPED_TRACK")
            track.target = targets[f"{key}.{suffix}"]
        # Pick the pole angle that leaves the rest pose unchanged
        rest_knee = bones["shin"].head_local.copy()
        best = min((math.radians(a) for a in (-180, -90, 0, 90)),
                   key=lambda a: _knee_error(arm, ik, a, suffix, rest_knee))
        ik.pole_angle = best
    return targets


def _knee_error(arm, ik, angle, suffix, rest_knee):
    ik.pole_angle = angle
    bpy.context.view_layer.update()
    return (arm.pose.bones[f"shin.{suffix}"].head - rest_knee).length


def build_raptor(mats_fish=None, parent=None):
    """Import, texture and rig the raptor. Returns the armature object (the thing to move)."""
    meshes = import_raptor_meshes()
    skin = skin_material()
    skin.diffuse_color = (0.45, 0.33, 0.18, 1.0)
    for name, obj in meshes.items():
        if name != "cornea":
            assign(obj, skin)
        smooth(obj)
    cornea = material("Raptor_Cornea", (1, 1, 1), roughness=0.02, Transmission_Weight=1.0)
    assign(meshes["cornea"], cornea)
    arm = build_armature(parent)
    bind(arm, meshes)
    for obj in meshes.values():
        obj.name = "Raptor_" + obj.name.replace("velo_", "").replace("_low", "").title()
    leg_controls(arm)
    return arm


# ---------------------------------------------------------------------------
# Run cycle
# ---------------------------------------------------------------------------

STRIDE = 1.85          # meters covered per full cycle (two steps)
DUTY = 0.3             # fraction of the cycle each foot is on the ground: a run with a flight phase
BALL_X, BALL_Z = -0.40, 0.05
TOE = Vector((0.22, 0, -0.03))
META_LEN = (Vector(LEG[2][2]) - Vector(LEG[2][1])).length


def foot_targets(phase, side):
    """Ball, ankle and toe-tip targets (rig space) for one foot at `phase` of the cycle (0-1).
    In stance the ball slides back at exactly the running speed, so it stays put on the ground."""
    stance = DUTY * STRIDE
    if phase < DUTY:
        s = phase / DUTY
        x, lift, meta_tilt, curl = BALL_X + stance / 2 - stance * s, 0.0, lerp_(35, 55, s), 0.0
    else:
        s = (phase - DUTY) / (1 - DUTY)
        ease = s * s * (3 - 2 * s)
        x = BALL_X - stance / 2 + stance * ease
        lift = 0.30 * math.sin(math.pi * s) ** 0.8
        meta_tilt = 55 + 25 * math.sin(math.pi * s) - 20 * s
        curl = 40 * math.sin(math.pi * s)
    y = LEG[2][2][1] * side
    ball = Vector((x, y, BALL_Z + lift))
    t = math.radians(meta_tilt)                   # metatarsus tilt back from vertical
    ankle = ball + Vector((-math.sin(t), 0, math.cos(t))) * META_LEN
    c = math.radians(curl)
    toe = ball + Vector((TOE.x * math.cos(c) + TOE.z * math.sin(c), 0, -TOE.x * math.sin(c) + TOE.z * math.cos(c)))
    return ball, ankle, toe


def lerp_(a, b, t):
    return a + (b - a) * t


def pose_run(arm, phase, frame=None):
    """Pose the rig at `phase` of the run cycle: feet on their IK targets, pelvis bobbing twice a
    cycle, spine and tail swaying against the stride, neck stretched forward, head held steady."""
    def key(obj, path, value, index):
        getattr(obj, path)[index] = value
        if frame is not None:
            obj.keyframe_insert(path, index=index, frame=frame)

    for suffix, side, offset in (("L", 1, 0.0), ("R", -1, 0.5)):
        ball, ankle, toe = foot_targets((phase + offset) % 1.0, side)
        for name, point in (("Ball", ball), ("Ankle", ankle), ("Toe", toe)):
            target = bpy.data.objects[f"Raptor_{name}_{suffix}"]
            for i in range(3):
                key(target, "location", point[i], i)

    pb = arm.pose.bones
    w = 2 * math.pi * phase
    bob = -0.045 * math.cos(2 * (w - 2 * math.pi * DUTY / 2))       # lowest mid-stance of each foot
    up_local = arm.data.bones["pelvis"].matrix_local.inverted().to_3x3() @ Vector((0, 0, 1))
    for i in range(3):
        key(pb["pelvis"], "location", up_local[i] * bob, i)
    key(pb["pelvis"], "rotation_euler", math.radians(2.0) * math.sin(2 * w), 0)
    key(pb["spine"], "rotation_euler", math.radians(4) * math.sin(w), 2)
    key(pb["neck1"], "rotation_euler", math.radians(18), 0)                       # neck reaches forward
    key(pb["neck2"], "rotation_euler", math.radians(-4), 0)
    key(pb["head"], "rotation_euler", math.radians(-12) - math.radians(2.0) * math.sin(2 * w), 0)
    for k in range(5):
        lag = w - 0.7 * (k + 1)
        key(pb[f"tail{k + 1}"], "rotation_euler", math.radians(3 + 1.5 * k) * math.sin(lag), 2)
        key(pb[f"tail{k + 1}"], "rotation_euler", math.radians(-1.5) * math.sin(2 * lag) + math.radians(1), 0)
    for suffix, side in (("L", 1), ("R", -1)):
        key(pb[f"upperarm.{suffix}"], "rotation_euler", math.radians(6) * math.sin(w + (0 if side > 0 else math.pi)), 0)
        key(pb[f"forearm.{suffix}"], "rotation_euler", math.radians(-10), 0)


def run_along(arm, points_fn, heading_fn, frames, fps, speed):
    """Move the rig along a path (points_fn(t) in meters, heading_fn(t) in radians) and key the run
    cycle every frame, timed so the planted foot never slides."""
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    for frame in range(frames[0], frames[1] + 1):
        t = (frame - frames[0]) / fps
        arm.location = points_fn(t)
        arm.rotation_euler = (0, 0, heading_fn(t))
        arm.keyframe_insert("location", frame=frame)
        arm.keyframe_insert("rotation_euler", index=2, frame=frame)
        pose_run(arm, (speed * t / STRIDE) % 1.0, frame=frame)


def build():
    """Standalone check: the raptor running across a plain ground, followed by a side camera."""
    bpy.context.scene.render.fps = 24
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 48
    ground()
    arm = build_raptor()
    speed = 2.2
    run_along(arm, lambda t: Vector((speed * t, 0, 0)), lambda t: 0.0, (1, 48), 24, speed)
    cam = camera(location=(0.2, -5.2, 1.0), target=(0, 0, 0.75), lens_mm=35)
    cam.parent = arm                                # rides along beside the raptor
    world_color((0.55, 0.62, 0.72), 0.8)
    sun = link(bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN")))
    sun.data.energy = 3.5
    sun.location = (3, -4, 6)
    look_at(sun, (0, 0, 0))
    render_settings(engine="cycles")
    bpy.context.scene.cycles.samples = 64


if __name__ == "__main__":
    args = parse_args()
    reset_scene()
    build()
    save(args.out)
