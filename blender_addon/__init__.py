"""AI Scene Generator — Blender addon that generates 3D scenes from text prompts.

Pipeline: LLM (Claude or Gemini) → World Model → Procedural Materials → Blender Scene
Includes camera animation presets/LLM and reference video export.
"""

bl_info = {
    "name": "AI Scene Generator",
    "author": "Render3D Pipeline",
    "version": (2, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > AI Scene",
    "description": "Generate 3D scenes, camera animations, and reference videos from text",
    "category": "3D View",
}

if "bpy" in locals():
    import importlib
    importlib.reload(llm_client)
    importlib.reload(scene_builder)
    importlib.reload(world_model)
    importlib.reload(camera_animation)
    importlib.reload(video_export)
else:
    from . import camera_animation, llm_client, scene_builder, video_export, world_model

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class AIScenePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    llm_provider: EnumProperty(
        name="LLM Provider",
        items=[
            ("claude", "Claude (Anthropic)", "Use Anthropic's Claude API"),
            ("gemini", "Gemini (Google)", "Use Google's Gemini API"),
        ],
        default="claude",
    )

    api_key: StringProperty(
        name="Anthropic API Key",
        description="API key for Claude (or set ANTHROPIC_API_KEY env var)",
        subtype="PASSWORD",
        default="",
    )

    workspace_id: StringProperty(
        name="Workspace ID",
        description="Anthropic workspace ID (required for org keys with multiple workspaces)",
        default="",
    )

    gemini_api_key: StringProperty(
        name="Google API Key",
        description="API key for Gemini (or set GOOGLE_API_KEY env var)",
        subtype="PASSWORD",
        default="",
    )

    model: EnumProperty(
        name="Claude Model",
        items=[
            ("claude-sonnet-5", "Claude Sonnet 5", "Fast, cost-effective"),
            ("claude-opus-5", "Claude Opus 5", "Most capable"),
            ("claude-haiku-4-5", "Claude Haiku 4.5", "Fastest, lightweight tasks"),
        ],
        default="claude-sonnet-5",
    )

    gemini_model: EnumProperty(
        name="Gemini Model",
        items=[
            ("gemini-3.8-flash", "Gemini 3.8 Flash", "Latest, most capable Flash"),
            ("gemini-3.6-flash", "Gemini 3.6 Flash", "Improved code and agentic planning"),
            ("gemini-3.5-flash", "Gemini 3.5 Flash", "Frontier-class performance"),
            ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "Fastest, low-cost"),
            ("gemini-2.5-pro", "Gemini 2.5 Pro", "Legacy Pro model"),
            ("gemini-2.5-flash", "Gemini 2.5 Flash", "Legacy Flash model"),
        ],
        default="gemini-3.8-flash",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "llm_provider")

        if self.llm_provider == "claude":
            layout.prop(self, "api_key")
            layout.prop(self, "workspace_id")
            layout.prop(self, "model")
        else:
            layout.prop(self, "gemini_api_key")
            layout.prop(self, "gemini_model")


# ---------------------------------------------------------------------------
# Scene properties
# ---------------------------------------------------------------------------

class AISceneProperties(bpy.types.PropertyGroup):
    # -- Scene generation --
    prompt: StringProperty(
        name="Prompt",
        description="Describe the scene you want to generate",
        default="a medieval stone tower on a grassy hill",
    )

    clear_scene: BoolProperty(
        name="Clear Scene",
        description="Remove existing objects before generating",
        default=True,
    )

    add_ground: BoolProperty(
        name="Ground Plane",
        description="Add a ground plane to the scene",
        default=True,
    )

    render_engine: EnumProperty(
        name="Render Engine",
        items=[
            ("CYCLES", "Cycles", "Path-traced rendering"),
            ("BLENDER_EEVEE_NEXT", "EEVEE", "Real-time rendering"),
        ],
        default="BLENDER_EEVEE_NEXT",
    )

    texture_size: IntProperty(
        name="Texture Size",
        description="Resolution for generated textures",
        default=1024,
        min=256,
        max=4096,
    )

    use_hdri: BoolProperty(
        name="HDRI Lighting",
        description="Use HDRI environment lighting",
        default=True,
    )

    status: StringProperty(name="Status", default="Ready")
    is_running: BoolProperty(name="Running", default=False)

    # -- Camera animation --
    cam_prompt: StringProperty(
        name="Camera Move",
        description="Describe the camera motion (or use a preset below)",
        default="slow orbit rising from ground level",
    )

    cam_preset: EnumProperty(
        name="Preset",
        items=[
            ("CUSTOM", "Custom (LLM)", "Describe camera move in text"),
            ("turntable", "Turntable", "360-degree orbit"),
            ("slow_zoom", "Slow Zoom", "Cinematic push-in"),
            ("dramatic_reveal", "Dramatic Reveal", "Low-to-high crane"),
            ("orbit_rise", "Orbit Rise", "Orbit while rising"),
            ("vertigo", "Vertigo", "Dolly zoom effect"),
            ("showcase_loop", "Showcase Loop", "Speed-ramped dynamic loop"),
            ("fly_over", "Fly Over", "Arc over the scene"),
            ("pull_back", "Pull Back", "Reveal pull-out"),
        ],
        default="turntable",
    )

    cam_duration: FloatProperty(
        name="Duration (s)",
        description="Animation duration in seconds",
        default=5.0,
        min=1.0,
        max=30.0,
    )

    cam_fps: IntProperty(
        name="FPS",
        default=24,
        min=12,
        max=60,
    )

    # -- Video export --
    video_quality: EnumProperty(
        name="Quality",
        items=[
            ("preview", "Preview (50%)", "Fast, low-res reference"),
            ("draft", "Draft (75%)", "Medium quality"),
            ("final", "Final (100%)", "Full resolution"),
        ],
        default="preview",
    )

    video_format: EnumProperty(
        name="Format",
        items=[
            ("mp4", "MP4", "H.264 compressed video"),
            ("mov", "MOV (ProRes)", "ProRes 4444 with alpha"),
        ],
        default="mp4",
    )

    video_transparent: BoolProperty(
        name="Transparent Background",
        description="Render with transparent background (MOV only)",
        default=False,
    )

    video_blockout: BoolProperty(
        name="Blockout Mode",
        description="Replace materials with flat grey for reference render",
        default=False,
    )

    video_use_viewport: BoolProperty(
        name="Viewport Render",
        description="Use fast viewport render instead of full render",
        default=True,
    )

    video_output: StringProperty(
        name="Output Dir",
        description="Output directory for rendered video",
        default="//render_output",
        subtype="DIR_PATH",
    )


# ---------------------------------------------------------------------------
# Scene generation operators
# ---------------------------------------------------------------------------

class AISCENE_OT_generate(bpy.types.Operator):
    bl_idname = "aiscene.generate"
    bl_label = "Generate Scene"
    bl_description = "Generate a 3D scene from the text prompt"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.ai_scene
        prefs = context.preferences.addons[__package__].preferences

        props.status = "Parsing scene with LLM..."
        props.is_running = True

        try:
            provider = prefs.llm_provider
            if provider == "claude":
                api_key = prefs.api_key or None
                model = prefs.model
                workspace_id = prefs.workspace_id or None
            else:
                api_key = prefs.gemini_api_key or None
                model = prefs.gemini_model
                workspace_id = None
            client = llm_client.LLMClient(
                provider=provider, api_key=api_key, model=model, workspace_id=workspace_id,
            )
            scene_data = client.parse_scene(props.prompt)
        except Exception as e:
            props.status = f"LLM error: {e}"
            props.is_running = False
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        props.status = "Applying world model..."
        try:
            scene_data = world_model.process(scene_data)
        except Exception as e:
            props.status = f"World model error: {e}"
            props.is_running = False
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        props.status = "Building Blender scene..."
        try:
            if props.clear_scene:
                scene_builder.clear_scene()

            scene_builder.build_scene(
                scene_data,
                add_ground=props.add_ground,
                texture_size=props.texture_size,
            )
            scene_builder.setup_lighting(scene_data.get("lights", []), use_hdri=props.use_hdri)
            scene_builder.setup_camera(scene_data.get("camera", {}))
            context.scene.render.engine = props.render_engine

        except Exception as e:
            props.status = f"Build error: {e}"
            props.is_running = False
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        obj_count = len(scene_data.get("objects", []))
        props.status = f"Done — {obj_count} objects created"
        props.is_running = False
        self.report({"INFO"}, f"Generated scene with {obj_count} objects")
        return {"FINISHED"}


class AISCENE_OT_quick_generate(bpy.types.Operator):
    bl_idname = "aiscene.quick_generate"
    bl_label = "Quick Generate (No LLM)"
    bl_description = "Generate a test scene without calling the LLM API"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.ai_scene

        test_scene = {
            "name": "test_scene",
            "objects": [
                {
                    "name": "tower_base", "primitive": "cylinder",
                    "position": [0, 0, 2.5], "rotation": [0, 0, 0], "scale": [1.5, 1.5, 5],
                    "material": {"color": [0.55, 0.55, 0.5], "roughness": 0.85, "texture_prompt": "weathered stone wall"},
                },
                {
                    "name": "tower_roof", "primitive": "cone",
                    "position": [0, 0, 6], "rotation": [0, 0, 0], "scale": [2, 2, 2.5],
                    "material": {"color": [0.45, 0.15, 0.1], "roughness": 0.7, "texture_prompt": "clay roof tiles"},
                },
                {
                    "name": "hill", "primitive": "sphere",
                    "position": [0, 0, -1], "rotation": [0, 0, 0], "scale": [8, 8, 3],
                    "material": {"color": [0.2, 0.5, 0.15], "roughness": 0.95, "texture_prompt": "grassy hillside"},
                },
            ],
            "lights": [
                {"type": "SUN", "direction": [0.5, 0.3, -1], "color": [1, 0.95, 0.9], "intensity": 3.0},
                {"type": "POINT", "position": [-3, 4, 6], "color": [0.8, 0.85, 1.0], "intensity": 200},
            ],
            "camera": {"position": [8, -6, 5], "target": [0, 0, 2.5], "fov": 50},
            "sky_color": [0.529, 0.808, 0.922],
        }

        test_scene = world_model.process(test_scene)

        if props.clear_scene:
            scene_builder.clear_scene()

        scene_builder.build_scene(test_scene, add_ground=props.add_ground, texture_size=props.texture_size)
        scene_builder.setup_lighting(test_scene["lights"], use_hdri=props.use_hdri)
        scene_builder.setup_camera(test_scene["camera"])
        context.scene.render.engine = props.render_engine

        props.status = f"Test scene built — {len(test_scene['objects'])} objects"
        self.report({"INFO"}, "Test scene generated")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Camera animation operators
# ---------------------------------------------------------------------------

class AISCENE_OT_animate_camera(bpy.types.Operator):
    bl_idname = "aiscene.animate_camera"
    bl_label = "Animate Camera"
    bl_description = "Create a keyframed camera animation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.ai_scene
        prefs = context.preferences.addons[__package__].preferences

        target = self._find_scene_center(context)

        if props.cam_preset == "CUSTOM":
            props.status = "Generating camera move with LLM..."
            try:
                provider = prefs.llm_provider
                if provider == "claude":
                    api_key = prefs.api_key or None
                    model = prefs.model
                    workspace_id = prefs.workspace_id or None
                else:
                    api_key = prefs.gemini_api_key or None
                    model = prefs.gemini_model
                    workspace_id = None
                camera_animation.animate_from_prompt(
                    props.cam_prompt,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    workspace_id=workspace_id,
                )
                props.status = "Camera animation created (LLM)"
            except Exception as e:
                props.status = f"Camera error: {e}"
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}
        else:
            try:
                camera_animation.animate_preset(
                    props.cam_preset,
                    target=target,
                    fps=props.cam_fps,
                )
                props.status = f"Camera: {props.cam_preset} ({props.cam_duration}s)"
            except Exception as e:
                props.status = f"Camera error: {e}"
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}

        self.report({"INFO"}, "Camera animation created")
        return {"FINISHED"}

    def _find_scene_center(self, context) -> tuple[float, float, float]:
        mesh_objects = [o for o in context.scene.objects if o.type == "MESH" and o.name != "Ground"]
        if not mesh_objects:
            return (0, 0, 1.5)

        avg = [0.0, 0.0, 0.0]
        for obj in mesh_objects:
            avg[0] += obj.location.x
            avg[1] += obj.location.y
            avg[2] += obj.location.z
        n = len(mesh_objects)
        return (avg[0] / n, avg[1] / n, avg[2] / n)


class AISCENE_OT_preview_camera(bpy.types.Operator):
    bl_idname = "aiscene.preview_camera"
    bl_label = "Preview"
    bl_description = "Play the camera animation in the viewport"

    def execute(self, context):
        context.scene.frame_set(context.scene.frame_start)
        bpy.ops.screen.animation_play()
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Video export operators
# ---------------------------------------------------------------------------

class AISCENE_OT_export_video(bpy.types.Operator):
    bl_idname = "aiscene.export_video"
    bl_label = "Export Reference Video"
    bl_description = "Render the scene as a reference video clip"

    def execute(self, context):
        props = context.scene.ai_scene
        props.status = "Rendering reference video..."

        original_mats = None
        if props.video_blockout:
            original_mats = video_export.setup_blockout_materials()

        try:
            exporter = video_export.VideoExporter(
                output_dir=props.video_output,
                resolution=(context.scene.render.resolution_x, context.scene.render.resolution_y),
                fps=props.cam_fps,
            )

            output_path = exporter.export_reference(
                quality=props.video_quality,
                format=props.video_format,
                use_viewport=props.video_use_viewport,
                transparent=props.video_transparent,
            )

            props.status = f"Video exported: {output_path}"
            self.report({"INFO"}, f"Reference video: {output_path}")

        except Exception as e:
            props.status = f"Export error: {e}"
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        finally:
            if original_mats is not None:
                video_export.restore_materials(original_mats)

        return {"FINISHED"}


class AISCENE_OT_snapshot(bpy.types.Operator):
    bl_idname = "aiscene.snapshot"
    bl_label = "Snapshot Current Frame"
    bl_description = "Render a single frame at current position"

    def execute(self, context):
        props = context.scene.ai_scene

        exporter = video_export.VideoExporter(
            output_dir=props.video_output,
            resolution=(context.scene.render.resolution_x, context.scene.render.resolution_y),
        )

        path = exporter.export_single_frame(quality=props.video_quality)
        props.status = f"Snapshot: {path}"
        self.report({"INFO"}, f"Saved: {path}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# UI Panels
# ---------------------------------------------------------------------------

class AISCENE_PT_scene_panel(bpy.types.Panel):
    bl_label = "Scene Builder"
    bl_idname = "AISCENE_PT_scene_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AI Scene"

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_scene

        layout.label(text="Scene Description:")
        layout.prop(props, "prompt", text="")

        box = layout.box()
        box.label(text="Settings", icon="PREFERENCES")
        box.prop(props, "clear_scene")
        box.prop(props, "add_ground")
        box.prop(props, "render_engine")
        box.prop(props, "texture_size")
        box.prop(props, "use_hdri")

        layout.separator()

        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("aiscene.generate", icon="SCENE_DATA")
        row.enabled = not props.is_running

        layout.operator("aiscene.quick_generate", icon="MESH_MONKEY")


class AISCENE_PT_camera_panel(bpy.types.Panel):
    bl_label = "Camera Animation"
    bl_idname = "AISCENE_PT_camera_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AI Scene"

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_scene

        layout.prop(props, "cam_preset")

        if props.cam_preset == "CUSTOM":
            layout.label(text="Describe the camera move:")
            layout.prop(props, "cam_prompt", text="")

        row = layout.row(align=True)
        row.prop(props, "cam_duration")
        row.prop(props, "cam_fps")

        layout.separator()

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("aiscene.animate_camera", icon="ANIM")

        layout.operator("aiscene.preview_camera", icon="PLAY")


class AISCENE_PT_video_panel(bpy.types.Panel):
    bl_label = "Video Export"
    bl_idname = "AISCENE_PT_video_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AI Scene"

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_scene

        box = layout.box()
        box.label(text="Render Settings", icon="RENDER_ANIMATION")
        box.prop(props, "video_quality")
        box.prop(props, "video_format")
        box.prop(props, "video_use_viewport")
        box.prop(props, "video_blockout")

        if props.video_format == "mov":
            box.prop(props, "video_transparent")

        layout.prop(props, "video_output")

        layout.separator()

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("aiscene.export_video", icon="RENDER_ANIMATION")

        layout.operator("aiscene.snapshot", icon="RENDER_STILL")


class AISCENE_PT_status_panel(bpy.types.Panel):
    bl_label = "Status"
    bl_idname = "AISCENE_PT_status_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AI Scene"

    def draw(self, context):
        props = context.scene.ai_scene
        if props.status:
            self.layout.label(text=props.status, icon="INFO")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    AIScenePreferences,
    AISceneProperties,
    AISCENE_OT_generate,
    AISCENE_OT_quick_generate,
    AISCENE_OT_animate_camera,
    AISCENE_OT_preview_camera,
    AISCENE_OT_export_video,
    AISCENE_OT_snapshot,
    AISCENE_PT_scene_panel,
    AISCENE_PT_camera_panel,
    AISCENE_PT_video_panel,
    AISCENE_PT_status_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ai_scene = bpy.props.PointerProperty(type=AISceneProperties)


def unregister():
    del bpy.types.Scene.ai_scene
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
