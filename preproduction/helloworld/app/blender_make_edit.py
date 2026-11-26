"""Runs inside Blender: import a cut with the HelloWorld OTIO add-on and save it as a .blend.

  Blender --background --app-template Video_Editing --python blender_make_edit.py -- --otio cut.otio --save edit.blend
"""

import argparse
import sys

import addon_utils
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument("--otio", required=True)
parser.add_argument("--save", required=True)
args = parser.parse_args(argv)

module = next((m.__name__ for m in addon_utils.modules() if m.__name__.endswith("helloworld_otio")), None)
if module is None:
    sys.exit("The HelloWorld OTIO add-on isn't installed in this Blender (use Set up in the HelloWorld app).")
addon_utils.enable(module, default_set=True)

result = bpy.ops.helloworld.import_otio(filepath=args.otio)
if result != {"FINISHED"}:
    sys.exit(f"Import failed: {result}")
bpy.ops.wm.save_as_mainfile(filepath=args.save)
print(f"saved {args.save}")
