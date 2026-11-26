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
- `scripts/render_animation.py`: renders the animation to an MP4 (or PNG frames), without changing the file.
- `scripts/render_passes.py`: renders a shot's control passes for diffusion models (depth, normals, segmentation, edges, quick beauty) as PNG sequences and MP4s.
- `scripts/solve_camera.py`: solves a camera (location, rotation, lens) from points measured in a reference image. Plain Python, no Blender needed.

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

Get something on screen early, then refine from renders:

1. **Blockout first.** Within the first couple of minutes, write a rough `build()` with the main masses at real scale and roughly in place, plus ground and camera. Build it and render one view (`--views camera --engine workbench`). A build and a Workbench preview usually take seconds, so a wrong guess costs far less than long up-front planning.
2. **Don't solve the geometry in your head.** Pick plausible numbers and let the previews show what's off. Where parts must meet exactly (feet on pedals, hands on a handle, wheels on the ground), compute the position in the script from the parts it depends on instead of working it out by hand.
3. **Add detail in a few passes.** Replace stand-ins with real forms part by part, rebuilding and checking between passes (section 3), rather than writing the whole detailed scene before the first run.

Modeling guidance:
- The finished model has recognizable, well-proportioned forms with real detail; blocky stand-ins belong only in the blockout pass.
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

Previews default to EEVEE. `--engine workbench` is fastest for checking shapes; it shows each material's viewport color, which the template's `material()` sets (set `mat.diffuse_color` yourself for materials you build another way, or Workbench shows them grey). `--engine cycles` works everywhere and uses the GPU when there is one (Metal, OptiX, CUDA, HIP, oneAPI), falling back to the CPU. Cycles on a GPU often matches EEVEE's speed and handles stone, ambient occlusion and bounce light much better. Keep previews small (640 px) to save time and tokens; look at only the views you need.

`--camera NAME` renders the camera view through a named camera instead of the scene camera, `--aspect H/W` overrides its aspect ratio, and `--frame N` renders that frame of an animation.

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

For animation, keyframe in the build script (set `scene.frame_start`, `frame_end` and `render.fps` there), then render the video with the helper. It writes an H.264 MP4 directly (no ffmpeg needed) and runs Cycles on the GPU:

```bash
"$BLENDER" --background --factory-startup --python "<skill dir>/scripts/render_animation.py" -- \
    --blend scenes/pelican/pelican.blend --out scenes/pelican/renders/shot.mp4 --res 1280 --samples 64
```

Before the full render:
- Check the key moments as stills (`render_preview.py --views camera --frame N` for the first frame, each camera key and the last). This catches a subject that leaves the frame or ends up hidden behind scenery.
- Render a short, low-resolution test clip (`--frames 1-24 --res 480 --samples 16`), and time a few full-quality frames to estimate the whole render. Run long renders in the background.

Animating parts of a model:
- Give each moving group an Empty at its pivot (wheel axle, crank, hip, knee, neck base) and parent the parts to it without moving them: call `bpy.context.view_layer.update()`, save each part's `matrix_world`, set its `parent`, and restore `matrix_world`. Then keyframe the Empty's rotation.
- When one motion drives another (legs on pedals, wheel spin from distance traveled), compute the pose for every frame in the script (for example two-bone IK in the leg's plane) and key every frame, instead of hoping sparse keys line up.
- Set `bpy.context.preferences.edit.keyframe_new_interpolation_type` to `"LINEAR"` before keying every frame and to `"BEZIER"` for sparse eased keys such as a camera move. This sets new keys' interpolation without the F-curve API, which changed in 5.x.
- For a camera move, key the camera's location and `data.lens` at a few frames and aim it with a Track To constraint at a keyed target Empty.

If this skill sits in the AI Scene Generator repo, its camera presets (turntable, slow_zoom, dramatic_reveal, orbit_rise, vertigo, showcase_loop, fly_over, pull_back) can be reused:

```python
import sys
sys.path.insert(0, "<repo>/blender_addon")
import camera_animation
camera_animation.animate_preset("turntable", target=(0, 0, 1.0))   # sets frames and scene camera
```

For an existing rigged model, run `inspect_scene.py` to list its bones, then keyframe `pose.bones["name"].rotation_euler` (set `rotation_mode = "XYZ"` first) in a script that opens the user's file.

## Handing a shot to a diffusion model

Blender is strongest at layout, camera moves, timing and physical plausibility; image and video diffusion models are strongest at surface realism (reflections, dust, foliage, skin). To combine them, don't chase the final look in Blender. Render control passes and let the model paint the surfaces:

```bash
"$BLENDER" --background --factory-startup --python "<skill dir>/scripts/render_passes.py" -- \
    --blend scenes/shot/shot.blend --out scenes/shot/passes --res 1280
```

This writes `depth`, `normal`, `segmentation`, `edges` and a quick EEVEE `beauty` pass, as numbered PNGs and one MP4 each, plus `passes.json` with the frame range, fps, resolution and depth range. EEVEE and Workbench passes take seconds per frame, where a final Cycles render can take many times longer.

- **Depth** is white near and black far, normalized once over the whole shot so it doesn't flicker. The default `--depth-mode inverse` follows MiDaS and Depth Anything; far ground comes out nearly black when the depth range is large, and `--depth-mode linear` keeps more far detail.
- **Normals** are camera-space: red is right, green is up, blue is toward the camera.
- **Segmentation** gives each object a flat random color that stays the same across frames; use it for masks.
- **Edges** come from depth and normal breaks and object boundaries, so there's no texture noise. Swarms of small objects (debris, leaves) show up as dense speckle.
- Pure volume objects (haze, smoke) are left out of the data passes.

Which pass to send depends on the model: depth (or edges) for models that follow structure frame by frame; the beauty MP4 for video-to-video restyling or as a reference video; a single beauty frame as the first frame for image-to-video.

## Working from a reference photo

When the user gives a photo to model from (or asks for something real, like a landmark):

1. **Gather facts, not just pictures.** Look up the real dimensions and plan (height, footprint, number of bays or floors), and one view the photo doesn't show, such as an aerial or a plan, if web tools are available. A single photo fixes proportions from one side only.
2. **Put a camera where the photographer stood.** Add a second camera (keep the scene camera for the final shot), and solve its position rather than guessing (step 3). A stitched panorama or very wide photo needs a panoramic camera: `cam.data.type = "PANO"`, `cam.data.panorama_type = "EQUIRECTANGULAR"` (or `"CENTRAL_CYLINDRICAL"`), and `longitude_min/max` and `latitude_min/max` in radians to match the photo's horizontal and vertical span. Panoramic cameras render in Cycles only; `render_preview.py` switches to Cycles for them.
3. **Solve the camera from measurements.** Pick 6 or more features in the reference whose 3D positions you know in the model: building corners, where a wall meets the ground, a car's center, the top of a post. Spread them across the frame and at different depths. Measure each as a frame fraction (x from the left edge, y from the top), put them in a JSON file, and run:

   ```bash
   python3 "<skill dir>/scripts/solve_camera.py" points.json --width 1920
   ```

   It prints `cam.location`, `cam.rotation_euler` and `cam.data.lens` ready to paste, plus each point's error in pixels. An error under about 0.5% of the frame width is a good fit. Fix the lens with `--lens` when it's known. (Not for panoramic cameras.)
4. **When the fit stays bad, question the scene, not the camera.** A persistent error means an assumption in the model is wrong: a size, where something is, or timing. Make the doubtful quantity a parameter and fit it along with the camera (copy the solver's approach into a scratch script). Example: in a car-jump shot, nothing fit until the car's speed was a free parameter; the shot turned out to be in slow motion.
5. **For a moving shot,** solve two or three key frames, then build the camera path between them (keyframes, or a path relative to the moving subject). Render the same frame numbers as the reference and compare them side by side (ffmpeg `hstack`/`vstack` makes quick comparison sheets and videos).
6. **Compare and refit.** Render that camera at the photo's aspect (`--views camera --camera NAME --aspect H/W`) and compare it with the photo feature by feature: where the horizon falls, and the image height of known levels (floors, terraces, rooflines). When they disagree, fix the model's proportions or the camera position, not the photo camera's lens.
7. **Then frame the real shot.** Once the match camera agrees with the photo, compose the final shot with the scene camera. It doesn't need to copy the photo.

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
