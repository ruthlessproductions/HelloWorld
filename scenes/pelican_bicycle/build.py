"""A white pelican riding a city bicycle down a road, with a basket of fish up front.

Run:
  "$BLENDER" --background --factory-startup --python scenes/pelican_bicycle/build.py -- --out scenes/pelican_bicycle

Writes <out>/pelican_bicycle.blend. Every run starts from an empty scene, so the script is the
single source of truth: to change the scene, edit this file and run it again.

Axes: the bike rides toward +X, +Z is up, +Y is the rider's left (drive side is -Y).
"""

import argparse
import math
import os
import sys

import bpy
import bmesh  # after bpy: the pip "bpy" module only exposes bmesh once bpy is loaded
from mathutils import Matrix, Vector

NAME = "pelican_bicycle"


# ---------------------------------------------------------------------------
# Helpers (from the skill template)
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
# Extra helpers for this scene
# ---------------------------------------------------------------------------

def _val(f, t):
    return f(t) if callable(f) else f


def lerp(a, b, t):
    return a + (b - a) * t


def catmull_rom(points, samples):
    """Smooth path through the control points, `samples` points long."""
    pts = [Vector(p) for p in points]
    ext = [pts[0] * 2 - pts[1]] + pts + [pts[-1] * 2 - pts[-2]]
    segs = len(pts) - 1
    out = []
    for i in range(samples):
        u = i / (samples - 1) * segs
        s = min(int(u), segs - 1)
        t = u - s
        p0, p1, p2, p3 = ext[s], ext[s + 1], ext[s + 2], ext[s + 3]
        out.append(0.5 * ((2 * p1) + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                          + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    return out


def path_frames(ctrl, samples, side=None, up=(0, 0, 1)):
    """Points along a smooth path with (tangent, side, normal) frames: side = `side` made
    perpendicular to the path, or path x `up`."""
    path = catmull_rom(ctrl, samples)
    n = len(path)
    frames = []
    for i, c in enumerate(path):
        tangent = (path[min(i + 1, n - 1)] - path[max(i - 1, 0)]).normalized()
        if side is not None:
            s = Vector(side) - tangent * Vector(side).dot(tangent)
        else:
            s = tangent.cross(Vector(up))
        if s.length < 1e-6:
            s = tangent.orthogonal()
        s.normalize()
        frames.append((c, tangent, s, s.cross(tangent).normalized()))
    return frames


def loft(name, ctrl, half_w, half_h, side=None, up=(0, 0, 1), mats=(), parent=None,
         samples=32, ring_verts=24, offset=0.0, mat_fn=None):
    """Elliptical cross-section swept along a smooth path.

    half_w runs along `side` (or path x `up`), half_h along the remaining normal; both, and
    `offset` (shift of the section along that normal), may be callables of t in [0, 1].
    mat_fn(t, direction) picks a material index per face from its outward direction.
    """
    frames = path_frames(ctrl, samples, side, up)
    n = len(frames)
    bm = bmesh.new()
    rings, dirs = [], []
    for i, (c, tangent, s, nrm) in enumerate(frames):
        t = i / (n - 1)
        hw, hh, off = _val(half_w, t), _val(half_h, t), _val(offset, t)
        verts, ds = [], []
        for k in range(ring_verts):
            a = 2 * math.pi * k / ring_verts
            verts.append(bm.verts.new(c + nrm * off + s * hw * math.cos(a) + nrm * hh * math.sin(a)))
            ds.append(s * math.cos(a) + nrm * math.sin(a))
        rings.append(verts)
        dirs.append(ds)
    for i in range(n - 1):
        t = (i + 0.5) / (n - 1)
        for k in range(ring_verts):
            k2 = (k + 1) % ring_verts
            face = bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
            if mat_fn:
                face.material_index = mat_fn(t, (dirs[i][k] + dirs[i][k2]).normalized())
    bm.faces.new(rings[0])
    bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    obj = mesh_object(name, bm, None, parent)
    for m in mats:
        obj.data.materials.append(m)
    return smooth(obj)


def rods(name, segments, radius, mat=None, parent=None, sides=8):
    """Many thin cylinders in one mesh (spokes, basket wires)."""
    bm = bmesh.new()
    for a, b in segments:
        a, b = Vector(a), Vector(b)
        axis = b - a
        rot = Vector((0, 0, 1)).rotation_difference(axis.normalized()).to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=sides, radius1=radius, radius2=radius,
                              depth=axis.length, matrix=Matrix.Translation((a + b) / 2) @ rot)
    return smooth(mesh_object(name, bm, mat, parent))


def box(name, center, size, mat=None, parent=None, bevel_width=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal((*size, 1.0)))
    obj = mesh_object(name, bm, mat, parent)
    obj.location = center
    if bevel_width:
        bevel(obj, bevel_width)
    return obj


def poly_tube(name, points, radius, mat=None, parent=None, cyclic=False):
    """Tube along straight segments (chain, wire loops)."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 2
    curve.use_fill_caps = not cyclic
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for p, co in zip(spline.points, points):
        p.co = (*co, 1.0)
    spline.use_cyclic_u = cyclic
    obj = link(bpy.data.objects.new(name, curve), parent)
    return assign(obj, mat) if mat else obj


def flat_shape(name, outline, thickness, mat=None, parent=None):
    """Extruded 2D outline given in 3D points (feet webbing, fins)."""
    bm = bmesh.new()
    bm.faces.new([bm.verts.new(p) for p in outline])
    obj = mesh_object(name, bm, mat, parent)
    mod = obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = thickness
    mod.offset = 0.0
    return obj


def gear(name, center, y, teeth, pitch_r, mat, parent, inner_r=None, thickness=0.003):
    """Toothed ring in the XZ plane (chainring, cassette cog)."""
    tip, root = pitch_r + 0.004, pitch_r - 0.003
    inner_r = inner_r or pitch_r - 0.016
    bm = bmesh.new()
    n = teeth * 4
    outer, inner = [], []
    for k in range(n):
        a = 2 * math.pi * k / n
        r = tip if k % 4 in (1, 2) else root
        outer.append(bm.verts.new((r * math.cos(a), 0, r * math.sin(a))))
        inner.append(bm.verts.new((inner_r * math.cos(a), 0, inner_r * math.sin(a))))
    for k in range(n):
        k2 = (k + 1) % n
        bm.faces.new((outer[k], outer[k2], inner[k2], inner[k]))
    obj = mesh_object(name, bm, mat, parent)
    obj.location = (center.x, y, center.z)
    mod = obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = thickness
    mod.offset = 0.0
    return obj


def convex_hull_2d(points):
    pts = sorted(set(points))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def rounded_rect(x0, x1, y0, y1, z, r=0.02, steps=4):
    pts = []
    corners = [(x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270)]
    for cx, cy, start in corners:
        for k in range(steps + 1):
            a = math.radians(start + 90 * k / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    return pts


def pivot(name, location, parent=None):
    """Empty that a group of parts turns about; `location` is in world space at build time."""
    obj = empty(name, parent=parent)
    bpy.context.view_layer.update()
    parent_world = parent.matrix_world if parent else Matrix.Identity(4)
    obj.location = parent_world.inverted() @ Vector(location)
    return obj


def adopt(objs, pivot_obj):
    """Parent parts to a pivot without moving them."""
    bpy.context.view_layer.update()
    for obj in objs:
        world = obj.matrix_world.copy()
        obj.parent = pivot_obj
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = world
    return pivot_obj


def knee_point(hip, ankle, l1, l2, forward=Vector((1, 0, 0))):
    """Two-bone IK: knee position that bends toward `forward`."""
    d = ankle - hip
    dist = min(d.length, l1 + l2 - 1e-4)
    axis = d.normalized()
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    perp = (forward - axis * forward.dot(axis)).normalized()
    return hip + axis * a + perp * h


def noise_bump(mat, scale, strength, distance=0.01):
    """Fine surface relief (feathers, asphalt) from a noise texture in object space."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    coords = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 4.0
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    links.new(coords.outputs["Object"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def noise_color(mat, scale, color_a, color_b):
    """Blotchy two-tone base color (grass)."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    coords = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (*color_a, 1.0)
    ramp.color_ramp.elements[1].position = 0.65
    ramp.color_ramp.elements[1].color = (*color_b, 1.0)
    links.new(coords.outputs["Object"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def sky_gradient(horizon, zenith, strength=1.0):
    """World that blends from a pale horizon to a deeper blue overhead."""
    world = bpy.data.worlds.new("Sky")
    if bpy.app.version < (5, 0, 0):
        world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    bg = nodes["Background"]
    bg.inputs["Strength"].default_value = strength
    coords = nodes.new("ShaderNodeTexCoord")
    xyz = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (*horizon, 1.0)
    ramp.color_ramp.elements[1].position = 0.35
    ramp.color_ramp.elements[1].color = (*zenith, 1.0)
    links.new(coords.outputs["Generated"], xyz.inputs["Vector"])
    links.new(xyz.outputs["Z"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bpy.context.scene.world = world


# ---------------------------------------------------------------------------
# Bicycle geometry (meters)
# ---------------------------------------------------------------------------

TIRE_TUBE = 0.018                      # tire cross-section radius
TIRE_R = 0.325                         # tire centerline radius
AXLE_Z = TIRE_R + TIRE_TUBE            # wheel center height: tire touches the road at z=0
REAR = Vector((-0.50, 0, AXLE_Z))
FRONT = Vector((0.52, 0, AXLE_Z))
BB = Vector((-0.08, 0, 0.27))          # bottom bracket
CRANK_LEN = 0.17
CRANK_ANGLE = math.radians(20)         # drive-side crank points forward and slightly up

SEAT_DIR = Vector((-math.cos(math.radians(73)), 0, math.sin(math.radians(73))))
STEER_DIR = Vector((-math.cos(math.radians(72)), 0, math.sin(math.radians(72))))
FORK_RAKE = 0.045
_steer_base = FRONT - Vector((STEER_DIR.z, 0, -STEER_DIR.x)) * FORK_RAKE
HT_BOTTOM = _steer_base + STEER_DIR * 0.38
HT_TOP = HT_BOTTOM + STEER_DIR * 0.13
ST_TOP = BB + SEAT_DIR * 0.50
SADDLE_POST_TOP = ST_TOP + SEAT_DIR * 0.16

BAR_CENTER = Vector((0.37, 0, 0.89))
GRIP_IN = Vector((0.328, 0.18, 0.895))  # left grip, inner end (mirror y for the right)
GRIP_OUT = Vector((0.302, 0.262, 0.90))

CHAIN_Y = -0.040
CHAIN_COG = 28                         # the chain runs on the largest cog: an easy cruising gear
CASSETTE_Y = {teeth: -0.050 + 0.005 * k for k, teeth in enumerate((14, 16, 20, 24, 28))}


def pedal_center(side, crank_rot=0.0):
    """side=-1: drive side (right), +1: left. Returns the pedal axle point with the crank turned
    crank_rot radians forward (about +Y) from the rest pose."""
    a = (CRANK_ANGLE if side < 0 else CRANK_ANGLE + math.pi) - crank_rot
    return BB + Vector((math.cos(a), 0, math.sin(a))) * CRANK_LEN + Vector((0, 0.12 * side, 0))


def mirror_y(v, side):
    return Vector((v.x, v.y * side, v.z))


def build_wheel(name, center, parent, mats, drive_cassette=False):
    wheel = empty(name, (0, 0, 0), parent)
    ring(f"{name}_Tire", center, TIRE_R, TIRE_TUBE, mat=mats["rubber"], parent=wheel)
    ring(f"{name}_Rim", center, 0.300, 0.011, mat=mats["alu"], parent=wheel)
    rod(f"{name}_Hub", center + Vector((0, -0.05, 0)), center + Vector((0, 0.05, 0)), 0.016,
        mats["alu"], wheel, segments=24)
    rod(f"{name}_Axle", center + Vector((0, -0.075, 0)), center + Vector((0, 0.075, 0)), 0.005,
        mats["chrome"], wheel)
    flange_y = (-0.022, 0.035) if drive_cassette else (-0.035, 0.035)
    for i, fy in enumerate(flange_y):
        rod(f"{name}_Flange_{i + 1}", center + Vector((0, fy - 0.002, 0)), center + Vector((0, fy + 0.002, 0)),
            0.028, mats["alu"], wheel, segments=24)

    spokes = []
    for i in range(32):
        a = 2 * math.pi * i / 32
        fy = flange_y[i % 2]
        lead = 1 if (i // 2) % 2 == 0 else -1
        ha = a + lead * 0.55
        hub_pt = center + Vector((0.025 * math.cos(ha), fy, 0.025 * math.sin(ha)))
        rim_pt = center + Vector((0.296 * math.cos(a), 0, 0.296 * math.sin(a)))
        spokes.append((hub_pt, rim_pt))
    rods(f"{name}_Spokes", spokes, 0.0014, mats["chrome"], wheel, sides=6)

    if drive_cassette:
        for teeth, y in CASSETTE_Y.items():
            gear(f"{name}_Cog_{teeth}T", center, y, teeth, teeth * 0.0127 / (2 * math.pi),
                 mats["steel"], wheel, inner_r=0.012, thickness=0.002)
    adopt(list(wheel.children), pivot(f"{name}_Spin", center, wheel))    # rolls about its axle
    return wheel


def build_bicycle(mats):
    bike = empty("Bicycle")
    frame = empty("Frame", parent=bike)
    paint = mats["paint"]

    # Main triangle and head tube
    rod("Head_Tube", HT_BOTTOM - STEER_DIR * 0.01, HT_TOP + STEER_DIR * 0.01, 0.021, paint, frame, 24)
    for i, p in enumerate((HT_BOTTOM - STEER_DIR * 0.012, HT_TOP + STEER_DIR * 0.012)):
        rod(f"Headset_{i + 1}", p - STEER_DIR * 0.007, p + STEER_DIR * 0.007, 0.024, mats["chrome"], frame, 24)
    rod("Top_Tube", ST_TOP - SEAT_DIR * 0.02, HT_TOP - STEER_DIR * 0.02, 0.016, paint, frame, 24)
    rod("Down_Tube", BB, HT_BOTTOM + STEER_DIR * 0.03, 0.021, paint, frame, 24)
    rod("Seat_Tube", BB, ST_TOP, 0.017, paint, frame, 24)
    rod("BB_Shell", BB + Vector((0, -0.036, 0)), BB + Vector((0, 0.036, 0)), 0.021, paint, frame, 24)

    # Rear triangle: stays converge from the frame to the dropouts either side of the hub
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        drop = REAR + Vector((0, 0.065 * side, 0))
        rod(f"Chainstay_{s}", BB + Vector((0, 0.02 * side, 0)), drop, 0.010, paint, frame)
        tube(f"Seatstay_{s}", [ST_TOP - SEAT_DIR * 0.03 + Vector((0, 0.018 * side, 0)),
                               (ST_TOP + drop) / 2 + Vector((0, 0.01 * side, 0.01)),
                               drop], 0.009, paint, frame)
        rod(f"Dropout_{s}", drop + Vector((-0.015, 0, -0.01)), drop + Vector((0.02, 0, 0.012)), 0.012,
            paint, frame)

    # Fork: blades curve forward into the axle for rake
    fork = empty("Fork", parent=bike)
    crown = HT_BOTTOM - STEER_DIR * 0.03
    rod("Fork_Crown", crown + Vector((0, -0.058, 0)), crown + Vector((0, 0.058, 0)), 0.016, paint, fork, 24)
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        off = Vector((0, 0.052 * side, 0))
        mid = HT_BOTTOM - STEER_DIR * 0.24 + Vector((0.012, 0, 0))
        tube(f"Fork_Blade_{s}", [crown + off, mid + off, FRONT + off], 0.014, paint, fork, taper_end=0.65)

    # Cockpit: gooseneck stem, swept city bar, leather grips, bell
    cockpit = empty("Cockpit", parent=bike)
    stem_rise = HT_TOP + STEER_DIR * 0.06
    tube("Stem", [HT_TOP - STEER_DIR * 0.01, stem_rise, BAR_CENTER + Vector((0.005, 0, 0))], 0.013,
         mats["chrome"], cockpit)
    bar_pts = [mirror_y(GRIP_OUT, -1), Vector((0.325, -0.19, 0.895)), Vector((0.36, -0.09, 0.89)), BAR_CENTER,
               Vector((0.36, 0.09, 0.89)), Vector((0.325, 0.19, 0.895)), GRIP_OUT]
    tube("Handlebar", bar_pts, 0.011, mats["chrome"], cockpit)
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        g_in, g_out = mirror_y(GRIP_IN, side), mirror_y(GRIP_OUT, side)
        rod(f"Grip_{s}", g_in, g_out + (g_out - g_in).normalized() * 0.006, 0.017, mats["leather"], cockpit, 24)
    bell_base = Vector((0.362, 0.105, 0.90))
    rod("Bell_Clamp", bell_base + Vector((0, -0.008, 0)), bell_base + Vector((0, 0.008, 0)), 0.014,
        mats["chrome"], cockpit)
    bell = ellipsoid("Bell", bell_base + Vector((0, 0, 0.022)), (0.05, 0.05, 0.036), mats["chrome"], cockpit)

    # Seat post and sprung leather saddle
    rod("Seat_Post", ST_TOP - SEAT_DIR * 0.05, SADDLE_POST_TOP, 0.013, mats["chrome"], bike)
    saddle_z = SADDLE_POST_TOP.z + 0.03
    loft("Saddle", [(-0.39, 0, saddle_z + 0.004), (-0.32, 0, saddle_z + 0.003), (-0.22, 0, saddle_z),
                    (-0.13, 0, saddle_z - 0.004)],
         half_w=lambda t: lerp(0.085, 0.024, min(1, t * 1.25) ** 1.6),
         half_h=lambda t: lerp(0.026, 0.017, t), side=(0, 1, 0), mats=[mats["leather"]], parent=bike,
         samples=20, ring_verts=24)
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        rail_y = 0.03 * side
        tube(f"Saddle_Rail_{s}", [(SADDLE_POST_TOP.x - 0.10, rail_y, saddle_z - 0.012),
                                  (SADDLE_POST_TOP.x, rail_y, SADDLE_POST_TOP.z - 0.002),
                                  (SADDLE_POST_TOP.x + 0.12, rail_y * 0.5, saddle_z - 0.014)],
             0.0035, mats["chrome"], bike)
        for k in range(2):
            x = SADDLE_POST_TOP.x - 0.085 + k * 0.02
            coil_pts = [(x + 0.012 * math.cos(u * 0.5), rail_y * 2.2 + 0.012 * math.sin(u * 0.5),
                         saddle_z - 0.05 + u * 0.0012) for u in range(0, 38)]
            poly_tube(f"Saddle_Spring_{s}_{k + 1}", coil_pts, 0.0022, mats["chrome"], bike)

    # Wheels
    build_wheel("Rear_Wheel", REAR, bike, mats, drive_cassette=True)
    build_wheel("Front_Wheel", FRONT, bike, mats)

    # Drivetrain: chainring, cranks, pedals, chain
    drive = empty("Drivetrain", parent=bike)
    ring_pitch = 44 * 0.0127 / (2 * math.pi)
    gear("Chainring", BB, CHAIN_Y, 44, ring_pitch, mats["alu"], drive, inner_r=0.068, thickness=0.004)
    spider = []
    for k in range(5):
        a = 2 * math.pi * k / 5 + 0.3
        spider.append((BB + Vector((0.015 * math.cos(a), CHAIN_Y - 0.004, 0.015 * math.sin(a))),
                       BB + Vector((0.072 * math.cos(a), CHAIN_Y - 0.004, 0.072 * math.sin(a)))))
    rods("Chainring_Spider", spider, 0.007, mats["alu"], drive)
    rod("BB_Spindle", BB + Vector((0, -0.07, 0)), BB + Vector((0, 0.07, 0)), 0.011, mats["steel"], drive)
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        p = pedal_center(side)
        arm_y = 0.058 * side
        loft(f"Crank_Arm_{s}", [BB + Vector((0, arm_y, 0)), Vector((p.x, arm_y, p.z))],
             half_w=lambda t: lerp(0.019, 0.013, t), half_h=0.007, up=(0, 1, 0), mats=[mats["alu"]],
             parent=drive, samples=6, ring_verts=16)
        rod(f"Pedal_Spindle_{s}", Vector((p.x, arm_y, p.z)), Vector((p.x, 0.168 * side, p.z)), 0.006,
            mats["steel"], drive)
        box(f"Pedal_{s}", Vector((p.x, 0.12 * side, p.z)), (0.075, 0.09, 0.022), mats["rubber"], drive,
            bevel_width=0.004)

    # The crank turns the chainring and arms about the bottom bracket; each pedal counter-rotates
    # on its spindle so it stays level under the foot
    crank = pivot("Crank", BB, drive)
    adopt([o for o in drive.children if o.name.startswith(("Chainring", "BB_Spindle", "Crank_Arm", "Pedal_Spindle"))],
          crank)
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        adopt([bpy.data.objects[f"Pedal_{s}"]], pivot(f"Pedal_Pivot_{s}", pedal_center(side), crank))

    # Chain: wraps the chainring top/bottom and the cog, as the convex hull of both circles
    cog_pitch = CHAIN_COG * 0.0127 / (2 * math.pi)
    chain_y = (CHAIN_Y + CASSETTE_Y[CHAIN_COG]) / 2
    pts = []
    for c, r in ((BB, ring_pitch), (REAR, cog_pitch)):
        for k in range(72):
            a = 2 * math.pi * k / 72
            pts.append((round(c.x + r * math.cos(a), 5), round(c.z + r * math.sin(a), 5)))
    hull = convex_hull_2d(pts)
    poly_tube("Chain", [(x, chain_y, z) for x, z in hull], 0.0045, mats["chain"], drive, cyclic=True)

    build_basket(bike, mats)
    return bike


def build_basket(bike, mats):
    basket = empty("Basket", parent=bike)
    x0, x1, y0, y1, zb, zt = 0.42, 0.66, -0.14, 0.14, 0.73, 0.93
    wire = mats["wire"]
    for k, z in enumerate((zb, (zb + zt) / 2, zt)):
        poly_tube(f"Basket_Rim_{k + 1}", rounded_rect(x0, x1, y0, y1, z), 0.005 if k != 1 else 0.003,
                  wire, basket, cyclic=True)
    uprights = []
    loop = rounded_rect(x0, x1, y0, y1, 0.0, steps=1)
    perimeter = []
    for i in range(len(loop)):
        a, b = Vector(loop[i]), Vector(loop[(i + 1) % len(loop)])
        n = max(1, round((b - a).length / 0.035))
        perimeter += [a + (b - a) * j / n for j in range(n)]
    for p in perimeter:
        uprights.append(((p.x, p.y, zb), (p.x, p.y, zt)))
    for j in range(1, 7):
        x = lerp(x0, x1, j / 7)
        uprights.append(((x, y0 + 0.004, zb), (x, y1 - 0.004, zb)))
    for j in range(1, 8):
        y = lerp(y0, y1, j / 8)
        uprights.append(((x0 + 0.004, y, zb), (x1 - 0.004, y, zb)))
    rods("Basket_Wires", uprights, 0.0025, wire, basket, sides=6)

    # Struts down to the front axle, clamps to the handlebar
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        rod(f"Basket_Strut_{s}", (x1 - 0.03, 0.10 * side, zb + 0.005), FRONT + Vector((0, 0.07 * side, 0)),
            0.004, wire, basket)
        rod(f"Basket_Bracket_{s}", (x0 + 0.005, 0.05 * side, zt - 0.01),
            BAR_CENTER + Vector((-0.005, 0.05 * side, 0)), 0.005, wire, basket)

    # A catch of fish, heads down, tails poking out
    for i, (loc, rot, scale) in enumerate([
        ((0.50, -0.06, 0.90), (math.radians(8), math.radians(62), math.radians(15)), 1.0),
        ((0.585, 0.055, 0.905), (math.radians(-12), math.radians(68), math.radians(170)), 1.08),
        ((0.60, -0.075, 0.87), (math.radians(20), math.radians(78), math.radians(95)), 0.9),
    ]):
        build_fish(f"Fish_{i + 1}", loc, rot, scale, basket, mats)


def build_fish(name, location, rotation, scale, parent, mats):
    body = loft(name, [(-0.115, 0, 0), (-0.06, 0, 0.002), (0.02, 0, 0.004), (0.095, 0, 0), (0.125, 0, -0.004)],
                half_w=lambda t: 0.005 + 0.019 * math.sin(math.pi * t ** 0.8) ** 0.9,
                half_h=lambda t: 0.007 + 0.036 * math.sin(math.pi * t ** 0.85) ** 0.9,
                side=(0, 1, 0), mats=[mats["fish"]], parent=parent, samples=24, ring_verts=20)
    body.location = location
    body.rotation_euler = rotation
    body.scale = (scale, scale, scale)
    flat_shape(f"{name}_Tail", [(-0.105, 0, 0), (-0.175, 0, 0.05), (-0.152, 0, 0), (-0.175, 0, -0.05)],
               0.004, mats["fin"], body)
    flat_shape(f"{name}_Dorsal", [(-0.045, 0, 0.035), (0.035, 0, 0.038), (-0.03, 0, 0.068)],
               0.003, mats["fin"], body)
    for side in (-1, 1):
        ellipsoid(f"{name}_Eye_{'R' if side < 0 else 'L'}", (0.093, 0.013 * side, 0.008), (0.012, 0.006, 0.012),
                  mats["eye"], body, segments=12)
    return body


# ---------------------------------------------------------------------------
# Pelican (American white pelican: white plumage, black flight feathers,
# orange bill, pouch and feet)
# ---------------------------------------------------------------------------

BODY_CENTER = Vector((-0.13, 0, 1.195))
BODY_PITCH = math.radians(28)           # chest raised, leaning toward the bars
HEAD_CENTER = Vector((0.19, 0, 1.79))
BILL_PITCH = math.radians(15)
BILL_LEN = 0.43
NECK_BASE = Vector((0.12, 0, 1.36))
HIP = Vector((-0.07, 0.11, 1.0))        # left hip; the right mirrors y
THIGH_LEN, SHIN_LEN = 0.41, 0.48         # long enough to reach the pedal at the bottom of its stroke


def build_pelican(mats):
    bird = empty("Pelican")
    white, dark = mats["feathers"], mats["flight_feathers"]

    body = ellipsoid("Pelican_Body", BODY_CENTER, (0.78, 0.40, 0.44), white, bird, segments=48)
    body.rotation_euler = (0, -BODY_PITCH, 0)
    chest = ellipsoid("Pelican_Chest", (0.12, 0, 1.36), (0.22, 0.24, 0.26), white, bird)
    chest.rotation_euler = (0, -math.radians(40), 0)
    loft("Pelican_Tail", [(-0.44, 0, 1.03), (-0.55, 0, 0.99), (-0.64, 0, 0.955), (-0.68, 0, 0.945)],
         half_w=lambda t: lerp(0.12, 0.075, t), half_h=lambda t: lerp(0.035, 0.008, t),
         side=(0, 1, 0), mats=[white], parent=bird, samples=16)

    # S-curved neck, head, crest tuft
    tube("Pelican_Neck", [(0.10, 0, 1.33), (0.18, 0, 1.46), (0.15, 0, 1.59), (0.13, 0, 1.69), (0.18, 0, 1.77)],
         0.058, white, bird, taper_end=0.78)
    head = ellipsoid("Pelican_Head", HEAD_CENTER, (0.17, 0.115, 0.13), white, bird)
    head.rotation_euler = (0, math.radians(10), 0)
    loft("Pelican_Crest", [(0.16, 0, 1.845), (0.125, 0, 1.865), (0.09, 0, 1.858)],
         half_w=lambda t: lerp(0.024, 0.007, t), half_h=lambda t: lerp(0.015, 0.005, t),
         side=(0, 1, 0), mats=[mats["crest"]], parent=bird, samples=12, ring_verts=12)
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        ellipsoid(f"Pelican_Eye_Ring_{s}", (0.228, 0.049 * side, 1.81), (0.032, 0.012, 0.028),
                  mats["eye_ring"], bird, segments=20)
        ellipsoid(f"Pelican_Eye_{s}", (0.23, 0.054 * side, 1.81), (0.017, 0.01, 0.017), mats["eye"], bird,
                  segments=16)

    build_bill(bird, mats)

    # Wings: broad white coverts arc from the shoulder down to the grips, with a fringe of
    # black flight feathers along the trailing (lower/rear) edge.
    trail = Vector((-0.45, 0, -0.9)).normalized()

    def wing_w(t):
        return lerp(0.07, 0.13, t / 0.2) if t < 0.2 else lerp(0.13, 0.05, (t - 0.2) / 0.8)

    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        wing_up = (0, side, 0)
        wing_ctrl = [(-0.14, 0.165 * side, 1.31), (0.03, 0.215 * side, 1.30), (0.14, 0.25 * side, 1.15),
                     (0.20, 0.245 * side, 1.02), (0.25, 0.225 * side, 0.95)]
        loft(f"Pelican_Wing_{s}", wing_ctrl, wing_w, lambda t: lerp(0.032, 0.018, t), up=wing_up,
             mats=[white, dark], parent=bird, samples=40, ring_verts=24,
             mat_fn=lambda t, d: 1 if d.dot(trail) > 0.4 or t > 0.9 else 0)

        frames = path_frames(wing_ctrl, 40, up=wing_up)
        count = 13
        for k in range(count):
            u = lerp(0.08, 0.82, k / (count - 1))
            c, tangent, sv, nv = frames[round(u * (len(frames) - 1))]
            edge = sv if sv.dot(trail) > 0 else -sv
            base = c + edge * wing_w(u) * 0.7
            sweep = (edge * 0.7 + Vector((-0.6, 0, -0.25)).normalized() * 0.5).normalized()
            tip = base + sweep * lerp(0.15, 0.10, u) * (1.0 - 0.12 * (k % 2))
            loft(f"Pelican_Secondary_{s}_{k + 1}", [base, tip], half_w=lambda t: lerp(0.03, 0.012, t ** 1.4),
                 half_h=0.005, side=tangent, mats=[dark], parent=bird, samples=8, ring_verts=10)

        # Primaries curl over and around the grip like fingers
        g_in, g_out = mirror_y(GRIP_IN, side), mirror_y(GRIP_OUT, side)
        for k, u in enumerate((0.12, 0.37, 0.62, 0.87)):
            g = g_in + (g_out - g_in) * u
            reach = 1.0 - 0.12 * abs(k - 1.5)
            wrap = [g + Vector((-0.10, 0, 0.06)), g + Vector((-0.045, 0, 0.031)), g + Vector((0, 0, 0.027)),
                    g + Vector((0.025 * reach, 0, 0.004)), g + Vector((0.013 * reach, 0, -0.021 * reach)),
                    g + Vector((-0.008, 0, -0.027 * reach))]
            loft(f"Pelican_Primary_{s}_{k + 1}", wrap, half_w=lambda t: lerp(0.013, 0.006, t ** 1.5),
                 half_h=0.0045, side=(0, 1, 0), mats=[dark], parent=bird, samples=24, ring_verts=12)

    # Head and neck turn together about the base of the neck
    head_parts = [o for o in bird.children if o.name.startswith(
        ("Pelican_Neck", "Pelican_Head", "Pelican_Crest", "Pelican_Eye", "Pelican_Bill", "Pelican_Pouch",
         "Pelican_Mandible"))]
    adopt(head_parts, pivot("Pelican_Head_Pivot", NECK_BASE, bird))

    # Legs pedal: the thigh swings from the hip, the shin from the knee, and each webbed foot rides
    # its pedal. pose_ride() re-solves the two-bone IK for any crank angle.
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        hip, knee, ankle, heel = leg_points(side, 0.0)
        # Feathered drumstick high up, bare orange skin below
        thigh = [tube(f"Pelican_Thigh_{s}", [hip, hip.lerp(knee, 0.3), hip.lerp(knee, 0.58)], 0.052, white, bird,
                      taper_end=0.62),
                 tube(f"Pelican_Lower_Thigh_{s}", [hip.lerp(knee, 0.45), knee], 0.026, mats["skin"], bird,
                      taper_end=0.95)]
        shin = [ellipsoid(f"Pelican_Knee_{s}", knee, (0.05, 0.05, 0.05), mats["skin"], bird, segments=20),
                tube(f"Pelican_Shin_{s}", [knee, knee.lerp(ankle, 0.5), ankle], 0.022, mats["skin"], bird,
                     taper_end=0.8),
                ellipsoid(f"Pelican_Ankle_{s}", ankle, (0.036, 0.036, 0.036), mats["skin"], bird, segments=16)]
        hip_pivot = adopt(thigh, pivot(f"Pelican_Hip_{s}", hip, bird))
        adopt(shin, pivot(f"Pelican_Knee_Pivot_{s}", knee, hip_pivot))
        foot = build_foot(f"Pelican_Foot_{s}", heel, side, bird, mats)
        pedal = bpy.data.objects.get(f"Pedal_Pivot_{s}")
        if pedal is not None:
            adopt([foot], pedal)
    return bird


def leg_points(side, crank_rot):
    """Hip, knee, ankle and heel for a crank turned crank_rot from rest (bike space)."""
    p = pedal_center(side, crank_rot)
    heel = Vector((p.x - 0.035, 0.12 * side, p.z + 0.011 + 0.004))
    ankle = heel + Vector((0.005, 0, 0.022))
    hip = Vector((HIP.x, HIP.y * side, HIP.z))
    return hip, knee_point(hip, ankle, THIGH_LEN, SHIN_LEN), ankle, heel


def pose_ride(crank_rot, wheel_rot, head_yaw=0.0, head_pitch=0.0, frame=None):
    """Pose the rig: wheels rolled wheel_rot, cranks turned crank_rot (both radians forward), legs
    following the pedals, head turned. With `frame`, keyframes the pose there."""
    def xz_angle(v):
        return math.atan2(v.z, v.x)

    def key(obj, value, axis=1):
        obj.rotation_euler[axis] = value
        if frame is not None:
            obj.keyframe_insert("rotation_euler", index=axis, frame=frame)

    objs = bpy.data.objects
    for name in ("Rear_Wheel_Spin", "Front_Wheel_Spin"):
        key(objs[name], wheel_rot)
    key(objs["Crank"], crank_rot)
    for side in (-1, 1):
        s = "R" if side < 0 else "L"
        key(objs[f"Pedal_Pivot_{s}"], -crank_rot)
        hip, knee0, ankle0, _ = leg_points(side, 0.0)
        _, knee, ankle, _ = leg_points(side, crank_rot)
        hip_turn = xz_angle(knee0 - hip) - xz_angle(knee - hip)     # +Y rotation lowers the XZ angle
        key(objs[f"Pelican_Hip_{s}"], hip_turn)
        key(objs[f"Pelican_Knee_Pivot_{s}"], xz_angle(ankle0 - knee0) - xz_angle(ankle - knee) - hip_turn)
    key(objs["Pelican_Head_Pivot"], head_pitch, axis=1)
    key(objs["Pelican_Head_Pivot"], head_yaw, axis=2)


def build_bill(bird, mats):
    base = HEAD_CENTER + Vector((0.07, 0, -0.01))
    fwd = Vector((math.cos(BILL_PITCH), 0, -math.sin(BILL_PITCH)))
    up = Vector((math.sin(BILL_PITCH), 0, math.cos(BILL_PITCH)))

    # Upper mandible: long and flat, ending in a downturned hook
    upper = [base - fwd * 0.03, base + fwd * 0.14, base + fwd * 0.28, base + fwd * (BILL_LEN - 0.04),
             base + fwd * (BILL_LEN - 0.005) - up * 0.012, base + fwd * BILL_LEN - up * 0.032]

    def upper_w(t):
        return lerp(0.036, 0.019, t / 0.8) if t < 0.8 else lerp(0.019, 0.006, (t - 0.8) / 0.2)

    def upper_h(t):
        return lerp(0.017, 0.011, t / 0.8) if t < 0.8 else lerp(0.011, 0.005, (t - 0.8) / 0.2)

    loft("Pelican_Bill_Upper", upper, upper_w, upper_h, side=(0, 1, 0), mats=[mats["bill"]], parent=bird,
         samples=40, ring_verts=20)

    # Throat pouch: hangs from the lower mandible, deepest a third of the way along
    pouch_ctrl = [base - fwd * 0.12 - up * 0.03, base - fwd * 0.02 - up * 0.012, base + fwd * 0.14 - up * 0.01,
                  base + fwd * 0.28 - up * 0.01, base + fwd * (BILL_LEN - 0.035) - up * 0.012]

    def pouch_depth(t):
        return 0.012 + 0.085 * math.sin(math.pi * t ** 0.75)

    def pouch_w(t):
        return lerp(0.033, 0.017, t)

    loft("Pelican_Pouch", pouch_ctrl, pouch_w, lambda t: pouch_depth(t) / 2 + 0.004, side=(0, 1, 0),
         offset=lambda t: pouch_depth(t) / 2, mats=[mats["pouch"]], parent=bird, samples=36, ring_verts=24)
    for side in (-1, 1):
        edge = [Vector(p) + Vector((0, pouch_w(j / (len(pouch_ctrl) - 1)) * 0.95 * side, 0))
                for j, p in enumerate(pouch_ctrl[1:], start=1)]
        tube(f"Pelican_Mandible_{'R' if side < 0 else 'L'}", edge, 0.0055, mats["bill"], bird, taper_end=0.7)


def build_foot(name, heel, side, bird, mats):
    """Totipalmate foot: four toes joined by webbing, toes forward, resting on the pedal."""
    foot = empty(name, heel, bird)
    foot.rotation_euler = (0, 0, math.radians(-6 * side))
    toes = [(-36, 0.10), (-12, 0.13), (12, 0.125), (36, 0.09)]   # inner (hallux side) toward the bike
    tips = [Vector((length * math.cos(math.radians(a)), -side * length * math.sin(math.radians(a)), 0))
            for a, length in toes]
    outline = [Vector((-0.02, 0, 0)), Vector((0.01, 0.026 * side, 0))]
    for i, tip in enumerate(tips):
        outline.append(tip)
        if i < len(tips) - 1:
            mid = math.radians((toes[i][0] + toes[i + 1][0]) / 2)
            length = min(toes[i][1], toes[i + 1][1]) * 0.72
            outline.append(Vector((length * math.cos(mid), -side * length * math.sin(mid), 0)))
    outline.append(Vector((0.01, -0.026 * side, 0)))
    if side > 0:
        outline.reverse()
    web = flat_shape(f"{name}_Web", outline, 0.007, mats["skin"], foot)
    smooth(web)
    for i, tip in enumerate(tips):
        tube(f"{name}_Toe_{i + 1}", [Vector((0.005, 0, 0.006)), tip * 0.5 + Vector((0, 0, 0.007)),
                                    tip * 0.97 + Vector((0, 0, 0.004))], 0.0075, mats["skin"], foot, taper_end=0.6)
        d = tip.normalized()
        rod(f"{name}_Claw_{i + 1}", tip * 0.97 + Vector((0, 0, 0.003)), tip + d * 0.012 + Vector((0, 0, -0.004)),
            0.0035, mats["claw"], foot, segments=8)
    return foot


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def build_environment(mats):
    env = empty("Environment")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=40)
    grass = mesh_object("Ground", bm, mats["grass"], env)
    grass.location.z = -0.01

    road = box("Road", (0, 1.0, -0.004), (60, 4.8, 0.008), mats["asphalt"], env)

    bm = bmesh.new()
    rects = [(-30 + 3.0 * i, -30 + 3.0 * i + 1.5, 0.94, 1.06) for i in range(20)]
    rects += [(-30, 30, -1.30, -1.20), (-30, 30, 3.20, 3.30)]
    for x0, x1, y0, y1 in rects:
        vs = [bm.verts.new((x, y, 0.001)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        bm.faces.new(vs)
    mesh_object("Road_Markings", bm, mats["paint_line"], env)

    sky_gradient(horizon=(0.55, 0.7, 0.93), zenith=(0.16, 0.36, 0.8), strength=0.9)
    sun = link(bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN")))
    sun.data.energy = 3.5
    sun.data.angle = math.radians(4)
    sun.data.color = (1.0, 0.96, 0.9)
    sun.location = (4, -3, 6)
    look_at(sun, (0, 0, 0.8))
    return env


def make_materials():
    return {
        "paint": material("Frame_Paint", (0.02, 0.30, 0.36), roughness=0.25, metallic=0.3, Coat_Weight=0.6),
        "chrome": material("Chrome", (0.86, 0.86, 0.87), roughness=0.12, metallic=1.0),
        "alu": material("Aluminum", (0.78, 0.78, 0.8), roughness=0.3, metallic=1.0),
        "steel": material("Steel", (0.45, 0.45, 0.47), roughness=0.35, metallic=1.0),
        "chain": material("Chain", (0.22, 0.22, 0.24), roughness=0.4, metallic=1.0),
        "rubber": material("Rubber", (0.035, 0.035, 0.037), roughness=0.85),
        "leather": material("Leather", (0.28, 0.13, 0.06), roughness=0.45),
        "wire": material("Basket_Wire", (0.72, 0.72, 0.74), roughness=0.3, metallic=1.0),
        "fish": material("Fish_Scales", (0.42, 0.52, 0.6), roughness=0.25, metallic=0.6),
        "fin": material("Fish_Fin", (0.3, 0.38, 0.45), roughness=0.4, metallic=0.3),
        "eye": material("Eye", (0.03, 0.025, 0.02), roughness=0.05),
        "feathers": noise_bump(material("Feathers", (0.88, 0.87, 0.84), roughness=0.75), 35, 0.15),
        "flight_feathers": noise_bump(material("Flight_Feathers", (0.05, 0.05, 0.055), roughness=0.6), 35, 0.2),
        "crest": material("Crest", (0.93, 0.86, 0.62), roughness=0.75),
        "bill": material("Bill", (0.92, 0.36, 0.04), roughness=0.35),
        "pouch": material("Pouch", (0.9, 0.3, 0.12), roughness=0.4, Subsurface_Weight=0.15),
        "skin": material("Pelican_Skin", (0.92, 0.34, 0.04), roughness=0.5),
        "eye_ring": material("Eye_Ring", (0.95, 0.66, 0.08), roughness=0.4),
        "claw": material("Claw", (0.25, 0.22, 0.2), roughness=0.4),
        "asphalt": noise_bump(material("Asphalt", (0.11, 0.11, 0.12), roughness=0.9), 400, 0.3, 0.002),
        "paint_line": material("Road_Paint", (0.9, 0.88, 0.8), roughness=0.6),
        "grass": noise_color(material("Grass", (0.2, 0.32, 0.1), roughness=0.95), 3.0,
                             (0.16, 0.27, 0.08), (0.28, 0.38, 0.12)),
    }


def build():
    mats = make_materials()
    build_bicycle(mats)
    build_pelican(mats)
    build_environment(mats)
    camera(location=(2.55, -3.35, 1.2), target=(0.03, 0, 0.95), lens_mm=40)
    render_settings()
    bpy.context.scene.eevee.taa_render_samples = 64


if __name__ == "__main__":
    args = parse_args()
    reset_scene()
    build()
    save(args.out)
