# SPDX-License-Identifier: GPL-3.0-or-later
"""HelloWorld OTIO: bring an OpenTimelineIO cut into Blender's Video Sequence Editor.

Sequencer > Sidebar > HelloWorld, or File > Import / Export > OpenTimelineIO (HelloWorld).

* Import an .otio timeline (from Open Shot Designer via HelloWorld, Kitsu, Resolve, Premiere ...).
* Swap shots between their board, previs and final media without losing edits.
* Export the edit back to .otio for Kitsu, AYON or another editor.

Needs the ``opentimelineio`` Python package; the panel offers to install it if it's missing.
"""

bl_info = {  # legacy add-on install (Blender < 4.2); extensions read blender_manifest.toml
    "name": "HelloWorld OTIO",
    "author": "HelloWorld contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "Sequencer > Sidebar > HelloWorld",
    "description": "Import and export OpenTimelineIO cuts; swap shots between boards, previs and finals",
    "category": "Sequencer",
}

import importlib
import json
import os
import subprocess
import sys

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

STAGES = [
    ("board", "Boards", "Storyboard frames"),
    ("previs", "Previs", "Previs renders and playblasts"),
    ("final", "Final", "Final renders"),
]


# -- dependency handling ------------------------------------------------------------------------


def _deps_dir() -> str:
    try:
        return bpy.utils.extension_path_user(__package__, path="site-packages", create=True)
    except Exception:  # legacy add-on, or outside an extension repository
        path = os.path.join(bpy.utils.user_resource("SCRIPTS", path="modules"), "helloworld_deps")
        os.makedirs(path, exist_ok=True)
        return path


def otio_available() -> bool:
    deps = _deps_dir()
    if deps not in sys.path:
        sys.path.append(deps)
    try:
        importlib.import_module("opentimelineio")
        return True
    except ImportError:
        return False


def _vse():
    from . import vse_otio

    return vse_otio


class HELLOWORLD_OT_install_otio(bpy.types.Operator):
    bl_idname = "helloworld.install_otio"
    bl_label = "Install OpenTimelineIO"
    bl_description = "Download the opentimelineio package from PyPI into this add-on's folder (needs internet)"

    def execute(self, context):
        if not bpy.app.online_access:
            self.report({"ERROR"}, "Allow Online Access in Preferences > System first")
            return {"CANCELLED"}
        target = _deps_dir()
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
               "--target", target, "opentimelineio>=0.17"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.report({"ERROR"}, "pip failed: " + (result.stderr.strip().splitlines() or ["unknown error"])[-1])
            return {"CANCELLED"}
        importlib.invalidate_caches()
        if not otio_available():
            self.report({"ERROR"}, "Installed, but opentimelineio still can't be imported; restart Blender")
            return {"CANCELLED"}
        self.report({"INFO"}, "OpenTimelineIO installed")
        return {"FINISHED"}


# -- operators ----------------------------------------------------------------------------------


def _need_otio(op) -> bool:
    if otio_available():
        return True
    op.report({"ERROR"}, "OpenTimelineIO is not installed (Sequencer > Sidebar > HelloWorld)")
    return False


class HELLOWORLD_OT_import_otio(bpy.types.Operator, ImportHelper):
    bl_idname = "helloworld.import_otio"
    bl_label = "Import OpenTimelineIO"
    bl_description = "Build the cut in the Video Sequence Editor from an OpenTimelineIO file"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".otio"
    filter_glob: StringProperty(default="*.otio;*.otioz;*.otiod;*.edl;*.xml;*.fcpxml", options={"HIDDEN"})

    stage: EnumProperty(
        name="Show",
        items=[("best", "Most finished", "Final if there is one, else previs, else the boards")] + STAGES,
        default="best",
    )
    first_channel: IntProperty(name="First channel", default=1, min=1, max=128)
    start_frame: IntProperty(name="Start frame", default=1)
    labels: BoolProperty(name="Shot labels", description="Add text strips with shot number, lens and description", default=True)
    set_scene: BoolProperty(name="Set frame rate, range and format", default=True)
    replace: BoolProperty(name="Replace earlier import", description="Remove strips imported before from this file", default=True)

    def execute(self, context):
        if not _need_otio(self):
            return {"CANCELLED"}
        vse = _vse()
        prefer = vse.DEFAULT_PREFER if self.stage == "best" else (self.stage,) + vse.DEFAULT_PREFER
        report = vse.import_timeline(
            context, self.filepath, prefer=prefer, first_channel=self.first_channel, start_frame=self.start_frame,
            labels=self.labels, set_scene=self.set_scene, replace=self.replace,
        )
        context.scene["hw_last_otio"] = self.filepath
        self.report({"INFO"}, "Imported " + report.summary())
        return {"FINISHED"}


class HELLOWORLD_OT_swap_stage(bpy.types.Operator):
    bl_idname = "helloworld.swap_stage"
    bl_label = "Show Stage"
    bl_description = "Swap shots to their boards, previs or final media, keeping their place in the cut"
    bl_options = {"REGISTER", "UNDO"}

    stage: EnumProperty(name="Stage", items=STAGES)
    selected_only: BoolProperty(name="Selected strips only", default=False)

    def execute(self, context):
        if not _need_otio(self):
            return {"CANCELLED"}
        strips = _vse().all_strips(context.scene)
        if self.selected_only:
            strips = [s for s in strips if s.select]
        swapped, missing = _vse().swap_stage(context, strips, self.stage)
        self.report({"INFO"}, f"{swapped} shots now show {self.stage}; {missing} have no {self.stage} media")
        return {"FINISHED"}


class HELLOWORLD_OT_export_otio(bpy.types.Operator, ExportHelper):
    bl_idname = "helloworld.export_otio"
    bl_label = "Export OpenTimelineIO"
    bl_description = "Write the Video Sequence Editor cut to an OpenTimelineIO file"

    filename_ext = ".otio"
    filter_glob: StringProperty(default="*.otio", options={"HIDDEN"})
    relative_paths: BoolProperty(name="Relative media paths", default=True)

    def execute(self, context):
        if not _need_otio(self):
            return {"CANCELLED"}
        count = _vse().export_timeline(context, self.filepath, relative_paths=self.relative_paths)
        self.report({"INFO"}, f"Exported {count} clips to {os.path.basename(self.filepath)}")
        return {"FINISHED"}


# -- UI -----------------------------------------------------------------------------------------


class HELLOWORLD_PT_sequencer(bpy.types.Panel):
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "HelloWorld"
    bl_label = "HelloWorld"

    def draw(self, context):
        layout = self.layout
        if not otio_available():
            layout.label(text="OpenTimelineIO is not installed", icon="ERROR")
            layout.operator(HELLOWORLD_OT_install_otio.bl_idname, icon="IMPORT")
            return
        col = layout.column(align=True)
        col.operator(HELLOWORLD_OT_import_otio.bl_idname, icon="IMPORT")
        col.operator(HELLOWORLD_OT_export_otio.bl_idname, icon="EXPORT")

        layout.label(text="Show in the cut:")
        row = layout.row(align=True)
        for key, label, _ in STAGES:
            op = row.operator(HELLOWORLD_OT_swap_stage.bl_idname, text=label)
            op.stage = key

        sed = context.scene.sequence_editor
        strip = getattr(sed, "active_strip", None) if sed else None
        if strip is None or "hw_meta" not in strip:
            return
        meta = json.loads(strip["hw_meta"])
        box = layout.box()
        box.label(text=f"{meta.get('sequence', '')} {meta.get('shot', '')}  (slate {meta.get('shot_number', '?')})", icon="SEQUENCE")
        for label, key in (("Size", "size"), ("Lens", "lens_mm"), ("Angle", "angle"), ("Move", "movement"),
                           ("Camera", "camera"), ("Status", "status")):
            value = meta.get(key)
            if value:
                box.label(text=f"{label}: {value:g}mm" if key == "lens_mm" else f"{label}: {value}")
        if meta.get("description"):
            box.label(text=str(meta["description"])[:60])
        box.label(text=f"Showing: {strip.get('hw_stage') or 'placeholder'}")
        stages = json.loads(strip.get("hw_media", "{}"))
        box.label(text="Has: " + (", ".join(sorted(stages)) or "no media"))


def menu_import(self, context):
    self.layout.operator(HELLOWORLD_OT_import_otio.bl_idname, text="OpenTimelineIO (HelloWorld)")


def menu_export(self, context):
    self.layout.operator(HELLOWORLD_OT_export_otio.bl_idname, text="OpenTimelineIO (HelloWorld)")


classes = (
    HELLOWORLD_OT_install_otio,
    HELLOWORLD_OT_import_otio,
    HELLOWORLD_OT_swap_stage,
    HELLOWORLD_OT_export_otio,
    HELLOWORLD_PT_sequencer,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
