---
name: blender
description: Build, render, and animate 3D scenes with the locally installed Blender by writing Python build scripts and running Blender in the background. Use when the user asks for a 3D model or scene, a Blender (.blend) file, a 3D render, a turntable or camera animation, or changes to an existing .blend file.
---

# Blender scenes from scripts

You build scenes by writing a Python script, running Blender in the background, and then checking the result by inspecting it and looking at rendered previews. The script is the source of truth: to change the scene, edit the script and run it again. Deliver a `.blend` the user can open, the script, and renders.

Helpers in this skill's directory (`<skill dir>` below):
- `templates/build_scene.py`: starter build script with tested helpers (materials, curved tubes, rods, ellipsoids, rings, lights, camera, save).
- `scripts/inspect_scene.py`: object sizes in meters, parts that float or sink below ground, bones, materials with unlinked nodes.
- `scripts/render_preview.py`: preview PNGs from the scene camera and from framing views, without changing the file.

## 1. Find Blender

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender   # macOS default
"$BLENDER" --version
```

If that path doesn't exist, look for it (`ls /Applications | grep -i blender`, `mdfind -name Blender.app`, or `which blender` on Linux) and ask the user if you can't find it. Note the version: several APIs differ between 4.x and 5.x (see Pitfalls).

Always run with `--background --factory-startup` so the user's UI and addons don't interfere. Script arguments go after `--`.

## 2. Build

Put each scene in its own folder: `scenes/<name>/build.py`, output next to it.

```bash
mkdir -p scenes/pelican && cp "<skill dir>/templates/build_scene.py" scenes/pelican/build.py
# set NAME = "pelican", replace build(), then:
"$BLENDER" --background --factory-startup --python scenes/pelican/build.py -- --out scenes/pelican
```

Modeling guidance:
- Model recognizable, well-proportioned forms with real detail, not blocky stand-ins.
- Pick the technique per part: `tube()` (Bezier curve with bevel) for necks, limbs, frames, handles, cables; `rod()` for straight struts and spokes; `ellipsoid()` for organic masses; `bmesh` for custom shapes; primitives plus `bevel()` for hard-surface parts; Mirror, Array, Screw, Solidify modifiers for symmetry, repetition and lathed shapes.
- Parts of one object must physically connect: overlap joints slightly. Nothing floats unless the brief says so.
- Build repeated detail with loops (spokes, fence posts, leaves, windows).
- Use Subdivision Surface only on meshes with enough edge loops to hold their shape; never on plain cubes or cylinders (it turns them into blobs and needles). Use `bevel()` there.
- Parent each distinct object's parts to an Empty (`empty("Bicycle")`) and give every part a descriptive name.
- Use real-world scale (meters) from the start; see the reference table below.

## 3. Check, then look

After every build:

```bash
"$BLENDER" --background --factory-startup --python "<skill dir>/scripts/inspect_scene.py" -- --blend scenes/pelican/pelican.blend
"$BLENDER" --background --factory-startup --python "<skill dir>/scripts/render_preview.py" -- \
    --blend scenes/pelican/pelican.blend --out scenes/pelican/previews --res 640
```

Then read the PNGs and go through this list before calling it done:
- **Scale:** compare `size x,y,z` against the reference table. Fix anything more than about 30% off, including texture detail size (noise/bump features should match the object's real size).
- **Placement:** every `FLOATING` or `BELOW_GROUND` flag is either fixed or intended (clouds, balloons, a buried foundation).
- **Connections:** in the previews, joints touch, nothing sticks through where it shouldn't, and wheels, feet and bases rest on the ground.
- **Framing:** the scene camera shows the whole subject with some margin.
- **Materials:** no pure black or neon surprises; remove every unlinked node the inspector lists.

Previews default to EEVEE. `--engine workbench` is fastest for checking shapes; `--engine cycles` works everywhere, including machines without a GPU. Keep previews small (640 px) to save time and tokens; look at only the views you need.

## 4. Revise

- Change only what was asked. Don't retune materials, lighting or other parts as a side effect.
- Edit `build.py` and rebuild instead of patching the `.blend`, so the script stays the source of truth.
- If the same fix fails twice, stop and tell the user what you tried and what you see, instead of looping.

## 5. Final render and animation

For the final still, render through the scene camera at full resolution:

```bash
"$BLENDER" --background --factory-startup --python "<skill dir>/scripts/render_preview.py" -- \
    --blend scenes/pelican/pelican.blend --out scenes/pelican/renders --views camera --res 1920 --samples 64
```

For animation, keyframe in the build script, then render video directly from Blender (no ffmpeg needed):

```python
scene.frame_start, scene.frame_end = 1, 120
scene.render.fps = 24
im = scene.render.image_settings
if hasattr(im, "media_type"):          # Blender 5.x
    im.media_type = "VIDEO"
im.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.filepath = "//renders/turntable_"   # "//" = relative to the .blend
bpy.ops.render.render(animation=True)
```

Render a short, low-resolution test (about 24 frames at 480 px) before the full animation.

If this skill sits in the AI Scene Generator repo, its camera presets (turntable, slow_zoom, dramatic_reveal, orbit_rise, vertigo, showcase_loop, fly_over, pull_back) can be reused:

```python
import sys
sys.path.insert(0, "<repo>/blender_addon")
import camera_animation
camera_animation.animate_preset("turntable", target=(0, 0, 1.0))   # sets frames and scene camera
```

For an existing rigged model, run `inspect_scene.py` to list its bones, then keyframe `pose.bones["name"].rotation_euler` (set `rotation_mode = "XYZ"` first) in a script that opens the user's file.

## Working on the user's existing .blend

Open it in the script with `bpy.ops.wm.open_mainfile(filepath=...)` instead of `reset_scene()`, and save to a new file (`<name>_v2.blend`). Never overwrite the user's file unless they ask. Inspect it first so you know what's there.

## Real-world scale reference (meters)

| Thing | Size |
|---|---|
| Adult human | 1.75 tall, shoulders 0.45 wide |
| Door | 2.0 × 0.9 |
| Table / chair seat / counter | 0.75 / 0.45 / 0.9 high |
| Bicycle | 1.75 long, wheels 0.68 diameter, saddle about 0.9 high |
| Car | 4.5 × 1.8 × 1.5 |
| Pelican | 1.1–1.8 long, bill 0.3–0.5, wingspan 2–3 |
| House storey | 3.0 |
| Tree | 5–20 tall |
| Mountain (in a scene) | hundreds to thousands; move the camera, don't shrink the mountain |

## Pitfalls (bpy)

- Bezier points have `handle_left_type` / `handle_right_type`; there is no `handle_type`. A new spline already has one point: `spline.bezier_points.add(n - 1)`.
- Prefer `bpy.data` plus `scene.collection.objects.link(obj)` over `bpy.ops`; some operators need a UI context (active area, selection) that background mode doesn't have.
- Rotations are radians (`rotation_euler`).
- Camera field of view: set `cam.data.angle`, but keyframe `cam.data.lens` (`angle` can't be keyframed).
- Render engine ID: `BLENDER_EEVEE_NEXT` on 4.2–4.4, `BLENDER_EEVEE` on 5.x; check the enum like the template's `render_settings()` does.
- Blender 5.x: `Action.fcurves` is gone. Get F-curves through `bpy_extras.anim_utils.action_get_channelbag_for_slot(action, obj.animation_data.action_slot).fcurves`.
- Blender 5.x: new materials and worlds already have node trees; `use_nodes` is deprecated.
- Blender 5.x: an evaluated curve object's `bound_box` is unreliable; measure `evaluated.to_mesh()` vertices instead (the inspector does this).
- Removed in 4.1+: `Mesh.use_auto_smooth`, the `bgl` module. Smooth shading: `mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))`.
- Principled BSDF input names (4.0+): "Base Color", "Metallic", "Roughness", "Transmission Weight", "Emission Color", "Emission Strength", "Subsurface Weight", "Coat Weight".
- Sky texture types differ across versions; check `ShaderNodeTexSky.bl_rna.properties["sky_type"].enum_items` before setting one.
- Linux without a GPU: EEVEE and Workbench fail (`libEGL`); use `--engine cycles`.
