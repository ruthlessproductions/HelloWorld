# Velociraptor model: attribution

"Velociraptor" by [Tomas Ibar](https://www.artstation.com/tomas_ibar)
([artwork page](https://www.artstation.com/artwork/4XgZd8)), downloaded from Sketchfab,
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Files from the original

- `source/Velo_sketchfab.fbx`: unchanged copy of the downloaded model.
- `textures/*_2k.png`: the original 4096 × 4096, 16-bit texture maps resized to 2048 × 2048.

## Changes made here

`build.py` adapts the model; the original files are not edited in place.

- Rotated to face +X, with the FBX's 0.01 scale applied, and lifted so the feet stand on the ground plane.
- The DirectX normal map is converted for Blender in the material (green channel flipped), and
  the baked ambient occlusion is multiplied into the base color.
- Added an armature (spine, neck, head, tail, legs, arms) with automatic skin weights, IK legs,
  and a procedural run cycle.
- In the Colosseum scene (`scenes/colosseum`), a fish is placed in its jaws.

## Crediting it when sharing renders

The raptor appears in `scenes/colosseum/renders/pelican_chase.mp4`. When sharing that video,
include a credit such as:

> "Velociraptor" by Tomas Ibar (artstation.com/artwork/4XgZd8), CC BY 4.0. Rigged and animated for this scene.
