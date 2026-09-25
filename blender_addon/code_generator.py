"""Code mode: the LLM writes a Blender Python script that builds the scene.

The script is stored in a Text datablock so the user can review (and edit)
it in Blender's Text Editor before running it.
"""

from __future__ import annotations

import re
import traceback

import bpy

TEXT_NAME = "AI_Scene_Script"

CODE_GEN_SYSTEM = """You are an expert Blender technical artist. Write a Blender Python (bpy) script that builds the scene the user describes.

Output exactly one ```python code block containing the complete script, and nothing else.

Environment:
- The script runs inside Blender 4.2 or newer (including 5.x) via exec(). If the user wanted the scene cleared, that already happened; do not delete existing objects.
- Only import bpy, bmesh, mathutils, math and random. No file, network or OS access, and no bpy.ops.wm calls.
- Z is up, 1 unit = 1 meter, the ground is at z = 0.

Modeling quality matters most:
- Model recognizable, well-proportioned forms with real detail, not blocky stand-ins.
- Pick the right technique per part: curves with bevel_depth for tubes, necks, limbs, frames, cables and handles; bmesh for custom shapes; non-uniformly scaled UV spheres for organic masses; primitives with a Bevel modifier for hard-surface parts; Mirror, Array, Screw and Solidify modifiers for symmetry, repetition and lathed shapes.
- Parts of one object must physically connect. Overlap joints slightly instead of leaving gaps; nothing floats unless the description says so.
- Build repeated details with loops (wheel spokes, fence posts, leaves, windows).
- For smooth surfaces set use_smooth on the polygons. Only add a Subdivision Surface modifier to meshes with enough edge loops to hold their shape; never to plain cubes or cylinders (use a Bevel modifier on those).
- Parent each distinct object's parts to an Empty with a descriptive name (e.g. "Pelican", "Bicycle"), and give every part a descriptive name.

Materials: Principled BSDF with plausible, distinct colors. Blender 4+ input names: "Base Color", "Metallic", "Roughness", "Transmission Weight", "Emission Color", "Emission Strength", "Subsurface Weight", "Coat Weight".

Lighting and camera: add a ground plane unless the scene makes no sense with one, a key/fill/rim light setup (or a Sun for outdoor scenes), and a camera that frames the whole subject, assigned to scene.camera. Aim the camera with a Track To constraint or Vector.to_track_quat('-Z', 'Y').

Structure the script with small helper functions (make_material, make_tube, and so on) and keep it under about 500 lines. Avoid APIs removed in Blender 4.1+, such as Mesh.use_auto_smooth and the bgl module.
"""

_RISKY_PATTERNS = [
    (r"\bimport\s+(os|sys|subprocess|socket|shutil|urllib|requests|http|ctypes|pathlib)\b", "system/network import"),
    (r"\bfrom\s+(os|sys|subprocess|socket|shutil|urllib|requests|http|ctypes|pathlib)\b", "system/network import"),
    (r"\b__import__\s*\(", "__import__"),
    (r"(?<![\w.])(open|eval|exec)\s*\(", "open/eval/exec"),
    (r"\bbpy\.ops\.wm\.", "bpy.ops.wm"),
]


def generate_script(client, prompt: str) -> str:
    text = client.chat(prompt, system=CODE_GEN_SYSTEM, max_tokens=32000, timeout=300)
    return _extract_code(text)


def fix_script(client, prompt: str, code: str, error: str) -> str:
    message = (
        f"Original request: {prompt}\n\n"
        f"This script failed when run in Blender.\n\nError:\n{error}\n\n"
        f"Script:\n```python\n{code}\n```\n\n"
        "Return the complete corrected script."
    )
    text = client.chat(message, system=CODE_GEN_SYSTEM, max_tokens=32000, timeout=300)
    return _extract_code(text)


def _extract_code(text: str) -> str:
    match = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip() + "\n"
    return text.strip() + "\n"


def store_script(code: str) -> bpy.types.Text:
    text = bpy.data.texts.get(TEXT_NAME) or bpy.data.texts.new(TEXT_NAME)
    text.clear()
    text.write(code)
    text.current_line_index = 0
    return text


def show_in_text_editors(context, text: bpy.types.Text) -> bool:
    shown = False
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "TEXT_EDITOR":
                area.spaces.active.text = text
                shown = True
    return shown


def find_risky_code(code: str) -> list[str]:
    found = []
    for pattern, label in _RISKY_PATTERNS:
        if re.search(pattern, code) and label not in found:
            found.append(label)
    return found


def run_script(code: str):
    """Execute the script. On failure, raise RuntimeError carrying a traceback trimmed to the script's frames."""
    try:
        exec(compile(code, TEXT_NAME, "exec"), {"__name__": "__main__"})
    except Exception as e:
        raise RuntimeError(_format_error(e, code)) from None


def _format_error(exc: Exception, code: str) -> str:
    source = code.splitlines()

    def src(lineno):
        return source[lineno - 1].strip() if lineno and 0 < lineno <= len(source) else ""

    if isinstance(exc, SyntaxError) and exc.filename == TEXT_NAME:
        return f"line {exc.lineno}: SyntaxError: {exc.msg}\n    {src(exc.lineno)}"

    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == TEXT_NAME]
    lines = [f"line {f.lineno} in {f.name}: {src(f.lineno)}" for f in frames]
    lines.append(f"{type(exc).__name__}: {exc}")
    return "\n".join(lines)
