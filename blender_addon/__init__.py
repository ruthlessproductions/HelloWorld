"""AI Scene Generator — Blender addon that generates 3D scenes from text prompts.

Pipeline: LLM (Claude) → World Model → Procedural Materials → Blender Scene
"""

bl_info = {
    "name": "AI Scene Generator",
    "author": "Render3D Pipeline",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > AI Scene",
    "description": "Generate 3D scenes from text using LLM, world model, and procedural materials",
    "category": "3D View",
}

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from . import llm_client, scene_builder, world_model


class AIScenePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    api_key: StringProperty(
        name="Anthropic API Key",
        description="API key for Claude (or set ANTHROPIC_API_KEY env var)",
        subtype="PASSWORD",
        default="",
    )

    model: EnumProperty(
        name="Model",
        items=[
            ("claude-sonnet-4-20250514", "Claude Sonnet", "Fast, cost-effective"),
            ("claude-opus-4-20250514", "Claude Opus", "Most capable"),
        ],
        default="claude-sonnet-4-20250514",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "api_key")
        layout.prop(self, "model")


class AISceneProperties(bpy.types.PropertyGroup):
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
            api_key = prefs.api_key or None
            client = llm_client.ClaudeClient(api_key=api_key, model=prefs.model)
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
                    "name": "tower_base",
                    "primitive": "cylinder",
                    "position": [0, 0, 2.5],
                    "rotation": [0, 0, 0],
                    "scale": [1.5, 1.5, 5],
                    "material": {
                        "color": [0.55, 0.55, 0.5],
                        "roughness": 0.85,
                        "metallic": 0.0,
                        "texture_prompt": "weathered stone wall",
                    },
                },
                {
                    "name": "tower_roof",
                    "primitive": "cone",
                    "position": [0, 0, 6],
                    "rotation": [0, 0, 0],
                    "scale": [2, 2, 2.5],
                    "material": {
                        "color": [0.45, 0.15, 0.1],
                        "roughness": 0.7,
                        "metallic": 0.0,
                        "texture_prompt": "clay roof tiles",
                    },
                },
                {
                    "name": "hill",
                    "primitive": "sphere",
                    "position": [0, 0, -1],
                    "rotation": [0, 0, 0],
                    "scale": [8, 8, 3],
                    "material": {
                        "color": [0.2, 0.5, 0.15],
                        "roughness": 0.95,
                        "metallic": 0.0,
                        "texture_prompt": "grassy hillside",
                    },
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


class AISCENE_PT_main_panel(bpy.types.Panel):
    bl_label = "AI Scene Generator"
    bl_idname = "AISCENE_PT_main_panel"
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

        if props.status:
            box = layout.box()
            box.label(text=props.status, icon="INFO")


classes = (
    AIScenePreferences,
    AISceneProperties,
    AISCENE_OT_generate,
    AISCENE_OT_quick_generate,
    AISCENE_PT_main_panel,
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
