"""Diffusion-based texture generator: creates material textures from text prompts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_TEXTURE_SIZE = 512


class TextureGenerator:
    """Generates textures using a Stable Diffusion pipeline.

    Falls back to procedural generation when no GPU/model is available.
    """

    def __init__(
        self,
        model_id: str = "stabilityai/stable-diffusion-2-1",
        output_dir: str = "output/textures",
        device: Optional[str] = None,
    ):
        self.model_id = model_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pipe = None
        self.device = device

    def _load_pipeline(self):
        if self.pipe is not None:
            return

        try:
            import torch
            from diffusers import StableDiffusionPipeline

            device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
            logger.info("Loading diffusion model '%s' on %s", self.model_id, device)

            self.pipe = StableDiffusionPipeline.from_pretrained(
                self.model_id,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            )
            self.pipe = self.pipe.to(device)

            if device == "cuda":
                self.pipe.enable_attention_slicing()

        except (ImportError, Exception) as e:
            logger.warning("Diffusion pipeline unavailable (%s), using procedural textures", e)
            self.pipe = None

    def generate(
        self,
        prompt: str,
        name: str,
        size: int = DEFAULT_TEXTURE_SIZE,
        seed: Optional[int] = None,
    ) -> Path:
        texture_prompt = f"seamless tileable texture of {prompt}, photorealistic, high resolution, 4k"

        self._load_pipeline()

        if self.pipe is not None:
            return self._generate_diffusion(texture_prompt, name, size, seed)
        else:
            return self._generate_procedural(prompt, name, size, seed)

    def _generate_diffusion(
        self,
        prompt: str,
        name: str,
        size: int,
        seed: Optional[int],
    ) -> Path:
        import torch

        generator = None
        if seed is not None:
            generator = torch.Generator(device=self.pipe.device).manual_seed(seed)

        image = self.pipe(
            prompt,
            height=size,
            width=size,
            num_inference_steps=30,
            guidance_scale=7.5,
            generator=generator,
        ).images[0]

        path = self.output_dir / f"{name}.png"
        image.save(path)
        logger.info("Generated diffusion texture: %s", path)
        return path

    def _generate_procedural(
        self,
        prompt: str,
        name: str,
        size: int,
        seed: Optional[int],
    ) -> Path:
        rng = np.random.RandomState(seed or hash(prompt) % (2**31))

        base_color = self._prompt_to_color(prompt)

        img = np.zeros((size, size, 3), dtype=np.uint8)
        for c in range(3):
            channel = np.full((size, size), base_color[c], dtype=np.float64)
            noise = rng.normal(0, 15, (size, size))
            channel += noise
            for octave in range(3):
                freq = 2 ** (octave + 2)
                coarse = rng.normal(0, 10 / (octave + 1), (freq, freq))
                scaled = np.kron(coarse, np.ones((size // freq, size // freq)))
                if scaled.shape[0] < size:
                    pad_h = size - scaled.shape[0]
                    pad_w = size - scaled.shape[1]
                    scaled = np.pad(scaled, ((0, pad_h), (0, pad_w)), mode="edge")
                channel += scaled[:size, :size]

            img[:, :, c] = np.clip(channel, 0, 255).astype(np.uint8)

        path = self.output_dir / f"{name}.png"
        Image.fromarray(img).save(path)
        logger.info("Generated procedural texture: %s", path)
        return path

    def _prompt_to_color(self, prompt: str) -> tuple[int, int, int]:
        prompt_lower = prompt.lower()
        color_map = {
            "stone": (140, 140, 130),
            "rock": (130, 125, 115),
            "wood": (139, 90, 43),
            "wooden": (160, 100, 50),
            "metal": (180, 180, 190),
            "steel": (170, 175, 185),
            "iron": (100, 100, 105),
            "rust": (183, 65, 14),
            "brick": (178, 85, 56),
            "grass": (76, 153, 0),
            "sand": (210, 190, 140),
            "dirt": (139, 119, 101),
            "earth": (120, 100, 80),
            "water": (64, 164, 223),
            "ice": (200, 230, 255),
            "snow": (240, 240, 250),
            "marble": (220, 215, 210),
            "concrete": (180, 178, 176),
            "glass": (200, 220, 240),
            "gold": (212, 175, 55),
            "copper": (184, 115, 51),
            "lava": (207, 16, 32),
            "moss": (60, 100, 36),
            "clay": (180, 140, 100),
        }

        for keyword, color in color_map.items():
            if keyword in prompt_lower:
                return color

        h = hash(prompt_lower) % 360
        s, v = 0.3, 0.7
        return self._hsv_to_rgb(h, s, v)

    def _hsv_to_rgb(self, h: int, s: float, v: float) -> tuple[int, int, int]:
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h / 360, s, v)
        return (int(r * 255), int(g * 255), int(b * 255))

    def generate_batch(self, prompts: dict[str, str], size: int = DEFAULT_TEXTURE_SIZE) -> dict[str, Path]:
        results = {}
        for name, prompt in prompts.items():
            results[name] = self.generate(prompt, name, size)
        return results
