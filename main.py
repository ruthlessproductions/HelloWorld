#!/usr/bin/env python3
"""CLI entry point for the LLM + World Model + Diffusion 3D rendering pipeline."""

import argparse
import logging
import sys

from render3d.pipeline import RenderPipeline


def main():
    parser = argparse.ArgumentParser(
        description="Generate 3D renderings from text using LLM, world model, and diffusion",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Scene description (e.g., 'a wooden cabin in a snowy forest')",
    )
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="Output directory (default: output)",
    )
    parser.add_argument(
        "--llm-model",
        default="claude-sonnet-4-20250514",
        help="Claude model for scene parsing",
    )
    parser.add_argument(
        "--diffusion-model",
        default="stabilityai/stable-diffusion-2-1",
        help="Diffusion model for texture generation",
    )
    parser.add_argument(
        "--texture-size",
        type=int,
        default=512,
        help="Texture resolution in pixels (default: 512)",
    )
    parser.add_argument(
        "--no-textures",
        action="store_true",
        help="Skip diffusion texture generation",
    )
    parser.add_argument(
        "--glb",
        action="store_true",
        default=True,
        help="Export GLB file (default: true)",
    )
    parser.add_argument(
        "--obj",
        action="store_true",
        help="Also export OBJ file",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        default=True,
        help="Render a preview image (default: true)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1280,
        help="Preview image width (default: 1280)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=720,
        help="Preview image height (default: 720)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.prompt:
        parser.print_help()
        print("\nExample:")
        print('  python main.py "a medieval stone tower on a grassy hill"')
        sys.exit(1)

    pipeline = RenderPipeline(
        output_dir=args.output,
        llm_model=args.llm_model,
        diffusion_model=args.diffusion_model,
        texture_size=args.texture_size,
        generate_textures=not args.no_textures,
    )

    result = pipeline.run(
        prompt=args.prompt,
        export_glb=args.glb,
        export_obj=args.obj,
        render_preview=args.preview,
        preview_resolution=(args.width, args.height),
    )

    print("\n" + result.summary())


if __name__ == "__main__":
    main()
