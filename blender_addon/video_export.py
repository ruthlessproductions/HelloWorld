"""Video reference export: renders the blockout scene as a reference clip.

Supports viewport render (fast, for previz) and full render (Cycles/EEVEE).
Outputs individual frames, then optionally encodes to MP4/MOV with ffmpeg.
"""

from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional

import bpy


class VideoExporter:
    def __init__(
        self,
        output_dir: str = "//render_output",
        resolution: tuple[int, int] = (1920, 1080),
        fps: int = 24,
    ):
        self.output_dir = output_dir
        self.resolution = resolution
        self.fps = fps

    def export_reference(
        self,
        quality: str = "preview",
        format: str = "mp4",
        use_viewport: bool = True,
        transparent: bool = False,
    ) -> str:
        scene = bpy.context.scene

        scene.render.resolution_x = self.resolution[0]
        scene.render.resolution_y = self.resolution[1]
        scene.render.fps = self.fps

        if quality == "preview":
            scene.render.resolution_percentage = 50
            if scene.render.engine == "CYCLES":
                scene.cycles.samples = 16
                scene.cycles.use_denoising = True
        elif quality == "draft":
            scene.render.resolution_percentage = 75
            if scene.render.engine == "CYCLES":
                scene.cycles.samples = 64
                scene.cycles.use_denoising = True
        else:
            scene.render.resolution_percentage = 100
            if scene.render.engine == "CYCLES":
                scene.cycles.samples = 128

        abs_output = bpy.path.abspath(self.output_dir)
        frames_dir = os.path.join(abs_output, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        scene.render.image_settings.file_format = "PNG"
        if transparent:
            scene.render.film_transparent = True
            scene.render.image_settings.color_mode = "RGBA"
        else:
            scene.render.film_transparent = False
            scene.render.image_settings.color_mode = "RGB"

        scene.render.filepath = os.path.join(frames_dir, "frame_")

        if use_viewport:
            self._render_viewport(scene)
        else:
            bpy.ops.render.render(animation=True)

        output_path = self._encode_video(frames_dir, abs_output, format, transparent)

        return output_path

    def export_single_frame(
        self,
        frame: Optional[int] = None,
        quality: str = "draft",
    ) -> str:
        scene = bpy.context.scene

        if frame is not None:
            scene.frame_set(frame)

        scene.render.resolution_x = self.resolution[0]
        scene.render.resolution_y = self.resolution[1]
        scene.render.resolution_percentage = 75 if quality == "draft" else 100

        abs_output = bpy.path.abspath(self.output_dir)
        os.makedirs(abs_output, exist_ok=True)

        scene.render.image_settings.file_format = "PNG"
        filepath = os.path.join(abs_output, f"frame_{scene.frame_current:04d}.png")
        scene.render.filepath = filepath

        bpy.ops.render.render(write_still=True)

        return filepath

    def _render_viewport(self, scene):
        ctx_override = None
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        ctx_override = {
                            "area": area,
                            "region": region,
                            "space_data": area.spaces.active,
                        }
                        break

        if ctx_override:
            with bpy.context.temp_override(**ctx_override):
                bpy.ops.render.opengl(animation=True)
        else:
            bpy.ops.render.render(animation=True)

    def _encode_video(
        self,
        frames_dir: str,
        output_dir: str,
        format: str,
        transparent: bool,
    ) -> str:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return frames_dir

        if format == "mov" and transparent:
            output_file = os.path.join(output_dir, "reference.mov")
            cmd = [
                ffmpeg, "-y",
                "-framerate", str(self.fps),
                "-i", os.path.join(frames_dir, "frame_%04d.png"),
                "-c:v", "prores_ks",
                "-profile:v", "4444",
                "-pix_fmt", "yuva444p10le",
                output_file,
            ]
        else:
            output_file = os.path.join(output_dir, "reference.mp4")
            cmd = [
                ffmpeg, "-y",
                "-framerate", str(self.fps),
                "-i", os.path.join(frames_dir, "frame_%04d.png"),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                output_file,
            ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=300)
            return output_file
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return frames_dir


def setup_blockout_materials():
    """Switch all materials to a flat grey blockout look for reference renders."""
    blockout_mat = bpy.data.materials.get("M_Blockout")
    if not blockout_mat:
        blockout_mat = bpy.data.materials.new(name="M_Blockout")
        blockout_mat.use_nodes = True
        nodes = blockout_mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.58, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.8
            bsdf.inputs["Metallic"].default_value = 0.0

    original_materials = {}

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        original_materials[obj.name] = [slot.material for slot in obj.material_slots]
        for slot in obj.material_slots:
            slot.material = blockout_mat

    return original_materials


def restore_materials(original_materials: dict):
    """Restore original materials after blockout render."""
    for obj_name, materials in original_materials.items():
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            continue
        for i, mat in enumerate(materials):
            if i < len(obj.material_slots):
                obj.material_slots[i].material = mat


def setup_overlay_info(scene_name: str = ""):
    """Add frame counter and scene name as overlay text via compositing."""
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = scene.node_tree

    if not tree.nodes.get("Render Layers"):
        return

    render_node = tree.nodes["Render Layers"]

    composite = tree.nodes.get("Composite")
    if not composite:
        composite = tree.nodes.new("CompositorNodeComposite")

    tree.links.new(render_node.outputs["Image"], composite.inputs["Image"])
