from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Primitive(Enum):
    CUBE = "cube"
    SPHERE = "sphere"
    CYLINDER = "cylinder"
    CONE = "cone"
    PLANE = "plane"
    TORUS = "torus"


class LightType(Enum):
    POINT = "point"
    DIRECTIONAL = "directional"
    AMBIENT = "ambient"


@dataclass
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]

    @classmethod
    def from_list(cls, values: list[float]) -> Vec3:
        return cls(x=values[0], y=values[1], z=values[2])


@dataclass
class Color:
    r: float = 0.8
    g: float = 0.8
    b: float = 0.8
    a: float = 1.0

    def to_rgba(self) -> tuple[float, float, float, float]:
        return (self.r, self.g, self.b, self.a)

    def to_rgb_bytes(self) -> tuple[int, int, int]:
        return (int(self.r * 255), int(self.g * 255), int(self.b * 255))

    @classmethod
    def from_list(cls, values: list[float]) -> Color:
        if len(values) == 3:
            return cls(r=values[0], g=values[1], b=values[2])
        return cls(r=values[0], g=values[1], b=values[2], a=values[3])


@dataclass
class Material:
    color: Color = field(default_factory=Color)
    roughness: float = 0.5
    metallic: float = 0.0
    texture_path: Optional[str] = None
    texture_prompt: Optional[str] = None


@dataclass
class SceneObject:
    name: str
    primitive: Primitive
    position: Vec3 = field(default_factory=Vec3)
    rotation: Vec3 = field(default_factory=Vec3)
    scale: Vec3 = field(default_factory=lambda: Vec3(1, 1, 1))
    material: Material = field(default_factory=Material)
    children: list[SceneObject] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class Light:
    type: LightType
    position: Vec3 = field(default_factory=lambda: Vec3(0, 10, 0))
    color: Color = field(default_factory=lambda: Color(1, 1, 1))
    intensity: float = 1.0
    direction: Optional[Vec3] = None


@dataclass
class Camera:
    position: Vec3 = field(default_factory=lambda: Vec3(5, 5, 5))
    target: Vec3 = field(default_factory=Vec3)
    fov: float = 60.0


@dataclass
class Scene:
    name: str = "untitled"
    objects: list[SceneObject] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)
    camera: Camera = field(default_factory=Camera)
    ground_plane: bool = True
    sky_color: Color = field(default_factory=lambda: Color(0.529, 0.808, 0.922))
