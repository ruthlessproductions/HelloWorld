"""Main pipeline: orchestrates LLM → World Model → Diffusion → Rendering."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from render3d.diffusion.texture_gen import TextureGenerator
from render3d.llm.scene_parser import SceneParser
from render3d.rendering.renderer import SceneRenderer
from render3d.schema import Scene
from render3d.world_model.scene_graph import SceneGraph

logger = logging.getLogger(__name__)


class RenderPipeline:
    """End-to-end pipeline: text prompt → 3D rendered scene.

    Stages:
        1. LLM parses natural language into a structured Scene
        2. World model enforces spatial constraints and physics
        3. Diffusion model generates textures for materials
        4. Renderer produces 3D output (GLB, OBJ, preview image)
    """

    def __init__(
        self,
        output_dir: str = "output",
        llm_model: str = "claude-sonnet-4-20250514",
        diffusion_model: str = "stabilityai/stable-diffusion-2-1",
        texture_size: int = 512,
        generate_textures: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.parser = SceneParser(model=llm_model)
        self.scene_graph = SceneGraph()
        self.texture_gen = TextureGenerator(
            model_id=diffusion_model,
            output_dir=str(self.output_dir / "textures"),
        )
        self.renderer = SceneRenderer(output_dir=str(self.output_dir))

        self.texture_size = texture_size
        self.generate_textures = generate_textures

    def run(
        self,
        prompt: str,
        export_glb: bool = True,
        export_obj: bool = False,
        render_preview: bool = True,
        preview_resolution: tuple[int, int] = (1280, 720),
    ) -> PipelineResult:
        logger.info("=== Pipeline Start ===")
        logger.info("Prompt: %s", prompt)

        # Stage 1: LLM scene parsing
        logger.info("--- Stage 1: LLM Scene Parsing ---")
        scene = self.parser.parse(prompt)
        logger.info("Parsed scene '%s' with %d objects", scene.name, len(scene.objects))

        scene_json_path = self.output_dir / "scene.json"
        self._save_scene_json(scene, scene_json_path)

        # Stage 2: World model
        logger.info("--- Stage 2: World Model ---")
        scene = self.scene_graph.build(scene)
        logger.info("Scene graph built, %d nodes", len(self.scene_graph.nodes))

        # Stage 3: Diffusion textures
        texture_paths: dict[str, Path] = {}
        if self.generate_textures:
            logger.info("--- Stage 3: Diffusion Textures ---")
            texture_paths = self._generate_textures(scene)
            logger.info("Generated %d textures", len(texture_paths))

        # Stage 4: Rendering
        logger.info("--- Stage 4: Rendering ---")
        result = PipelineResult(scene=scene, output_dir=self.output_dir)

        if export_glb:
            result.glb_path = self.renderer.export_glb(scene, f"{scene.name}.glb")

        if export_obj:
            result.obj_path = self.renderer.export_obj(scene, f"{scene.name}.obj")

        if render_preview:
            result.preview_path = self.renderer.render_preview(
                scene, resolution=preview_resolution, filename=f"{scene.name}_preview.png"
            )

        logger.info("=== Pipeline Complete ===")
        logger.info("Output directory: %s", self.output_dir)
        return result

    def run_from_scene(
        self,
        scene: Scene,
        export_glb: bool = True,
        render_preview: bool = True,
    ) -> PipelineResult:
        scene = self.scene_graph.build(scene)

        if self.generate_textures:
            self._generate_textures(scene)

        result = PipelineResult(scene=scene, output_dir=self.output_dir)

        if export_glb:
            result.glb_path = self.renderer.export_glb(scene, f"{scene.name}.glb")

        if render_preview:
            result.preview_path = self.renderer.render_preview(scene)

        return result

    def _generate_textures(self, scene: Scene) -> dict[str, Path]:
        texture_prompts: dict[str, str] = {}
        for obj in scene.objects:
            self._collect_texture_prompts(obj, texture_prompts)

        if not texture_prompts:
            logger.info("No texture prompts found, skipping texture generation")
            return {}

        paths = self.texture_gen.generate_batch(texture_prompts, size=self.texture_size)

        for obj in scene.objects:
            self._apply_texture_paths(obj, paths)

        return paths

    def _collect_texture_prompts(self, obj, prompts: dict):
        if obj.material.texture_prompt:
            prompts[obj.id] = obj.material.texture_prompt
        for child in obj.children:
            self._collect_texture_prompts(child, prompts)

    def _apply_texture_paths(self, obj, paths: dict[str, Path]):
        if obj.id in paths:
            obj.material.texture_path = str(paths[obj.id])
        for child in obj.children:
            self._apply_texture_paths(child, paths)

    def _save_scene_json(self, scene: Scene, path: Path):
        def serialize(obj):
            if hasattr(obj, "value"):
                return obj.value
            if isinstance(obj, Path):
                return str(obj)
            raise TypeError(f"Cannot serialize {type(obj)}")

        data = asdict(scene)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=serialize)
        logger.info("Saved scene JSON: %s", path)


class PipelineResult:
    def __init__(self, scene: Scene, output_dir: Path):
        self.scene = scene
        self.output_dir = output_dir
        self.glb_path: Optional[Path] = None
        self.obj_path: Optional[Path] = None
        self.preview_path: Optional[Path] = None

    def summary(self) -> str:
        lines = [
            f"Scene: {self.scene.name}",
            f"Objects: {len(self.scene.objects)}",
            f"Lights: {len(self.scene.lights)}",
        ]
        if self.glb_path:
            lines.append(f"GLB: {self.glb_path}")
        if self.obj_path:
            lines.append(f"OBJ: {self.obj_path}")
        if self.preview_path:
            lines.append(f"Preview: {self.preview_path}")
        return "\n".join(lines)
