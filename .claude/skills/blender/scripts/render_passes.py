"""Render a shot's control passes for diffusion models (depth, normals, segmentation, edges, and a
quick beauty render), as numbered PNGs plus one MP4 per pass. Does not modify the .blend.

Usage:
  "$BLENDER" --background --factory-startup --python render_passes.py -- \
      --blend scene.blend --out passes/ [--passes beauty,depth,normal,segmentation,edges] \
      [--frames 1-73] [--res 1280] [--camera NAME] [--samples 16] [--depth-mode inverse|linear] \
      [--overscan 16:9] [--no-video] [--keep-raw]

Conventions (the ones depth/normal/edge-conditioned image and video models expect):
- depth: near is white, far is black, background black. "inverse" (default) maps 1/distance, like
  MiDaS and Depth Anything; "linear" maps distance. Normalized once over the whole shot, so it
  does not flicker from frame to frame.
- normal: camera-space normals as colors: red = right, green = up, blue = toward the camera.
- segmentation: one flat random color per object, stable across frames.
- edges: white geometric edges on black: depth and normal breaks plus object boundaries (no
  texture noise).
- beauty: EEVEE with the scene's own materials, for image-to-video or reference inputs.
Objects that are pure volumes (haze, smoke) are left out of the data passes.
--overscan W:H renders a taller (or wider) frame around the shot, for models that only accept
certain aspect ratios: the camera's horizontal field of view is kept, so the original frame is the
centered crop recorded in passes.json ("crop"). Padding with black bars instead would read as
"far away" in a depth pass and invite the model to paint sky there.
Writes <out>/<pass>/0001.png..., <out>/<pass>.mp4 (if ffmpeg is on PATH) and <out>/passes.json.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

import bpy
import numpy as np

ALL_PASSES = ("beauty", "depth", "normal", "segmentation", "edges")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--passes", default=",".join(ALL_PASSES))
    parser.add_argument("--frames", help="first-last (default: the scene's range)")
    parser.add_argument("--res", type=int, help="width in pixels (default: the scene's); keeps the aspect")
    parser.add_argument("--camera", help="camera object (default: the scene camera)")
    parser.add_argument("--samples", type=int, default=16, help="EEVEE samples for the beauty pass")
    parser.add_argument("--depth-mode", default="inverse", choices=["inverse", "linear"])
    parser.add_argument("--overscan", help="render a W:H frame around the shot, e.g. 16:9")
    parser.add_argument("--no-video", action="store_true", help="skip the per-pass MP4s")
    parser.add_argument("--keep-raw", action="store_true", help="keep the float EXR intermediates")
    return parser.parse_args(argv)


def eevee_id():
    available = {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in available else "BLENDER_EEVEE"


def is_volume_only(obj):
    """True for meshes whose materials only feed a Volume output (haze boxes, smoke)."""
    mats = [s.material for s in getattr(obj, "material_slots", []) if s.material]
    if obj.type != "MESH" or not mats:
        return False
    for mat in mats:
        out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None) if mat.node_tree else None
        if out is None or out.inputs["Surface"].is_linked or not out.inputs["Volume"].is_linked:
            return False
    return True


def set_image_format(scene, fmt):
    image = scene.render.image_settings
    if hasattr(image, "media_type"):          # Blender 5.x
        image.media_type = "IMAGE"
    image.file_format = fmt
    if fmt == "OPEN_EXR":
        image.color_depth = "32"
        image.color_mode = "RGBA"
    else:
        image.color_mode = "RGB"
        image.color_depth = "8"


def render_sequence(scene, path_prefix):
    scene.render.filepath = path_prefix
    bpy.ops.render.render(animation=True)


def override_material(kind):
    """Emission-only material that writes raw data: view-space depth or camera-space normal."""
    mat = bpy.data.materials.new(f"Pass_{kind}")
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    for n in list(nodes):
        if n.type != "OUTPUT_MATERIAL":
            nodes.remove(n)
    emit = nodes.new("ShaderNodeEmission")
    if kind == "depth":
        cam = nodes.new("ShaderNodeCameraData")
        links.new(cam.outputs["View Z Depth"], emit.inputs["Color"])
    else:
        geo = nodes.new("ShaderNodeNewGeometry")
        to_cam = nodes.new("ShaderNodeVectorTransform")
        to_cam.vector_type = "NORMAL"
        to_cam.convert_from, to_cam.convert_to = "WORLD", "CAMERA"
        links.new(geo.outputs["Normal"], to_cam.inputs["Vector"])
        links.new(to_cam.outputs["Vector"], emit.inputs["Color"])
    output = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
    links.new(emit.outputs["Emission"], output.inputs["Surface"])
    return mat


def read_pixels(path):
    """Pixels (RGBA floats, bottom row first) of an EXR or PNG."""
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(h, w, 4)


def write_png(path, rgb):
    h, w = rgb.shape[:2]
    img = bpy.data.images.new("pass_out", w, h, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"              # store the values as they are
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(rgb, 0.0, 1.0)
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def make_video(frames_dir, fps, out_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found on PATH: skipping", out_path)
        return False
    subprocess.run([ffmpeg, "-v", "error", "-y", "-framerate", str(fps), "-i", os.path.join(frames_dir, "%04d.png"),
                    "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                    "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", out_path], check=True)
    return True


def main():
    args = parse_args()
    passes = [p.strip() for p in args.passes.split(",") if p.strip()]
    unknown = set(passes) - set(ALL_PASSES)
    if unknown:
        sys.exit(f"unknown passes: {', '.join(sorted(unknown))}")
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
    shot_size = (render.resolution_x, render.resolution_y)
    if args.overscan:
        aw, ah = (float(v) for v in args.overscan.split(":"))
        cam = scene.camera.data
        cam.sensor_fit = "HORIZONTAL"                        # keep the horizontal field of view
        render.resolution_y = int(round(render.resolution_x * ah / aw / 2)) * 2
    out = os.path.abspath(args.out)
    raw = os.path.join(out, "_raw")
    os.makedirs(raw, exist_ok=True)
    frames = list(range(scene.frame_start, scene.frame_end + 1))
    fps = render.fps / render.fps_base
    meta = {"blend": args.blend, "camera": scene.camera.name, "frames": [frames[0], frames[-1]], "fps": fps,
            "resolution": [render.resolution_x, render.resolution_y], "passes": {}}
    if args.overscan:
        meta["crop"] = {"shot_resolution": list(shot_size), "note": "the shot is the centered crop of this size"}

    if "beauty" in passes:
        render.engine = eevee_id()
        scene.eevee.taa_render_samples = args.samples
        set_image_format(scene, "PNG")
        render_sequence(scene, os.path.join(out, "beauty", ""))
        meta["passes"]["beauty"] = {"engine": "EEVEE", "samples": args.samples}

    # Data passes: hide volumes, black world, no motion blur, transparent film for a clean background
    volumes = [o for o in scene.objects if is_volume_only(o)]
    for o in volumes:
        o.hide_render = True
    black = bpy.data.worlds.new("Pass_Black")
    black.color = (0, 0, 0)
    black.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    scene.world = black
    render.use_motion_blur = False
    render.film_transparent = True
    render.dither_intensity = 0.0           # 8-bit dither noise would read as edges and label noise

    need = {"depth": {"depth", "edges"}, "normal": {"normal", "edges"}}
    raw_done = {}
    for kind in ("depth", "normal"):
        if not need[kind] & set(passes):
            continue
        render.engine = eevee_id()
        scene.eevee.taa_render_samples = 4
        bpy.context.view_layer.material_override = override_material(kind)
        set_image_format(scene, "OPEN_EXR")
        render_sequence(scene, os.path.join(raw, f"{kind}_"))
        raw_done[kind] = [os.path.join(raw, f"{kind}_{f:04d}.exr") for f in frames]
    bpy.context.view_layer.material_override = None

    seg_dir = os.path.join(out if "segmentation" in passes else raw, "segmentation")
    if "segmentation" in passes or "edges" in passes:          # edges also use object boundaries
        render.engine = "BLENDER_WORKBENCH"
        shading = scene.display.shading
        shading.light, shading.color_type = "FLAT", "RANDOM"
        shading.show_shadows = shading.show_cavity = shading.show_object_outline = False
        shading.show_specular_highlight = False
        render.film_transparent = False
        scene.view_settings.view_transform = "Standard"
        set_image_format(scene, "PNG")
        render_sequence(scene, os.path.join(seg_dir, ""))
        if "segmentation" in passes:
            meta["passes"]["segmentation"] = {"colors": "random per object"}

    # Depth: one normalization for the whole shot
    depth_maps = []
    if "depth" in raw_done:
        stack = [read_pixels(p) for p in raw_done["depth"]]
        valid = np.concatenate([d[..., 0][d[..., 3] > 0.5] for d in stack])
        near, far = (float(np.percentile(valid, 0.5)), float(np.percentile(valid, 99.5))) if valid.size else (0.1, 100.0)
        near = max(near, 1e-3)
        for d in stack:
            z = np.maximum(d[..., 0], near)
            if args.depth_mode == "inverse":
                v = (1.0 / z - 1.0 / far) / (1.0 / near - 1.0 / far)
            else:
                v = 1.0 - (z - near) / (far - near)
            v = np.where(d[..., 3] > 0.5, np.clip(v, 0.0, 1.0), 0.0)
            depth_maps.append((v, d))
        if "depth" in passes:
            os.makedirs(os.path.join(out, "depth"), exist_ok=True)
            for f, (v, _) in zip(frames, depth_maps):
                write_png(os.path.join(out, "depth", f"{f:04d}.png"), np.repeat(v[..., None], 3, axis=2))
        meta["passes"]["depth"] = {"mode": args.depth_mode, "near_m": round(near, 3), "far_m": round(far, 3),
                                   "white": "near"}

    normal_maps = []
    if "normal" in raw_done:
        for p in raw_done["normal"]:
            n = read_pixels(p)
            vec = n[..., :3]
            vec = np.where(vec[..., 2:3] < 0, -vec, vec)          # back faces: flip toward the camera
            normal_maps.append((np.where(n[..., 3:4] > 0.5, vec * 0.5 + 0.5, 0.0), vec, n[..., 3]))
        if "normal" in passes:
            os.makedirs(os.path.join(out, "normal"), exist_ok=True)
            for f, (rgb, _, _) in zip(frames, normal_maps):
                write_png(os.path.join(out, "normal", f"{f:04d}.png"), rgb)
        meta["passes"]["normal"] = {"space": "camera", "red": "right", "green": "up", "blue": "toward camera"}

    if "edges" in passes and depth_maps and normal_maps:
        os.makedirs(os.path.join(out, "edges"), exist_ok=True)
        for f, (v, d), (_, vec, alpha) in zip(frames, depth_maps, normal_maps):
            seg = read_pixels(os.path.join(seg_dir, f"{f:04d}.png"))[..., :3]
            gs = (np.abs(np.diff(seg, axis=0, append=seg[-1:])) + np.abs(np.diff(seg, axis=1, append=seg[:, -1:]))).sum(axis=2)
            logz = np.log(np.maximum(d[..., 0], 1e-3))
            logz = np.where(alpha > 0.5, logz, logz.max() + 2.0)
            gz = np.abs(np.diff(logz, axis=0, append=logz[-1:])) + np.abs(np.diff(logz, axis=1, append=logz[:, -1:]))
            gn = sum(np.abs(np.diff(vec[..., c], axis=0, append=vec[-1:, :, c])) +
                     np.abs(np.diff(vec[..., c], axis=1, append=vec[:, -1:, c])) for c in range(3))
            edge = ((gz > 0.04) | (gn > 0.35) | (gs > 0.06)).astype(np.float32)
            write_png(os.path.join(out, "edges", f"{f:04d}.png"), np.repeat(edge[..., None], 3, axis=2))
        meta["passes"]["edges"] = {"from": "depth, normal and object boundaries", "white": "edge"}

    # Beauty and segmentation were written as frame_####.png by Blender: rename to ####.png
    for name in ("beauty", "segmentation"):
        folder = os.path.join(out, name)
        if name in passes and os.path.isdir(folder):
            for fn in os.listdir(folder):
                if fn.endswith(".png") and not fn[:4].isdigit():
                    os.replace(os.path.join(folder, fn), os.path.join(folder, fn[-8:]))

    if not args.no_video:
        for name in passes:
            folder = os.path.join(out, name)
            if os.path.isdir(folder) and make_video(folder, fps, os.path.join(out, f"{name}.mp4")):
                meta["passes"].setdefault(name, {})["video"] = f"{name}.mp4"
    if not args.keep_raw:
        shutil.rmtree(raw, ignore_errors=True)
    with open(os.path.join(out, "passes.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"wrote passes {', '.join(passes)} for frames {frames[0]}-{frames[-1]} to {out}")


main()
