"""Scene builder: converts scene descriptions into native Blender objects.

Uses bpy to create meshes, Principled BSDF materials with procedural
shader nodes, lights, and camera.
"""

from __future__ import annotations

import math
from typing import Optional

import bpy
import mathutils


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    for block in bpy.data.meshes:
        if not block.users:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if not block.users:
            bpy.data.materials.remove(block)
    for block in bpy.data.lights:
        if not block.users:
            bpy.data.lights.remove(block)
    for block in bpy.data.cameras:
        if not block.users:
            bpy.data.cameras.remove(block)


def build_scene(
    scene_data: dict,
    add_ground: bool = True,
    texture_size: int = 1024,
):
    objects = scene_data.get("objects", [])

    for obj_data in objects:
        _create_object(obj_data, texture_size=texture_size)

    if add_ground and scene_data.get("ground_plane", True):
        _create_ground_plane()


def _create_object(
    obj_data: dict,
    parent: Optional[bpy.types.Object] = None,
    texture_size: int = 1024,
):
    primitive = obj_data.get("primitive", "cube")
    name = obj_data.get("name", "Object")
    position = obj_data.get("position", [0, 0, 0])
    rotation = obj_data.get("rotation", [0, 0, 0])
    scale = obj_data.get("scale", [1, 1, 1])

    mesh_obj = _create_primitive(primitive, name, scale)
    if mesh_obj is None:
        return

    mesh_obj.location = mathutils.Vector(position)
    mesh_obj.rotation_euler = mathutils.Euler(
        [math.radians(r) for r in rotation], "XYZ"
    )

    if parent:
        mesh_obj.parent = parent

    mat_data = obj_data.get("material", {})
    mat = _create_material(name, mat_data, texture_size)
    mesh_obj.data.materials.append(mat)

    bpy.ops.object.shade_smooth()

    for child_data in obj_data.get("children", []):
        _create_object(child_data, parent=mesh_obj, texture_size=texture_size)


def _create_primitive(
    primitive: str,
    name: str,
    scale: list[float],
) -> Optional[bpy.types.Object]:
    sx, sy, sz = scale

    if primitive == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.active_object
        obj.scale = (sx, sy, sz)

    elif primitive == "sphere":
        radius = max(sx, sy, sz) / 2
        bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=48, ring_count=24)
        obj = bpy.context.active_object
        obj.scale = (sx / (2 * radius), sy / (2 * radius), sz / (2 * radius))

    elif primitive == "cylinder":
        radius = max(sx, sy) / 2
        depth = sz
        bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=48)
        obj = bpy.context.active_object

    elif primitive == "cone":
        radius = max(sx, sy) / 2
        depth = sz
        bpy.ops.mesh.primitive_cone_add(radius1=radius, depth=depth, vertices=48)
        obj = bpy.context.active_object

    elif primitive == "plane":
        bpy.ops.mesh.primitive_plane_add(size=1)
        obj = bpy.context.active_object
        obj.scale = (sx, sy, 1)

    elif primitive == "torus":
        major = max(sx, sy) / 2
        minor = sz / 4
        bpy.ops.mesh.primitive_torus_add(
            major_radius=major, minor_radius=minor,
            major_segments=64, minor_segments=24,
        )
        obj = bpy.context.active_object

    else:
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.active_object
        obj.scale = (sx, sy, sz)

    obj.name = name
    return obj


def _create_material(name: str, mat_data: dict, texture_size: int) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=f"M_{name}")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (200, 0)

    color = mat_data.get("color", [0.8, 0.8, 0.8])
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = mat_data.get("roughness", 0.5)
    bsdf.inputs["Metallic"].default_value = mat_data.get("metallic", 0.0)

    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    texture_prompt = mat_data.get("texture_prompt")
    if texture_prompt:
        _add_procedural_texture(mat, bsdf, texture_prompt, color, texture_size)

    return mat


def _add_procedural_texture(
    mat: bpy.types.Material,
    bsdf,
    prompt: str,
    base_color: list[float],
    texture_size: int,
):
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-800, 0)

    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-600, 0)
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])

    prompt_lower = prompt.lower()

    if _matches(prompt_lower, ["stone", "rock", "brick", "concrete", "wall"]):
        _stone_texture(nodes, links, mapping, bsdf, base_color, prompt_lower)
    elif _matches(prompt_lower, ["wood", "wooden", "plank", "timber", "oak", "pine"]):
        _wood_texture(nodes, links, mapping, bsdf, base_color)
    elif _matches(prompt_lower, ["metal", "steel", "iron", "rust", "copper", "gold"]):
        _metal_texture(nodes, links, mapping, bsdf, base_color, prompt_lower)
    elif _matches(prompt_lower, ["grass", "moss", "vegetation", "lawn"]):
        _grass_texture(nodes, links, mapping, bsdf, base_color)
    elif _matches(prompt_lower, ["sand", "dirt", "earth", "soil", "clay"]):
        _earth_texture(nodes, links, mapping, bsdf, base_color)
    elif _matches(prompt_lower, ["water", "ocean", "liquid"]):
        _water_material(bsdf, base_color)
    elif _matches(prompt_lower, ["glass", "crystal", "transparent"]):
        _glass_material(bsdf, base_color)
    elif _matches(prompt_lower, ["tile", "roof", "ceramic", "terra"]):
        _tile_texture(nodes, links, mapping, bsdf, base_color)
    else:
        _generic_texture(nodes, links, mapping, bsdf, base_color)


def _matches(prompt: str, keywords: list[str]) -> bool:
    return any(kw in prompt for kw in keywords)


def _stone_texture(nodes, links, mapping, bsdf, color, prompt):
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-400, 200)
    noise.inputs["Scale"].default_value = 8.0
    noise.inputs["Detail"].default_value = 12.0
    noise.inputs["Roughness"].default_value = 0.7
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    voronoi = nodes.new("ShaderNodeTexVoronoi")
    voronoi.location = (-400, -100)
    voronoi.inputs["Scale"].default_value = 5.0
    links.new(mapping.outputs["Vector"], voronoi.inputs["Vector"])

    mix_color = nodes.new("ShaderNodeMix")
    mix_color.data_type = "RGBA"
    mix_color.location = (-100, 200)
    mix_color.inputs["Factor"].default_value = 0.3

    dark = [max(0, c - 0.15) for c in color]
    light = [min(1, c + 0.1) for c in color]
    mix_color.inputs["A"].default_value = (*dark, 1.0)
    mix_color.inputs["B"].default_value = (*light, 1.0)

    links.new(noise.outputs["Fac"], mix_color.inputs["Factor"])
    links.new(mix_color.outputs["Result"], bsdf.inputs["Base Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (0, -200)
    bump.inputs["Strength"].default_value = 0.3
    links.new(voronoi.outputs["Distance"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    roughness_mix = nodes.new("ShaderNodeMath")
    roughness_mix.operation = "ADD"
    roughness_mix.location = (0, -50)
    roughness_mix.inputs[0].default_value = 0.7
    roughness_mix.inputs[1].default_value = 0.0
    links.new(noise.outputs["Fac"], roughness_mix.inputs[1])

    clamp = nodes.new("ShaderNodeClamp")
    clamp.location = (150, -50)
    links.new(roughness_mix.outputs[0], clamp.inputs[0])
    links.new(clamp.outputs[0], bsdf.inputs["Roughness"])


def _wood_texture(nodes, links, mapping, bsdf, color):
    wave = nodes.new("ShaderNodeTexWave")
    wave.location = (-400, 200)
    wave.wave_type = "RINGS"
    wave.inputs["Scale"].default_value = 3.0
    wave.inputs["Distortion"].default_value = 4.0
    wave.inputs["Detail"].default_value = 3.0
    links.new(mapping.outputs["Vector"], wave.inputs["Vector"])

    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-400, -100)
    noise.inputs["Scale"].default_value = 15.0
    noise.inputs["Detail"].default_value = 6.0
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    mix_wave = nodes.new("ShaderNodeMix")
    mix_wave.data_type = "FLOAT"
    mix_wave.location = (-200, 100)
    mix_wave.inputs["Factor"].default_value = 0.2
    links.new(wave.outputs["Fac"], mix_wave.inputs["A"])
    links.new(noise.outputs["Fac"], mix_wave.inputs["B"])

    color_ramp = nodes.new("ShaderNodeValToRGB")
    color_ramp.location = (-50, 200)

    dark_wood = [max(0, c - 0.2) for c in color]
    light_wood = [min(1, c + 0.1) for c in color]
    color_ramp.color_ramp.elements[0].color = (*dark_wood, 1.0)
    color_ramp.color_ramp.elements[1].color = (*light_wood, 1.0)

    links.new(mix_wave.outputs["Result"], color_ramp.inputs["Fac"])
    links.new(color_ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (0, -200)
    bump.inputs["Strength"].default_value = 0.15
    links.new(wave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _metal_texture(nodes, links, mapping, bsdf, color, prompt):
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.2

    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-400, 200)
    noise.inputs["Scale"].default_value = 20.0
    noise.inputs["Detail"].default_value = 8.0
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    if "rust" in prompt:
        bsdf.inputs["Roughness"].default_value = 0.8

        voronoi = nodes.new("ShaderNodeTexVoronoi")
        voronoi.location = (-400, -100)
        voronoi.inputs["Scale"].default_value = 4.0
        links.new(mapping.outputs["Vector"], voronoi.inputs["Vector"])

        mix_color = nodes.new("ShaderNodeMix")
        mix_color.data_type = "RGBA"
        mix_color.location = (-100, 200)
        links.new(voronoi.outputs["Distance"], mix_color.inputs["Factor"])
        mix_color.inputs["A"].default_value = (*color, 1.0)
        mix_color.inputs["B"].default_value = (0.72, 0.25, 0.05, 1.0)
        links.new(mix_color.outputs["Result"], bsdf.inputs["Base Color"])
    else:
        color_var = nodes.new("ShaderNodeMix")
        color_var.data_type = "RGBA"
        color_var.location = (-100, 200)
        color_var.inputs["Factor"].default_value = 0.0
        links.new(noise.outputs["Fac"], color_var.inputs["Factor"])
        bright = [min(1, c + 0.1) for c in color]
        color_var.inputs["A"].default_value = (*color, 1.0)
        color_var.inputs["B"].default_value = (*bright, 1.0)
        links.new(color_var.outputs["Result"], bsdf.inputs["Base Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (0, -200)
    bump.inputs["Strength"].default_value = 0.05
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _grass_texture(nodes, links, mapping, bsdf, color):
    noise1 = nodes.new("ShaderNodeTexNoise")
    noise1.location = (-400, 200)
    noise1.inputs["Scale"].default_value = 12.0
    noise1.inputs["Detail"].default_value = 10.0
    links.new(mapping.outputs["Vector"], noise1.inputs["Vector"])

    noise2 = nodes.new("ShaderNodeTexNoise")
    noise2.location = (-400, -100)
    noise2.inputs["Scale"].default_value = 40.0
    noise2.inputs["Detail"].default_value = 4.0
    links.new(mapping.outputs["Vector"], noise2.inputs["Vector"])

    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.location = (-100, 200)
    links.new(noise2.outputs["Fac"], mix.inputs["Factor"])

    dark_grass = [max(0, c - 0.1) for c in color]
    light_grass = [min(1, c + 0.15) for c in color]
    mix.inputs["A"].default_value = (*dark_grass, 1.0)
    mix.inputs["B"].default_value = (*light_grass, 1.0)
    links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (0, -200)
    bump.inputs["Strength"].default_value = 0.2
    links.new(noise1.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    bsdf.inputs["Roughness"].default_value = 0.9


def _earth_texture(nodes, links, mapping, bsdf, color):
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-400, 200)
    noise.inputs["Scale"].default_value = 6.0
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.8
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    voronoi = nodes.new("ShaderNodeTexVoronoi")
    voronoi.location = (-400, -100)
    voronoi.inputs["Scale"].default_value = 3.0
    links.new(mapping.outputs["Vector"], voronoi.inputs["Vector"])

    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.location = (-100, 200)
    mix.inputs["Factor"].default_value = 0.0
    links.new(noise.outputs["Fac"], mix.inputs["Factor"])

    dark = [max(0, c - 0.1) for c in color]
    mix.inputs["A"].default_value = (*dark, 1.0)
    mix.inputs["B"].default_value = (*color, 1.0)
    links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (0, -200)
    bump.inputs["Strength"].default_value = 0.4
    links.new(voronoi.outputs["Distance"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    bsdf.inputs["Roughness"].default_value = 0.95


def _water_material(bsdf, color):
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.05
    bsdf.inputs["IOR"].default_value = 1.33
    bsdf.inputs["Transmission Weight"].default_value = 0.9
    bsdf.inputs["Alpha"].default_value = 0.7


def _glass_material(bsdf, color):
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.0
    bsdf.inputs["IOR"].default_value = 1.45
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    bsdf.inputs["Alpha"].default_value = 0.3


def _tile_texture(nodes, links, mapping, bsdf, color):
    checker = nodes.new("ShaderNodeTexChecker")
    checker.location = (-400, 200)
    checker.inputs["Scale"].default_value = 8.0
    links.new(mapping.outputs["Vector"], checker.inputs["Vector"])

    dark = [max(0, c - 0.15) for c in color]
    checker.inputs["Color1"].default_value = (*color, 1.0)
    checker.inputs["Color2"].default_value = (*dark, 1.0)

    links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (0, -200)
    bump.inputs["Strength"].default_value = 0.1
    links.new(checker.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _generic_texture(nodes, links, mapping, bsdf, color):
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-400, 200)
    noise.inputs["Scale"].default_value = 10.0
    noise.inputs["Detail"].default_value = 6.0
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.location = (-100, 200)
    mix.inputs["Factor"].default_value = 0.0
    links.new(noise.outputs["Fac"], mix.inputs["Factor"])

    dark = [max(0, c - 0.08) for c in color]
    mix.inputs["A"].default_value = (*dark, 1.0)
    mix.inputs["B"].default_value = (*color, 1.0)
    links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (0, -200)
    bump.inputs["Strength"].default_value = 0.1
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _create_ground_plane():
    bpy.ops.mesh.primitive_plane_add(size=50, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "Ground"

    mat = bpy.data.materials.new(name="M_Ground")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.35, 0.35, 0.33, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9

    ground.data.materials.append(mat)


def setup_lighting(lights_data: list[dict], use_hdri: bool = True):
    if use_hdri:
        _setup_hdri_world()

    for light_data in lights_data:
        _create_light(light_data)

    if not lights_data:
        _create_default_lights()


def _create_light(light_data: dict):
    light_type = light_data.get("type", "POINT")
    position = light_data.get("position", [5, 5, 8])
    color = light_data.get("color", [1, 1, 1])
    intensity = light_data.get("intensity", 1.0)

    light = bpy.data.lights.new(name=f"Light_{light_type}", type=light_type)
    light.color = color
    light.energy = intensity

    if light_type == "SUN":
        light.angle = math.radians(1.0)

    light_obj = bpy.data.objects.new(name=f"Light_{light_type}", object_data=light)
    bpy.context.collection.objects.link(light_obj)
    light_obj.location = mathutils.Vector(position)

    direction = light_data.get("direction")
    if direction and light_type == "SUN":
        dir_vec = mathutils.Vector(direction).normalized()
        rot = dir_vec.to_track_quat("-Z", "Y")
        light_obj.rotation_euler = rot.to_euler()


def _create_default_lights():
    sun = bpy.data.lights.new(name="Sun", type="SUN")
    sun.energy = 3.0
    sun.color = (1.0, 0.95, 0.9)
    sun_obj = bpy.data.objects.new(name="Sun", object_data=sun)
    bpy.context.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (math.radians(45), math.radians(15), math.radians(30))

    fill = bpy.data.lights.new(name="Fill", type="AREA")
    fill.energy = 100
    fill.color = (0.8, 0.85, 1.0)
    fill.size = 5
    fill_obj = bpy.data.objects.new(name="Fill", object_data=fill)
    bpy.context.collection.objects.link(fill_obj)
    fill_obj.location = (-5, -5, 4)


def _setup_hdri_world():
    world = bpy.data.worlds.get("World")
    if not world:
        world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world

    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links

    bg = nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.05, 0.08, 0.15, 1.0)
        bg.inputs["Strength"].default_value = 0.5

    sky = nodes.new("ShaderNodeTexSky")
    sky.location = (-300, 300)
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(30)
    sky.sun_rotation = math.radians(45)

    if bg:
        links.new(sky.outputs["Color"], bg.inputs["Color"])


def setup_camera(camera_data: dict):
    position = camera_data.get("position", [8, -6, 5])
    target = camera_data.get("target", [0, 0, 2])
    fov = camera_data.get("fov", 50)

    cam_data = bpy.data.cameras.new(name="SceneCamera")
    cam_data.lens_unit = "FOV"
    cam_data.angle = math.radians(fov)
    cam_data.clip_end = 500

    cam_obj = bpy.data.objects.new(name="SceneCamera", object_data=cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location = mathutils.Vector(position)

    target_vec = mathutils.Vector(target)
    direction = target_vec - cam_obj.location
    rot = direction.to_track_quat("-Z", "Y")
    cam_obj.rotation_euler = rot.to_euler()

    bpy.context.scene.camera = cam_obj

    bpy.context.scene.render.resolution_x = 1920
    bpy.context.scene.render.resolution_y = 1080
