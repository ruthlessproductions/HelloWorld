"""The pelican on its bicycle, riding the reconstructed arena deck inside the Colosseum.

Run (the pelican and bike come from ../pelican_bicycle/build.py):
  "$BLENDER" --background --factory-startup --python scenes/colosseum/build.py -- --out scenes/colosseum

Writes <out>/colosseum.blend. Every run starts from an empty scene, so the script is the
single source of truth: to change the scene, edit this file and run it again.

Axes: +X is the long (east-west) axis with east at +X, +Y is north, the arena floor is z=0.
Rings are offsets `d` meters outward from the arena edge (negative d is inside the arena).
"""

import argparse
import importlib.util
import math
import os
import random
import sys

import bpy
import bmesh  # after bpy: the pip "bpy" module only exposes bmesh once bpy is loaded
from mathutils import Matrix, Vector

NAME = "colosseum"


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
# The pelican and bike, reused from the pelican_bicycle scene
# ---------------------------------------------------------------------------

def load_pelican_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pelican_bicycle", "build.py")
    spec = importlib.util.spec_from_file_location("pelican_bicycle_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PB = load_pelican_module()
lerp = PB.lerp


def load_raptor_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "raptor", "build.py")
    spec = importlib.util.spec_from_file_location("raptor_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RAP = load_raptor_module()


# ---------------------------------------------------------------------------
# Plan (meters)
# ---------------------------------------------------------------------------

ARENA_A, ARENA_B = 43.5, 27.5      # arena semi-axes: 87 x 55
OUTER_D = 51.0                     # outer wall offset: 189 x 156 overall
HYPO_D = -5.5                      # hypogeum edge: 76 x 44
HYPO_FLOOR = -6.0

# Cross-section, fitted to the reference photo: podium, steep lower seating up to the visitor
# walkway on the second order, the ring III arcade above it, upper seating up to ring II.
PODIUM_Z = 5.0
LOWER_D = (4.0, 15.0)              # lower seating runs from the podium to the walkway
WALK_Z = 13.0
RING3_D = (19.0, 21.0)
ARCADE_TOP = 25.0
RING2_D = (42.5, 44.5)
UPPER_TOP = 38.0
DECK_X = 26.0                      # the reconstructed deck covers the arena east of this line


def ring_pt(d, theta, z=0.0):
    """Point on the ring `d` meters outside the arena edge, at parametric angle theta (0 = east)."""
    return Vector(((ARENA_A + d) * math.cos(theta), (ARENA_B + d) * math.sin(theta), z))


def ring_solid(name, d0, d1, z_top0, z_top1, z_bottom=0.0, theta0=0.0, theta1=2 * math.pi, segments=240,
               mat=None, parent=None, top_fn=None):
    """Solid between ring offsets d0 and d1 over an angle range. The top runs from z_top0 at d0 to
    z_top1 at d1 (a slope for seating); top_fn(theta) returns how far ruin damage lowers it."""
    full = abs(theta1 - theta0 - 2 * math.pi) < 1e-6
    n = segments if full else max(2, round(segments * (theta1 - theta0) / (2 * math.pi)))
    bm = bmesh.new()
    sections = []
    for k in range(n if full else n + 1):
        th = theta0 + (theta1 - theta0) * k / n
        drop = top_fn(th) if top_fn else 0.0
        sections.append([bm.verts.new(v) for v in (
            ring_pt(d0, th, z_bottom), ring_pt(d1, th, z_bottom),
            ring_pt(d1, th, max(z_bottom + 0.05, z_top1 - drop)),
            ring_pt(d0, th, max(z_bottom + 0.05, z_top0 - drop)))])
    count = len(sections)
    for k in range(count if full else count - 1):
        a, b = sections[k], sections[(k + 1) % count]
        for j in range(4):
            bm.faces.new((a[j], a[(j + 1) % 4], b[(j + 1) % 4], b[j]))
    if not full:
        bm.faces.new(sections[0])
        bm.faces.new(list(reversed(sections[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return mesh_object(name, bm, mat, parent)


def ellipse_slab(name, d, z_top, thickness, mat=None, parent=None, x_min=None, segments=160):
    """Flat elliptical slab at ring offset d, optionally cut by a straight edge at x = x_min."""
    alpha = math.acos(x_min / (ARENA_A + d)) if x_min is not None else math.pi
    bm = bmesh.new()
    pts = [ring_pt(d, -alpha + 2 * alpha * k / segments, z_top) for k in range(segments + (1 if x_min else 0))]
    bm.faces.new([bm.verts.new(p) for p in pts])
    obj = mesh_object(name, bm, mat, parent)
    mod = obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = thickness
    mod.offset = -1.0
    return obj


def named_camera(name, location, target, lens_mm):
    data = bpy.data.cameras.new(name)
    data.lens = lens_mm
    data.clip_end = 1000
    cam = link(bpy.data.objects.new(name, data))
    cam.location = location
    look_at(cam, target)
    return cam


def bay_frame(d, th0, th1, overlap=0.1):
    """Local frame for one wall bay on ring d: u along the wall, w outward, v up."""
    p0, p1 = ring_pt(d, th0), ring_pt(d, th1)
    eu = (p1 - p0).normalized()
    ew = Vector((eu.y, -eu.x, 0.0))
    origin = p0 - eu * overlap / 2

    def to_world(u, w, v):
        return origin + eu * u + ew * w + Vector((0, 0, v))
    return to_world, (p1 - p0).length + overlap


def local_box(bm, to_world, u0, u1, w0, w1, v0, v1):
    corners = [(u0, w0, v0), (u1, w0, v0), (u1, w1, v0), (u0, w1, v0),
               (u0, w0, v1), (u1, w0, v1), (u1, w1, v1), (u0, w1, v1)]
    vs = [bm.verts.new(to_world(*c)) for c in corners]
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([vs[i] for i in f])


def arch_bay(bm, to_world, length, z0, z1, thick, opening=0.6, spring=0.45, segs=8):
    """Wall bay with a round-arched opening. Rays from the arch center to the bay outline make
    voussoir-like quads, so the face needs no triangulation."""
    ow = length * opening
    uc, r = length / 2, ow / 2
    ul, ur = uc - r, uc + r
    hs = min(z0 + (z1 - z0) * spring, z1 - 0.35 * (z1 - z0) * 0.3 - r)
    angles = {round(math.pi * (1 - k / segs), 9) for k in range(segs + 1)}
    angles |= {round(math.atan2(z1 - hs, -uc), 9), round(math.atan2(z1 - hs, length - uc), 9)}
    angles = sorted(angles, reverse=True)

    def ray(a):
        c, s = math.cos(a), math.sin(a)
        hits = []
        if c < -1e-9:
            hits.append(-uc / c)
        if c > 1e-9:
            hits.append((length - uc) / c)
        if s > 1e-9:
            hits.append((z1 - hs) / s)
        t = min(hits)
        return (uc + c * t, hs + s * t)

    inner = [(ul, z0)] + [(uc + r * math.cos(a), hs + r * math.sin(a)) for a in angles] + [(ur, z0)]
    outer = [(0.0, z0)] + [ray(a) for a in angles] + [(length, z0)]
    sides = {}
    for w in (thick / 2, -thick / 2):
        sides[w] = ([bm.verts.new(to_world(u, w, v)) for u, v in inner],
                    [bm.verts.new(to_world(u, w, v)) for u, v in outer])
    (fi, fo), (bi, bo) = sides[thick / 2], sides[-thick / 2]
    for k in range(len(inner) - 1):
        bm.faces.new((fi[k], fi[k + 1], fo[k + 1], fo[k]))
        bm.faces.new((bo[k], bo[k + 1], bi[k + 1], bi[k]))
        bm.faces.new((fi[k + 1], fi[k], bi[k], bi[k + 1]))
        (u0, v0), (u1, v1) = outer[k], outer[k + 1]
        if (abs(v0 - z1) < 1e-6 and abs(v1 - z1) < 1e-6) or (abs(u0) < 1e-6 and abs(u1) < 1e-6) \
                or (abs(u0 - length) < 1e-6 and abs(u1 - length) < 1e-6):
            bm.faces.new((fo[k], fo[k + 1], bo[k + 1], bo[k]))


def window_bay(bm, to_world, length, z0, z1, thick, width=0.3, sill=0.35, head=0.62):
    """Wall bay with a rectangular window, built from four blocks."""
    h, t = z1 - z0, thick / 2
    u0, u1 = length * (0.5 - width / 2), length * (0.5 + width / 2)
    vb, vt = z0 + h * sill, z0 + h * head
    local_box(bm, to_world, 0, length, -t, t, z0, vb)
    local_box(bm, to_world, 0, length, -t, t, vt, z1)
    local_box(bm, to_world, 0, u0, -t, t, vb, vt)
    local_box(bm, to_world, u1, length, -t, t, vb, vt)


def arcade_wall(name, d, thick, stories, mat, parent, theta0=0.0, theta1=2 * math.pi, bays=80, limit_fn=None,
                rng=None):
    """Ring wall of stacked stories, each a list of (z0, z1, kind) with kind "arch", "window" or "solid".
    limit_fn(i, theta) caps a bay's height: stories above it are gone, and the story it cuts through
    is left as broken piers."""
    rng = rng or random.Random(1)
    bm = bmesh.new()
    step = 2 * math.pi / bays
    for i in range(bays):
        th0, th1 = i * step, (i + 1) * step
        if th0 < theta0 - 1e-9 or th1 > theta1 + 1e-9:
            continue
        to_world, length = bay_frame(d, th0, th1)
        limit = limit_fn(i, (th0 + th1) / 2) if limit_fn else float("inf")
        for z0, z1, kind in stories:
            if z0 >= limit - 0.3:
                break
            if z1 <= limit:
                if kind == "arch":
                    arch_bay(bm, to_world, length, z0, z1, thick)
                elif kind == "window":
                    window_bay(bm, to_world, length, z0, z1, thick)
                else:
                    local_box(bm, to_world, 0, length, -thick / 2, thick / 2, z0, z1)
            else:
                pier = length * 0.2
                for u0, u1 in ((0, pier), (length - pier, length)):
                    top = rng.uniform(z0 + 0.35 * (limit - z0), limit)
                    local_box(bm, to_world, u0, u1, -thick / 2, thick / 2, z0, top)
                break
    obj = mesh_object(name, bm, mat, parent)
    return obj


def radial_walls(name, d0, d1, z_bottom, top_fn, thick, mat, parent, skip=(), bays=80, pieces=3, drop_fn=None):
    """The walls that radiate under the seating, one per bay line, with a sloped top. drop_fn(i, piece)
    lowers each piece for ruin damage."""
    bm = bmesh.new()
    for i in range(bays):
        if i in skip:
            continue
        th = 2 * math.pi * i / bays
        for k in range(pieces):
            da, db = lerp(d0, d1, k / pieces), lerp(d0, d1, (k + 1) / pieces)
            a, b = ring_pt(da, th), ring_pt(db, th)
            along = (b - a).normalized()
            side = Vector((-along.y, along.x, 0)) * thick / 2
            drop = drop_fn(i, k) if drop_fn else 0.0
            ta, tb = max(z_bottom + 0.4, top_fn(da) - drop), max(z_bottom + 0.4, top_fn(db) - drop)
            vs = [bm.verts.new(v) for v in (
                a - side + Vector((0, 0, z_bottom)), b - side + Vector((0, 0, z_bottom)),
                b + side + Vector((0, 0, z_bottom)), a + side + Vector((0, 0, z_bottom)),
                a - side + Vector((0, 0, ta)), b - side + Vector((0, 0, tb)),
                b + side + Vector((0, 0, tb)), a + side + Vector((0, 0, ta)))]
            for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                bm.faces.new([vs[j] for j in f])
    return mesh_object(name, bm, mat, parent)


def seating_vaults(name, d0, d1, top_fn, mat, parent, bays_fn, bays=80, rise=0.28, thick=0.45):
    """Sloped barrel vaults between neighbouring radial walls: the ribbed ramps left where the
    seats have gone. bays_fn(i) returns the (start, end) fraction of the run still standing, or None."""
    bm = bmesh.new()
    nd, na = 8, 8
    for i in range(bays):
        span = bays_fn(i)
        if span is None:
            continue
        th0, th1 = 2 * math.pi * i / bays, 2 * math.pi * (i + 1) / bays
        rows = []
        for j in range(nd + 1):
            d = lerp(lerp(d0, d1, span[0]), lerp(d0, d1, span[1]), j / nd)
            a, b = ring_pt(d, th0), ring_pt(d, th1)
            w = (b - a).length
            crown = top_fn(d) - 0.1
            rows.append([bm.verts.new(a.lerp(b, s) + Vector((0, 0, crown - rise * w + rise * w * math.sin(math.pi * s))))
                         for s in (k / na for k in range(na + 1))])
        for j in range(nd):
            for k in range(na):
                bm.faces.new((rows[j][k], rows[j][k + 1], rows[j + 1][k + 1], rows[j + 1][k]))
    obj = mesh_object(name, bm, mat, parent)
    mod = obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = thick
    return obj


def ring_railing(name, d, z, mat, parent, gaps=(), step_deg=2.0):
    """Visitor railing along a ring, broken at the axial entrances (gaps are angle ranges in degrees)."""
    def open_at(deg):
        return any(g0 <= deg % 360 <= g1 for g0, g1 in gaps)
    runs, run, posts = [], [], []
    for k in range(int(360 / step_deg) + 1):
        deg = k * step_deg
        if open_at(deg):
            if len(run) > 1:
                runs.append(run)
            run = []
            continue
        p = ring_pt(d, math.radians(deg), z)
        run.append(p)
        if k % 2 == 0:
            posts.append((p - Vector((0, 0, 1.05)), p))
    if len(run) > 1:
        runs.append(run)
    for n, pts in enumerate(runs):
        PB.poly_tube(f"{name}_Rail_{n + 1}", [tuple(p) for p in pts], 0.03, mat, parent)
    return PB.rods(f"{name}_Posts", posts, 0.025, mat, parent, sides=6)


# ---------------------------------------------------------------------------
# Colosseum
# ---------------------------------------------------------------------------

EAST_GATE = (79, 0)                # bays left open for the axial entrances
WEST_GATE = (39, 40)
GATES = set(EAST_GATE + WEST_GATE)
GATE_HEIGHT = 3.6
GATE_DEG = ((355.5, 360.0), (0.0, 4.5), (175.5, 184.5))


def lower_seat_z(d):
    return lerp(PODIUM_Z, WALK_Z, (d - LOWER_D[0]) / (LOWER_D[1] - LOWER_D[0]))


def upper_seat_z(d):
    return lerp(ARCADE_TOP, UPPER_TOP, (d - RING3_D[1]) / (RING2_D[0] - RING3_D[1]))


def gate_arcs(gap=math.radians(4.5)):
    """The two arcs of a ring between the east and west entrances."""
    return ((gap, math.pi - gap), (math.pi + gap, 2 * math.pi - gap))


def build_colosseum(mats):
    col = empty("Colosseum")
    trav, brick, dirt = mats["travertine"], mats["brick"], mats["dirt"]
    rng = random.Random(7)

    # Arena: podium wall, perimeter ground, hypogeum, reconstructed deck at the east end
    arena = empty("Arena", parent=col)
    for k, (a0, a1) in enumerate(gate_arcs()):
        ring_solid(f"Podium_Wall_{k + 1}", 0.0, 1.2, PODIUM_Z - 0.35, PODIUM_Z - 0.35, HYPO_FLOOR, a0, a1,
                   mat=brick, parent=arena)
    ring_solid("Podium_Cap", -0.1, 1.3, PODIUM_Z, PODIUM_Z, PODIUM_Z - 0.35, mat=trav, parent=arena)
    # The axial gates are tunnels under the podium and the lower seats
    for name, center in (("East", 0.0), ("West", math.pi)):
        a0, a1 = center - math.radians(4.5), center + math.radians(4.5)
        ring_solid(f"Gate_{name}_Lintel", -0.05, LOWER_D[0], PODIUM_Z - 0.35, PODIUM_Z - 0.35, GATE_HEIGHT,
                   a0, a1, mat=brick, parent=arena)
        ring_solid(f"Gate_{name}_Seats", LOWER_D[0], LOWER_D[1], PODIUM_Z, WALK_Z, GATE_HEIGHT, a0, a1,
                   mat=brick, parent=arena)
    ring_solid("Arena_Perimeter", HYPO_D, 0.0, 0.0, 0.0, HYPO_FLOOR, mat=dirt, parent=arena)
    ellipse_slab("Hypogeum_Floor", HYPO_D, HYPO_FLOOR, 0.5, dirt, arena)
    hypo_rng = random.Random(11)
    for k, d in enumerate((-9.0, -12.5)):
        arcade_wall(f"Hypogeum_Curved_Wall_{k + 1}", d, 0.9, [(HYPO_FLOOR, -0.4, "arch")], brick, arena, bays=64,
                    limit_fn=lambda i, th: hypo_rng.uniform(-3.5, -0.8) if hypo_rng.random() < 0.45 else 99,
                    rng=hypo_rng)
    radial_walls("Hypogeum_Cross_Walls", -12.5, HYPO_D, HYPO_FLOOR, lambda d: -0.6, 0.8, brick, arena,
                 bays=64, pieces=2, drop_fn=lambda i, k: hypo_rng.uniform(0, 2.5) if i % 2 else 99)
    inner_a, inner_b = ARENA_A - 12.5, ARENA_B - 12.5
    bm = bmesh.new()
    for y in (-13.5, -10.5, -7.5, -4.5, -1.5, 1.5, 4.5, 7.5, 10.5, 13.5):
        half = inner_a * math.sqrt(max(0.0, 1 - (y / inner_b) ** 2)) - 0.3
        x = -half
        while x < half:
            seg = min(hypo_rng.uniform(5.0, 9.0), half - x)
            if hypo_rng.random() > 0.08:          # otherwise a doorway gap
                top = -hypo_rng.uniform(0.2, 1.0)
                to_world = lambda u, w, v, x=x, y=y: Vector((x + u, y + w, v))
                local_box(bm, to_world, 0, seg, -0.5, 0.5, HYPO_FLOOR, top)
            x += seg
    mesh_object("Hypogeum_Walls", bm, brick, arena)
    ellipse_slab("Arena_Deck", -0.2, 0.0, 0.4, mats["wood"], arena, x_min=DECK_X)
    posts = [((DECK_X + 0.1, y, 0), (DECK_X + 0.1, y, 1.1)) for y in [(-24 + 1.6 * k) for k in range(31)]]
    PB.rods("Deck_Railing_Posts", posts, 0.03, mats["iron"], arena, sides=6)
    for z in (0.55, 1.1):
        PB.rods(f"Deck_Railing_Rail_{z}", [((DECK_X + 0.1, -24.0, z), (DECK_X + 0.1, 24.0, z))], 0.028,
                mats["iron"], arena, sides=8)

    # Seating (cavea): podium terrace, lower seating on radial walls and vaults, visitor walkway,
    # the ring III arcade, and the ruined upper seating behind it
    cavea = empty("Cavea", parent=col)
    for k, (a0, a1) in enumerate(gate_arcs()):
        ring_solid(f"Podium_Terrace_{k + 1}", 1.2, LOWER_D[0], PODIUM_Z, PODIUM_Z, 0.0, a0, a1, mat=brick,
                   parent=cavea)
        ring_solid(f"Walkway_Second_Order_{k + 1}", LOWER_D[1], RING3_D[0], WALK_Z, WALK_Z, 0.0, a0, a1,
                   mat=trav, parent=cavea)
    ring_solid("Walkway_Gate_Bridges", LOWER_D[1], RING3_D[0], WALK_Z, WALK_Z, WALK_Z - 1.2, mat=trav, parent=cavea)
    for k, (a0, a1) in enumerate(gate_arcs()):
        ring_solid(f"Cavea_Lower_Floor_{k + 1}", LOWER_D[0], LOWER_D[1], 0.3, 0.3, 0.0, a0, a1, mat=dirt,
                   parent=cavea)
    for name, center in (("East", 0.0), ("West", math.pi)):
        ring_solid(f"Gate_{name}_Floor", 0.0, LOWER_D[1], 0.0, 0.0, -0.3, center - math.radians(4.5),
                   center + math.radians(4.5), mat=dirt, parent=cavea)
    radial_walls("Cavea_Lower_Walls", LOWER_D[0], LOWER_D[1] + 0.3, 0.0, lower_seat_z, 1.1, brick, cavea,
                 skip=GATES, drop_fn=lambda i, k: rng.choice((0, 0, 0, 0.6, 1.5)))
    ring_solid("Cavea_Lower_Ring", 9.2, 10.0, lower_seat_z(9.2) - 0.6, lower_seat_z(10.0) - 0.6, mat=brick,
               parent=cavea, top_fn=lambda th: 1.5 * max(0.0, math.sin(11 * th)))
    seating_vaults("Cavea_Lower_Vaults", LOWER_D[0], LOWER_D[1], lower_seat_z, brick, cavea,
                   bays_fn=lambda i: None if i in GATES or rng.random() < 0.3
                   else (rng.choice((0.0, 0.0, 0.35)), rng.choice((1.0, 1.0, 0.7))))
    ring_railing("Walkway_Railing", LOWER_D[1] + 0.25, WALK_Z + 1.05, mats["iron"], cavea, gaps=GATE_DEG)

    arcade_wall("Ring_III", (RING3_D[0] + RING3_D[1]) / 2, RING3_D[1] - RING3_D[0],
                [(0.0, WALK_Z, "solid"), (WALK_Z, ARCADE_TOP, "arch")], trav, cavea,
                limit_fn=lambda i, th: rng.uniform(19, 24) if rng.random() < 0.12 else 99, rng=rng)
    ring_solid("Gallery_Floor_Second_Order", RING3_D[1], RING2_D[0], WALK_Z, WALK_Z, WALK_Z - 0.6, mat=trav,
               parent=cavea)

    def north(th):
        return math.radians(20) < th < math.radians(170)

    radial_walls("Cavea_Upper_Walls", RING3_D[1], RING2_D[0], WALK_Z, upper_seat_z, 1.1, brick, cavea,
                 drop_fn=lambda i, k: rng.uniform(0, 3) if north(2 * math.pi * i / 80)
                 else rng.uniform(6, 14) + 3 * (2 - k))
    seating_vaults("Cavea_Upper_Vaults", RING3_D[1], RING2_D[0], upper_seat_z, brick, cavea,
                   bays_fn=lambda i: (rng.choice((0.0, 0.25)), 1.0)
                   if north(2 * math.pi * (i + 0.5) / 80) and rng.random() < 0.85 else None)

    # Outer structure: ring II all round (ruined on the south), full-height outer wall on the north
    shell = empty("Shell", parent=col)
    ring2_mid, ring2_t = (RING2_D[0] + RING2_D[1]) / 2, RING2_D[1] - RING2_D[0]
    arcade_wall("Ring_II", ring2_mid, ring2_t, [(0.0, 11.5, "arch"), (11.5, 24.0, "arch"), (24.0, UPPER_TOP, "window")],
                trav, shell, rng=rng,
                limit_fn=lambda i, th: 99 if north(th) else (rng.uniform(26, 33) if rng.random() < 0.3 else 99))
    outer_bays = [i for i in range(80) if math.radians(15) <= 2 * math.pi * i / 80 < math.radians(165)]

    def outer_limit(i, th):
        from_end = min(i - outer_bays[0], outer_bays[-1] - i)
        return (20.0, 33.0, 42.0)[from_end] if from_end < 3 else 99

    arcade_wall("Outer_Wall", OUTER_D - 1.0, 2.0,
                [(0.0, 11.5, "arch"), (11.5, 24.0, "arch"), (24.0, 35.5, "arch"), (35.5, 48.0, "window")],
                trav, shell, theta0=math.radians(15), theta1=math.radians(165), limit_fn=outer_limit, rng=rng)
    for z in (11.5, 24.0, 35.5):
        ring_solid(f"Outer_Gallery_Floor_{z:.0f}", RING2_D[1], OUTER_D - 2.0, z, z, z - 0.6,
                   math.radians(17), math.radians(163), mat=trav, parent=shell)

    # Surroundings: paving outside the monument
    ring_solid("Ground", OUTER_D - 1.0, 400.0, 0.0, 0.0, -0.1, mat=mats["ground"], parent=col, segments=120)
    return col


def build_rider(location, heading_deg):
    mats = PB.make_materials()
    rider = empty("Rider", location)
    rider.rotation_euler = (0, 0, math.radians(heading_deg))
    PB.build_bicycle(mats).parent = rider
    PB.build_pelican(mats).parent = rider
    return rider, mats


def build_thief(mats):
    """The raptor, with a fish from the pelican's basket in its jaws."""
    arm = RAP.build_raptor()
    # Clamped crosswise in the front teeth, head and tail sticking out either side
    fish = PB.build_fish("Stolen_Fish", (0.69, 0.0, 1.50), (math.radians(-10), 0, math.radians(90)), 1.35,
                         None, mats)
    bpy.context.view_layer.update()
    world = fish.matrix_world.copy()
    fish.parent, fish.parent_type, fish.parent_bone = arm, "BONE", "head"
    fish.matrix_world = world
    return arm


# ---------------------------------------------------------------------------
# Animation: a raptor has stolen a fish and bolts along the deck for the east gate, with the
# pelican pedalling hard behind it. The camera starts ahead of them looking back, lets the
# raptor run past, swings round to the pelican's profile, then pulls back as the raptor
# vanishes into the gate tunnel with the pelican close behind.
# ---------------------------------------------------------------------------

FPS, SECONDS = 24, 8
FRAMES = FPS * SECONDS
HEADING = math.radians(12)
SPEED = 2.05                           # m/s for both: pedalling hard, and a raptor's easy run
GAP = 4.5                              # meters the raptor leads by
PATH_START = Vector((27.0, -3.2, 0.0)) # the pelican starts against the west railing of the deck
TURN_AT, TURN_LEN = 13.0, 2.5          # the path straightens out for the gate tunnel here
HERO_AT = Vector((32.0, -2.0, 0.0))    # where the hero still (Camera_Hero) catches the rider
HERO_FRAME = 61


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def path_heading(s):
    return HEADING * (1 - smoothstep(TURN_AT, TURN_AT + TURN_LEN, s))


_PATH_STEP = 0.02
_PATH = [PATH_START.copy()]
for _k in range(int(40 / _PATH_STEP)):
    _h = path_heading((_k + 0.5) * _PATH_STEP)
    _PATH.append(_PATH[-1] + Vector((math.cos(_h), math.sin(_h), 0)) * _PATH_STEP)


def path_point(s):
    """Point `s` meters along the chase path."""
    k = min(int(s / _PATH_STEP), len(_PATH) - 2)
    return _PATH[k].lerp(_PATH[k + 1], s / _PATH_STEP - k)


def rider_s(frame):
    return SPEED * (frame - 1) / FPS


def rider_at(frame):
    return path_point(rider_s(frame))


def rel(frame, fwd, left, up):
    """Point relative to the rider at `frame`: meters forward, to its left, and up."""
    h = path_heading(rider_s(frame))
    forward, left_dir = Vector((math.cos(h), math.sin(h), 0)), Vector((-math.sin(h), math.cos(h), 0))
    return rider_at(frame) + forward * fwd + left_dir * left + Vector((0, 0, up))


def set_interpolation(kind):
    bpy.context.preferences.edit.keyframe_new_interpolation_type = kind


def animate_chase(rider, raptor):
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, FRAMES
    scene.render.fps = FPS

    # Rider travel, wheels, cranks and legs: keyed every frame, linear between frames
    set_interpolation("LINEAR")
    wheel_radius = PB.TIRE_R + PB.TIRE_TUBE
    for frame in range(1, FRAMES + 1):
        rider.location = rider_at(frame)
        rider.rotation_euler = (0, 0, path_heading(rider_s(frame)))
        rider.keyframe_insert("location", frame=frame)
        rider.keyframe_insert("rotation_euler", index=2, frame=frame)
        wheel_rot = rider_s(frame) / wheel_radius
        crank_rot = wheel_rot * PB.CHAIN_COG / 44
        head_pitch = 0.03 * math.sin(2 * crank_rot)       # a nod on each pedal stroke, eyes on the thief
        PB.pose_ride(crank_rot, wheel_rot, 0.0, head_pitch, frame=frame)

    # The raptor runs the same path, GAP meters ahead, at the same speed
    RAP.run_along(raptor, lambda t: path_point(GAP + SPEED * t), lambda t: path_heading(GAP + SPEED * t),
                  (1, FRAMES), FPS, SPEED)

    # Camera: a few eased keys; it aims at a target empty that leads the framing
    set_interpolation("BEZIER")
    data = bpy.data.cameras.new("Camera_Ride")
    data.clip_end = 1000
    cam = link(bpy.data.objects.new("Camera_Ride", data))
    target = empty("Camera_Ride_Target")
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    keys = [   # frame, camera, target (both relative to the rider), lens (mm)
        (1, rel(1, 8.5, -3.2, 1.2), rel(1, 2.5, 0.3, 1.2), 28),              # ahead, looking back at both
        (72, rel(72, 5.5, -3.6, 1.3), rel(72, 2.0, 0.3, 1.2), 26),           # the raptor runs past
        (105, rel(105, 0.5, -4.0, 1.4), rel(105, 1.5, 0.2, 1.1), 24),        # the pelican's profile
        (150, rel(150, -4.5, -3.0, 2.0), rel(150, 4.0, 0.5, 1.2), 20),       # behind: the raptor at the gate
        (FRAMES, rel(FRAMES, -12.0, -1.2, 3.0), rel(FRAMES, 16.0, 1.0, 3.5), 18),  # pull back
    ]
    for frame, cam_at, target_at, lens in keys:
        cam.location, target.location, data.lens = cam_at, target_at, lens
        cam.keyframe_insert("location", frame=frame)
        target.keyframe_insert("location", frame=frame)
        data.keyframe_insert("lens", frame=frame)
    scene.camera = cam

    scene.render.use_motion_blur = True
    scene.render.use_persistent_data = True     # keep the static arena between frames
    return cam


def weathered(name, color_a, color_b, blotch_scale, bump_scale, bump_distance):
    """Masonry-style material: blotchy two-tone color plus fine surface relief."""
    mat = material(name, color_a, roughness=0.9)
    PB.noise_color(mat, blotch_scale, color_a, color_b)
    return PB.noise_bump(mat, bump_scale, 0.35, bump_distance)


def planks(name, color_a, color_b, length=2.4, width=0.16):
    """Deck boards running along X: a brick pattern stretched into planks with dark seams."""
    mat = material(name, color_a, roughness=0.7)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    coords = nodes.new("ShaderNodeTexCoord")
    boards = nodes.new("ShaderNodeTexBrick")
    boards.offset = 0.37
    boards.inputs["Color1"].default_value = (*color_a, 1.0)
    boards.inputs["Color2"].default_value = (*color_b, 1.0)
    boards.inputs["Mortar"].default_value = (0.12, 0.09, 0.06, 1.0)
    boards.inputs["Scale"].default_value = 1.0
    boards.inputs["Mortar Size"].default_value = 0.006
    boards.inputs["Brick Width"].default_value = length
    boards.inputs["Row Height"].default_value = width
    links.new(coords.outputs["Object"], boards.inputs["Vector"])
    links.new(boards.outputs["Color"], bsdf.inputs["Base Color"])
    return PB.noise_bump(mat, 30.0, 0.2, 0.003)


def build():
    mats = {
        "travertine": weathered("Travertine", (0.66, 0.54, 0.4), (0.5, 0.4, 0.29), 0.35, 4.0, 0.05),
        "brick": weathered("Roman_Brick", (0.52, 0.28, 0.16), (0.38, 0.21, 0.13), 0.5, 12.0, 0.02),
        "dirt": weathered("Hypogeum_Dirt", (0.42, 0.33, 0.24), (0.32, 0.25, 0.18), 0.8, 6.0, 0.03),
        "wood": planks("Deck_Wood", (0.62, 0.47, 0.31), (0.5, 0.37, 0.24)),
        "ground": weathered("Paving", (0.5, 0.47, 0.42), (0.4, 0.38, 0.34), 0.5, 8.0, 0.01),
        "iron": material("Iron", (0.12, 0.12, 0.13), roughness=0.5, metallic=0.8),
    }
    for mat in mats.values():   # Workbench previews show the viewport color
        mat.diffuse_color = mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value
    build_colosseum(mats)
    rider, rider_mats = build_rider(PATH_START, math.degrees(HEADING))
    raptor = build_thief(rider_mats)

    PB.sky_gradient(horizon=(0.62, 0.74, 0.92), zenith=(0.2, 0.42, 0.82), strength=0.55)
    sun = link(bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN")))
    sun.data.energy = 4.5
    sun.data.color = (1.0, 0.95, 0.88)
    sun.data.angle = math.radians(1.5)
    sun.location = (-40, -110, 150)
    look_at(sun, (0, 0, 0))

    # Matches the reference photo: a stitched panorama from the west end, about 140 degrees wide.
    # Panoramic cameras render in Cycles only.
    eye = (-(ARENA_A + 17.0), 0, WALK_Z + 1.6)          # standing on the west walkway
    photo = named_camera("Camera_Photo", eye, (30, 0, eye[2]), 12)
    photo.data.type = "PANO"
    photo.data.panorama_type = "EQUIRECTANGULAR"
    photo.data.longitude_min, photo.data.longitude_max = math.radians(-70), math.radians(70)
    photo.data.latitude_min, photo.data.latitude_max = math.radians(-43.8), math.radians(44.8)
    # Low and ahead of the rider on its drive side, looking west down the arena past the deck
    # railing and the hypogeum, with the standing north wall on the right
    # (it frames the rider at HERO_AT, which the ride passes at HERO_FRAME)
    named_camera("Camera_Hero", HERO_AT + Vector((3.9, -2.3, 1.45)), HERO_AT + Vector((-4.0, 1.8, 1.8)), 24)
    animate_chase(rider, raptor)
    bpy.context.scene.frame_set(1)
    render_settings(engine="cycles")
    bpy.context.scene.cycles.samples = 128
    bpy.context.scene.cycles.use_denoising = True


if __name__ == "__main__":
    args = parse_args()
    reset_scene()
    build()
    save(args.out)
