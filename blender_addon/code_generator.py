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

Output exactly one ```python code block containing the complete script. After the code block, write one or two plain sentences saying what you built or changed; nothing else.

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

Structure the script with small helper functions (make_material, make_tube, and so on) and keep it under about 500 lines.

bpy API details that are easy to get wrong:
- Create data with bpy.data (meshes.new, curves.new, objects.new) and link objects with bpy.context.collection.objects.link(obj); avoid bpy.ops where the data API works.
- Curves: curve = bpy.data.curves.new(name, "CURVE"); curve.dimensions = "3D"; spline = curve.splines.new("BEZIER"); spline.bezier_points.add(n - 1) (a new spline already has one point). Bezier points have handle_left_type and handle_right_type; there is no handle_type. Poly/NURBS points take 4D co (x, y, z, w). Tube thickness: curve.bevel_depth, curve.bevel_resolution, curve.use_fill_caps.
- Meshes from vertex lists: mesh.from_pydata(verts, [], faces) then mesh.update().
- Rotations are in radians; object.rotation_euler, not rotation.
- Avoid APIs removed in Blender 4.1+, such as Mesh.use_auto_smooth and the bgl module.
"""

_RISKY_PATTERNS = [
    (r"\bimport\s+(os|sys|subprocess|socket|shutil|urllib|requests|http|ctypes|pathlib)\b", "system/network import"),
    (r"\bfrom\s+(os|sys|subprocess|socket|shutil|urllib|requests|http|ctypes|pathlib)\b", "system/network import"),
    (r"\b__import__\s*\(", "__import__"),
    (r"(?<![\w.])(open|eval|exec)\s*\(", "open/eval/exec"),
    (r"\bbpy\.ops\.wm\.", "bpy.ops.wm"),
]


def generate_script(client, prompt: str) -> tuple[str, str]:
    """Return (script, note) for a new scene description."""
    return _ask(client, prompt)


def revise_script(client, original_prompt: str, history: list[str], code: str, instruction: str) -> tuple[str, str]:
    """Return (script, note) after applying a change request to the current script."""
    parts = [f"Original request: {original_prompt}"]
    if history:
        earlier = "\n".join(f"{i}. {h}" for i, h in enumerate(history, 1))
        parts.append(f"Earlier change requests, already applied to the script below:\n{earlier}")
    parts.append(
        "Current script (it may include manual edits by the user; keep them unless the request says otherwise):\n"
        f"```python\n{code}\n```"
    )
    parts.append(f"Change request: {instruction}")
    parts.append("Return the complete updated script.")
    return _ask(client, "\n\n".join(parts))


def fix_error_instruction(error: str) -> str:
    return f"The script failed when run in Blender with this error. Fix it without changing anything else.\n{error}"


def _ask(client, message: str) -> tuple[str, str]:
    reply = client.chat(message, system=CODE_GEN_SYSTEM, max_tokens=32000, timeout=300)
    return _split_reply(reply)


def _split_reply(text: str) -> tuple[str, str]:
    match = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if not match:
        return text.strip() + "\n", ""
    note = (text[: match.start()] + " " + text[match.end():]).strip()
    return match.group(1).strip() + "\n", " ".join(note.split())[:400]


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
