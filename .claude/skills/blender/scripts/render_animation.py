"""Render a .blend's animation to an MP4 (or PNG frames), without modifying the file.

Usage:
  "$BLENDER" --background --factory-startup --python render_animation.py -- \
      --blend scene.blend --out renders/shot.mp4 [--frames 1-24] [--res 1280] \
      [--engine cycles|eevee|workbench] [--samples 64] [--camera NAME]

--out ending in .mp4 writes one H.264 video at exactly that path; anything else is a folder
of numbered PNGs. --frames limits the range (default: the scene's). --res is the width; the
height keeps the scene's aspect. Cycles uses the GPU when one is available and keeps static
geometry between frames.
"""

import argparse
import glob
import os
import sys

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--frames", help="first-last, e.g. 1-24")
    parser.add_argument("--res", type=int, help="width in pixels (default: the scene's)")
    parser.add_argument("--engine", default="cycles", choices=["eevee", "workbench", "cycles"])
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--camera", help="camera object (default: the scene camera)")
    return parser.parse_args(argv)


def use_gpu(scene):
    """Point Cycles at the first GPU backend with a device; fall back to the CPU."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
        try:
            prefs.compute_device_type = backend
        except TypeError:          # backend not built into this Blender
            continue
        prefs.get_devices()
        if any(d.type == backend for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == backend
            scene.cycles.device = "GPU"
            return backend
    scene.cycles.device = "CPU"
    return "CPU"


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=args.blend)
    scene = bpy.context.scene
    render = scene.render
    if args.camera:
        scene.camera = bpy.data.objects[args.camera]
    if args.frames:
        scene.frame_start, scene.frame_end = (int(v) for v in args.frames.split("-"))
    if args.res:
        aspect = render.resolution_y / render.resolution_x
        render.resolution_x, render.resolution_y = args.res, round(args.res * aspect)
    render.resolution_percentage = 100

    available = {i.identifier for i in render.bl_rna.properties["engine"].enum_items}
    if args.engine == "cycles":
        render.engine = "CYCLES"
        scene.cycles.samples = args.samples
        render.use_persistent_data = True
        print(f"cycles device: {use_gpu(scene)}")
    elif args.engine == "eevee":
        render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in available else "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = args.samples
    else:
        render.engine = "BLENDER_WORKBENCH"

    out = os.path.abspath(args.out)
    image = render.image_settings
    if out.endswith(".mp4"):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if hasattr(image, "media_type"):          # Blender 5.x
            image.media_type = "VIDEO"
        image.file_format = "FFMPEG"
        render.ffmpeg.format = "MPEG4"
        render.ffmpeg.codec = "H264"
        render.ffmpeg.constant_rate_factor = "HIGH"
        stem = out[:-4] + "_"                     # Blender appends the frame range to this
        render.filepath = stem
        bpy.ops.render.render(animation=True)
        written = sorted(glob.glob(stem + "*.mp4"), key=os.path.getmtime)
        os.replace(written[-1], out)
    else:
        os.makedirs(out, exist_ok=True)
        if hasattr(image, "media_type"):
            image.media_type = "IMAGE"
        image.file_format = "PNG"
        render.filepath = os.path.join(out, "frame_")
        bpy.ops.render.render(animation=True)
    print(f"wrote {out} (frames {scene.frame_start}-{scene.frame_end}, {render.resolution_x}x{render.resolution_y})")


main()
