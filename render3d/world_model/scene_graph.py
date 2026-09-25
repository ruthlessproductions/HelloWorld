"""World model: scene graph with spatial reasoning and physical constraints."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from render3d.schema import Camera, Light, Primitive, Scene, SceneObject, Vec3

logger = logging.getLogger(__name__)


@dataclass
class BoundingBox:
    min_corner: np.ndarray
    max_corner: np.ndarray

    @property
    def center(self) -> np.ndarray:
        return (self.min_corner + self.max_corner) / 2

    @property
    def size(self) -> np.ndarray:
        return self.max_corner - self.min_corner

    def intersects(self, other: BoundingBox) -> bool:
        return bool(np.all(self.min_corner <= other.max_corner) and np.all(self.max_corner >= other.min_corner))

    def expand(self, margin: float) -> BoundingBox:
        return BoundingBox(
            self.min_corner - margin,
            self.max_corner + margin,
        )


@dataclass
class SceneNode:
    obj: SceneObject
    bbox: BoundingBox
    world_position: np.ndarray
    children: list[SceneNode] = field(default_factory=list)
    grounded: bool = False


class SceneGraph:
    """Maintains spatial relationships and enforces physical constraints."""

    def __init__(self):
        self.nodes: list[SceneNode] = []
        self.scene_bbox: Optional[BoundingBox] = None

    def build(self, scene: Scene) -> Scene:
        logger.info("Building scene graph for '%s' with %d objects", scene.name, len(scene.objects))

        self.nodes = []
        for obj in scene.objects:
            node = self._create_node(obj)
            self.nodes.append(node)

        self._enforce_ground_constraints(scene.ground_plane)
        self._resolve_collisions()
        self._compute_scene_bbox()

        scene.objects = [n.obj for n in self.nodes]
        scene.camera = self._optimize_camera(scene.camera)

        return scene

    def _create_node(self, obj: SceneObject) -> SceneNode:
        bbox = self._compute_bbox(obj)
        pos = np.array(obj.position.to_list())

        children = []
        for child in obj.children:
            child_node = self._create_node(child)
            child_node.world_position += pos
            children.append(child_node)

        return SceneNode(obj=obj, bbox=bbox, world_position=pos, children=children)

    def _compute_bbox(self, obj: SceneObject) -> BoundingBox:
        s = np.array(obj.scale.to_list())
        p = np.array(obj.position.to_list())

        half = self._primitive_half_extents(obj.primitive, s)

        return BoundingBox(min_corner=p - half, max_corner=p + half)

    def _primitive_half_extents(self, primitive: Primitive, scale: np.ndarray) -> np.ndarray:
        if primitive == Primitive.CUBE:
            return scale / 2
        elif primitive == Primitive.SPHERE:
            r = max(scale) / 2
            return np.array([r, r, r])
        elif primitive == Primitive.CYLINDER:
            r = max(scale[0], scale[2]) / 2
            h = scale[1] / 2
            return np.array([r, h, r])
        elif primitive == Primitive.CONE:
            r = max(scale[0], scale[2]) / 2
            h = scale[1] / 2
            return np.array([r, h, r])
        elif primitive == Primitive.PLANE:
            return np.array([scale[0] / 2, 0.01, scale[2] / 2])
        elif primitive == Primitive.TORUS:
            outer = max(scale[0], scale[2]) / 2
            return np.array([outer, scale[1] / 4, outer])
        return scale / 2

    def _enforce_ground_constraints(self, has_ground: bool):
        if not has_ground:
            return

        for node in self.nodes:
            self._ground_node(node)

    def _ground_node(self, node: SceneNode):
        bbox = node.bbox
        if bbox.min_corner[1] < 0:
            offset = -bbox.min_corner[1]
            node.obj.position.y += offset
            node.bbox.min_corner[1] += offset
            node.bbox.max_corner[1] += offset
            node.world_position[1] += offset
            node.grounded = True
            logger.debug("Grounded '%s' by raising %.2f", node.obj.name, offset)

    def _resolve_collisions(self):
        max_iterations = 50
        for iteration in range(max_iterations):
            resolved = True
            for i, a in enumerate(self.nodes):
                for b in self.nodes[i + 1:]:
                    if a.bbox.intersects(b.bbox):
                        self._separate(a, b)
                        resolved = False
            if resolved:
                logger.debug("Collisions resolved in %d iterations", iteration + 1)
                return

        logger.warning("Collision resolution did not fully converge after %d iterations", max_iterations)

    def _separate(self, a: SceneNode, b: SceneNode):
        delta = b.bbox.center - a.bbox.center
        overlap = (a.bbox.size + b.bbox.size) / 2 - np.abs(delta)
        overlap = np.maximum(overlap, 0)

        if np.all(overlap == 0):
            return

        axis = int(np.argmin(np.where(overlap > 0, overlap, np.inf)))
        shift = overlap[axis] / 2 + 0.05

        direction = 1.0 if delta[axis] >= 0 else -1.0

        pos_a = list(a.obj.position.to_list())
        pos_b = list(b.obj.position.to_list())
        pos_a[axis] -= direction * shift
        pos_b[axis] += direction * shift
        a.obj.position = Vec3.from_list(pos_a)
        b.obj.position = Vec3.from_list(pos_b)

        a.bbox = self._compute_bbox(a.obj)
        b.bbox = self._compute_bbox(b.obj)

    def _compute_scene_bbox(self):
        if not self.nodes:
            self.scene_bbox = BoundingBox(np.zeros(3), np.ones(3))
            return

        all_min = np.array([n.bbox.min_corner for n in self.nodes])
        all_max = np.array([n.bbox.max_corner for n in self.nodes])
        self.scene_bbox = BoundingBox(np.min(all_min, axis=0), np.max(all_max, axis=0))

    def _optimize_camera(self, camera: Camera) -> Camera:
        if self.scene_bbox is None:
            return camera

        center = self.scene_bbox.center
        size = self.scene_bbox.size
        max_dim = float(np.max(size))

        distance = max_dim * 2.0
        fov_rad = math.radians(camera.fov / 2)
        if fov_rad > 0:
            distance = max(distance, max_dim / (2 * math.tan(fov_rad)))

        distance *= 1.3

        camera.target = Vec3(float(center[0]), float(center[1]), float(center[2]))
        camera.position = Vec3(
            float(center[0] + distance * 0.7),
            float(center[1] + distance * 0.5),
            float(center[2] + distance * 0.7),
        )

        return camera
