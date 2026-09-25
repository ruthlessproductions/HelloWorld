"""Claude API client using only stdlib — no external dependencies required inside Blender."""

from __future__ import annotations

import json
import os
import ssl
import urllib.request

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
        "texture_prompt": "optional description for procedural texture generation"
      },
      "children": []
    }
  ],
  "lights": [
    {
      "type": "SUN|POINT|AREA|SPOT",
      "position": [x, y, z],
      "color": [r, g, b],
      "intensity": 1.0,
      "direction": [dx, dy, dz]
    }
  ],
  "camera": {
    "position": [x, y, z],
    "target": [tx, ty, tz],
    "fov": 50.0
  },
  "ground_plane": true,
  "sky_color": [r, g, b]
}

Rules:
- Z-axis is up (Blender convention). Ground is at z=0.
- Use realistic proportions (1 unit = 1 meter).
- Color values are 0.0-1.0 floats.
- Decompose complex objects into primitives (a table = a flat cube top + 4 cylinder legs).
- Include 2-3 light sources. Use SUN for outdoor, AREA/POINT for indoor.
- Set SUN intensity to 2-5, POINT to 100-500 (watts), AREA to 100-500.
- Position the camera to frame the full scene. Typical FOV is 40-60.
- Set texture_prompt to describe surface appearance for procedural shaders (e.g., "rough stone", "polished wood grain", "rusty metal").
- Children inherit parent transforms.
- Keep object count reasonable (5-20 objects).
"""


class ClaudeClient:
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set it in addon preferences or ANTHROPIC_API_KEY env var."
            )
        self.model = model

    def parse_scene(self, prompt: str) -> dict:
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 4096,
            "system": SCENE_PARSE_SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        ctx = ssl.create_default_context()

        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        text = body["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]

        return json.loads(text)
