"""LLM client using only stdlib — no external dependencies required inside Blender.

Supports Claude (Anthropic) and Gemini (Google) as interchangeable providers.
"""

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


def _extract_json(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return text


class LLMClient:
    """Provider-agnostic LLM client. Dispatches to Claude or Gemini."""

    def __init__(
        self,
        provider: str = "claude",
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.provider = provider.lower()

        if self.provider == "claude":
            self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "Anthropic API key required. Set it in addon preferences or ANTHROPIC_API_KEY env var."
                )
            self.model = model or "claude-sonnet-4-20250514"

        elif self.provider == "gemini":
            self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "Google API key required. Set it in addon preferences or GOOGLE_API_KEY env var."
                )
            self.model = model or "gemini-2.5-flash"

        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'claude' or 'gemini'.")

    def chat(self, prompt: str, system: str = "") -> str:
        """Send a prompt and return the text response."""
        if self.provider == "claude":
            return self._chat_claude(prompt, system)
        return self._chat_gemini(prompt, system)

    def parse_scene(self, prompt: str) -> dict:
        text = self.chat(prompt, system=SCENE_PARSE_SYSTEM)
        return json.loads(_extract_json(text))

    def _chat_claude(self, prompt: str, system: str) -> str:
        payload = {"model": self.model, "max_tokens": 4096}
        if system:
            payload["system"] = system
        payload["messages"] = [{"role": "user", "content": prompt}]

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        return body["content"][0]["text"].strip()

    def _chat_gemini(self, prompt: str, system: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"
            f":generateContent?key={self.api_key}"
        )

        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        payload = {"contents": contents}

        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        return body["candidates"][0]["content"]["parts"][0]["text"].strip()


# Backwards-compatible alias
ClaudeClient = LLMClient
