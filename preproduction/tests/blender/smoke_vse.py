"""Blender smoke test for the HelloWorld OTIO add-on (run inside Blender, not pytest).

  blender --background --factory-startup --python tests/blender/smoke_vse.py -- \
      --otio cut.otio --out OUTDIR [--deps DIR_WITH_OPENTIMELINEIO] [--render 1,40,100]

Imports the cut, checks the strips, swaps every shot to boards and back to the most finished
stage, exports to OUTDIR/roundtrip.otio, saves OUTDIR/smoke.blend and renders the listed frames.
Exits non-zero on failure.
"""

import argparse
import json
import os
import sys
import warnings

import bpy

warnings.simplefilter("error", DeprecationWarning)  # fail on APIs Blender plans to remove

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument("--otio", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--deps")
parser.add_argument("--render", default="")
args = parser.parse_args(argv)

if args.deps:
    sys.path.insert(0, args.deps)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "blender"))
import helloworld_otio  # noqa: E402

helloworld_otio.register()
os.makedirs(args.out, exist_ok=True)
failures = []


def check(cond, message):
    print(("ok   " if cond else "FAIL ") + message)
    if not cond:
        failures.append(message)


scene = bpy.context.scene
result = bpy.ops.helloworld.import_otio(filepath=os.path.abspath(args.otio))
check(result == {"FINISHED"}, "import operator finished")
vse = helloworld_otio._vse()
strips = sorted(vse.all_strips(scene), key=lambda s: (s.channel, vse.strip_start(s)))
for s in strips:
    print(f"  ch{s.channel} {s.type:6} {vse.strip_start(s):5}-{vse.strip_end(s):5} {s.name:22} stage={s.get('hw_stage', '-')}")
media = [s for s in strips if not s.get("hw_label")]
labels = [s for s in strips if s.get("hw_label")]
check(len(labels) > 0, f"{len(labels)} label strips")
check(all(vse.strip_end(s) > vse.strip_start(s) for s in media), "every strip has length")
check(scene.frame_end - scene.frame_start + 1 == max(vse.strip_end(s) for s in media) - scene.frame_start, "scene range matches the cut")
check(len(scene.timeline_markers) > 0, f"{len(scene.timeline_markers)} scene markers")

before = {(s.get("hw_clip"), vse.strip_start(s)) for s in media}
imported_stage = {s.get("hw_clip"): s.get("hw_stage") for s in media}
bpy.ops.helloworld.swap_stage(stage="board")
boards = [s for s in vse.all_strips(scene) if not s.get("hw_label")]
check(all(s.get("hw_stage") == "board" for s in boards), "all shots swapped to boards")
# Back up the ladder, least finished first, so each shot ends on its most finished stage as on import.
for stage in ("previs", "final"):
    if stage in imported_stage.values():
        bpy.ops.helloworld.swap_stage(stage=stage)
after = [s for s in vse.all_strips(scene) if not s.get("hw_label")]
check({s.get("hw_clip") for s in after} == {c for c, _ in before}, "same shots after swapping back")
back_stage = {s.get("hw_clip"): s.get("hw_stage") for s in after}
check(back_stage == imported_stage, f"every shot back on its imported stage {sorted(set(imported_stage.values()))}")
check(min(vse.strip_start(s) for s in after) == min(f for _, f in before), "cut still starts where it did")

out_otio = os.path.join(args.out, "roundtrip.otio")
bpy.ops.helloworld.export_otio(filepath=out_otio)
import opentimelineio as otio  # noqa: E402

source = otio.adapters.read_from_file(args.otio)
back = otio.adapters.read_from_file(out_otio)
src_clips = [(c.name, c.duration().value) for c in source.find_clips()]
back_clips = [(c.name, c.duration().value) for c in back.find_clips()]
print("  source  ", src_clips)
print("  exported", back_clips)
check(sorted(src_clips) == sorted(back_clips), "round trip keeps every clip and its length")
check(all("helloworld" in c.metadata for c in back.find_clips()), "round trip keeps helloworld metadata")
check(all("board" in c.media_references() for c in back.find_clips()), "round trip keeps board media")

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.out, "smoke.blend"))
scene.render.resolution_percentage = 50
scene.render.image_settings.file_format = "PNG"
for frame in [int(f) for f in args.render.split(",") if f.strip()]:
    scene.frame_set(frame)
    scene.render.filepath = os.path.join(args.out, f"frame_{frame:05d}.png")
    bpy.ops.render.render(write_still=True)
    print("  rendered", scene.render.filepath)

print(json.dumps({"failures": failures}))
sys.exit(1 if failures else 0)
