"""LLM-based scene parser: converts natural language descriptions into structured Scene objects."""

from __future__ import annotations

import json
import logging
from typing import Optional

import anthropic

from render3d.schema import (
    Camera,
    Color,
    Light,
    LightType,
    Material,
    Primitive,
    Scene,
    SceneObject,
    Vec3,
)

logger = logging.getLogger(__name__)

SCENE_PARSE_SYSTEM = """You are a 3D scene architect. Given a natural language description, output a JSON scene specification.

Return ONLY valid JSON with this exact structure:
{
  "name": "scene_name",
  "objects": [
    {
      "name": "object_name",
      "primitive": "cube|sphere|cylinder|cone|plane|torus",
      "position": [x, y, z],
      "rotation": [rx, ry, rz],
      "scale": [sx, sy, sz],
      "material": {
        "color": [r, g, b],
        "roughness": 0.0-1.0,
        "metallic": 0.0-1.0,
        "texture_prompt": "optional description for texture generation"
      },
      "children": []
    }
  ],
  "lights": [
    {
      "type": "point|directional|ambient",
      "position": [x, y, z],
      "color": [r, g, b],
      "intensity": 1.0,
      "direction": [dx, dy, dz]
    }
  ],
  "camera": {
    "position": [x, y, z],
    "target": [tx, ty, tz],
    "fov": 60.0
  },
  "ground_plane": true,
  "sky_color": [r, g, b]
}

Rules:
- Y-axis is up. Ground is at y=0.
- Use realistic proportions (1 unit ≈ 1 meter).
- Color values are 0.0-1.0 floats.
- Decompose complex objects into primitives (a table = a flat cube top + 4 cylinder legs).
- Always include at least one light source.
- Position the camera to frame the full scene.
- Set texture_prompt when a surface needs a generated texture (e.g., "weathered stone wall", "wooden planks").
- Children inherit parent transforms.
"""


class SceneParser:
    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic()
        self.model = model

    def parse(self, prompt: str, max_tokens: int = 4096) -> Scene:
        logger.info("Parsing scene from prompt: %s", prompt[:80])

        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=SCENE_PARSE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]

        data = json.loads(text)
        return self._build_scene(data)

    def _build_scene(self, data: dict) -> Scene:
        objects = [self._build_object(obj) for obj in data.get("objects", [])]
        lights = [self._build_light(lt) for lt in data.get("lights", [])]

        cam_data = data.get("camera", {})
        camera = Camera(
            position=Vec3.from_list(cam_data.get("position", [5, 5, 5])),
            target=Vec3.from_list(cam_data.get("target", [0, 0, 0])),
            fov=cam_data.get("fov", 60.0),
        )

        sky = data.get("sky_color", [0.529, 0.808, 0.922])

        return Scene(
            name=data.get("name", "untitled"),
            objects=objects,
            lights=lights,
            camera=camera,
            ground_plane=data.get("ground_plane", True),
            sky_color=Color.from_list(sky),
        )

    def _build_object(self, data: dict) -> SceneObject:
        mat_data = data.get("material", {})
        material = Material(
            color=Color.from_list(mat_data.get("color", [0.8, 0.8, 0.8])),
            roughness=mat_data.get("roughness", 0.5),
            metallic=mat_data.get("metallic", 0.0),
            texture_prompt=mat_data.get("texture_prompt"),
        )

        children = [self._build_object(c) for c in data.get("children", [])]

        return SceneObject(
            name=data.get("name", "object"),
            primitive=Primitive(data.get("primitive", "cube")),
            position=Vec3.from_list(data.get("position", [0, 0, 0])),
            rotation=Vec3.from_list(data.get("rotation", [0, 0, 0])),
            scale=Vec3.from_list(data.get("scale", [1, 1, 1])),
            material=material,
            children=children,
        )

    def _build_light(self, data: dict) -> Light:
        direction = None
        if "direction" in data and data["direction"]:
            direction = Vec3.from_list(data["direction"])

        return Light(
            type=LightType(data.get("type", "point")),
            position=Vec3.from_list(data.get("position", [0, 10, 0])),
            color=Color.from_list(data.get("color", [1, 1, 1])),
            intensity=data.get("intensity", 1.0),
            direction=direction,
        )
