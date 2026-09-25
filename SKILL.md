---
name: render3d-scene-generator
description: Generate 3D scenes from text prompts using LLM + World Model + Diffusion pipeline, with native Blender integration. Trigger when asked to create 3D scenes, generate Blender scenes from text, or produce 3D renderings from descriptions.
---

# AI 3D Scene Generator

Generates complete 3D scenes from natural language descriptions using a three-stage pipeline:
1. **LLM (Claude)** — parses text into structured scene descriptions
2. **World Model** — enforces spatial constraints, resolves collisions, optimizes camera
3. **Procedural Materials / Diffusion** — creates realistic Blender shader node trees or diffusion textures

## Prerequisites

- **Blender 4.0+** with [blender-mcp](https://github.com/ahujasid/blender-mcp) addon (for MCP mode)
- **Anthropic API key** (set as `ANTHROPIC_API_KEY` env var or in addon preferences)
- Python 3.10+ with `anthropic`, `numpy`, `trimesh`, `Pillow` (for standalone mode)

## Modes

### 1. Blender Addon (Recommended)

Install directly into Blender for a native panel in the 3D Viewport sidebar.

**Install:**
```
1. In Blender: Edit → Preferences → Add-ons → Install
2. Select the blender_addon/ directory (or zip it first)
3. Enable "AI Scene Generator"
4. Set your Anthropic API key in addon preferences
5. Find the panel: View3D → Sidebar (N) → "AI Scene"
```

**Use:**
- Type a scene description in the prompt field
- Adjust settings (render engine, texture size, HDRI)
- Click "Generate Scene"
- Or click "Quick Generate" for a test scene without an API call

### 2. MCP Script (Remote Control)

Send scenes to a running Blender instance via the blender-mcp WebSocket addon.

```bash
# Generate from text prompt
python scripts/generate_scene.py --prompt "a medieval castle on a hill" --port 9876

# Use a test scene (no API call)
python scripts/generate_scene.py --test --port 9876

# Save as Blender Python script (no Blender connection needed)
python scripts/generate_scene.py --prompt "a forest cabin" --output scene.py

# Load from a scene JSON
python scripts/generate_scene.py --scene output/scene.json --port 9876
```

### 3. Standalone Pipeline (CLI)

Generate GLB/OBJ models and preview images without Blender.

```bash
python main.py "a stone tower on a grassy hill"
python main.py "a wooden cabin" --obj --texture-size 1024 -v
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Text Prompt                               │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stage 1: LLM (Claude API)                                      │
│  Natural language → JSON scene description                       │
│  Objects, materials, lights, camera                              │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stage 2: World Model                                            │
│  Spatial reasoning, ground constraints, collision resolution     │
│  Camera framing optimization                                     │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────┬───────────────────────────┐
│  Stage 3a: Blender Materials         │  Stage 3b: Diffusion      │
│  Principled BSDF + procedural nodes  │  Stable Diffusion textures│
│  (stone, wood, metal, grass, etc.)   │  (standalone mode)        │
└──────────────────────┬───────────────┴───────────────────────────┘
                       ▼
┌──────────────────────────────────────┬───────────────────────────┐
│  Output: Blender Scene               │  Output: GLB / OBJ / PNG  │
│  Native objects, Cycles/EEVEE render  │  trimesh export           │
└──────────────────────────────────────┴───────────────────────────┘
```

## Supported Primitives

cube, sphere, cylinder, cone, plane, torus

## Material Types

The Blender addon generates procedural shader node trees based on texture_prompt keywords:

| Keyword | Shader Setup |
|---------|-------------|
| stone, rock, brick, wall | Noise + Voronoi + bump mapping |
| wood, wooden, plank | Wave rings + noise grain |
| metal, steel, iron | Metallic BSDF + fine noise |
| rust | Voronoi rust patches + high roughness |
| grass, moss | Dual noise + green variation |
| sand, dirt, earth | Noise + Voronoi displacement |
| water | Transmission + low roughness + IOR 1.33 |
| glass, crystal | Full transmission + IOR 1.45 |
| tile, roof, ceramic | Checker pattern + bump |

## Project Structure

```
render3d/              # Standalone Python pipeline
├── llm/               # Claude scene parser
├── world_model/       # Spatial reasoning engine
├── diffusion/         # Texture generation (Stable Diffusion / procedural)
├── rendering/         # trimesh-based renderer (GLB/OBJ/preview)
└── pipeline.py        # Orchestrator

blender_addon/         # Blender 4.0+ addon
├── __init__.py        # Addon registration, operators, UI panel
├── llm_client.py      # Claude API via urllib (zero external deps)
├── world_model.py     # Spatial constraints (stdlib math only)
└── scene_builder.py   # bpy scene construction + procedural shaders

scripts/               # MCP integration
└── generate_scene.py  # Send generated scenes to Blender via WebSocket
```
