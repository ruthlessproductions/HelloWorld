"""3D renderer: converts Scene objects into renderable meshes and exports images/models."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np
import trimesh
import trimesh.creation
import trimesh.transformations as tf
from PIL import Image

from render3d.schema import Camera, Color, Light, LightType, Primitive, Scene, SceneObject, Vec3

logger = logging.getLogger(__name__)


class SceneRenderer:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_mesh_scene(self, scene: Scene) -> trimesh.Scene:
        t_scene = trimesh.Scene()

        if scene.ground_plane:
            ground = trimesh.creation.box(extents=[50, 0.02, 50])
            ground.visual.face_colors = [200, 200, 195, 255]
            t_scene.add_geometry(ground, node_name="ground_plane")

        for obj in scene.objects:
            self._add_object(t_scene, obj)

        cam_transform = self._look_at(
            np.array(scene.camera.position.to_list()),
            np.array(scene.camera.target.to_list()),
        )
        t_scene.camera_transform = cam_transform
        t_scene.camera.fov = (scene.camera.fov, scene.camera.fov)

        return t_scene

    def _add_object(self, t_scene: trimesh.Scene, obj: SceneObject, parent_transform: Optional[np.ndarray] = None):
        mesh = self._create_primitive(obj.primitive, obj.scale)
        if mesh is None:
            return

        color = obj.material.color.to_rgba()
        face_color = [int(c * 255) for c in color]
        mesh.visual.face_colors = face_color

        if obj.material.texture_path:
            self._apply_texture(mesh, obj.material.texture_path)

        transform = self._build_transform(obj.position, obj.rotation)
        if parent_transform is not None:
            transform = parent_transform @ transform

        t_scene.add_geometry(mesh, node_name=obj.name, transform=transform)

        for child in obj.children:
            self._add_object(t_scene, child, parent_transform=transform)

    def _create_primitive(self, primitive: Primitive, scale: Vec3) -> Optional[trimesh.Trimesh]:
        s = scale.to_tuple()

        if primitive == Primitive.CUBE:
            return trimesh.creation.box(extents=s)

        elif primitive == Primitive.SPHERE:
            radius = max(s) / 2
            mesh = trimesh.creation.icosphere(radius=radius)
            sx, sy, sz = s[0] / (2 * radius), s[1] / (2 * radius), s[2] / (2 * radius)
            mesh.apply_scale([sx, sy, sz])
            return mesh

        elif primitive == Primitive.CYLINDER:
            radius = max(s[0], s[2]) / 2
            height = s[1]
            return trimesh.creation.cylinder(radius=radius, height=height)

        elif primitive == Primitive.CONE:
            radius = max(s[0], s[2]) / 2
            height = s[1]
            return trimesh.creation.cone(radius=radius, height=height)

        elif primitive == Primitive.PLANE:
            return trimesh.creation.box(extents=[s[0], 0.01, s[2]])

        elif primitive == Primitive.TORUS:
            major = max(s[0], s[2]) / 2
            minor = s[1] / 4
            return trimesh.creation.torus(major_radius=major, minor_radius=minor)

        return None

    def _build_transform(self, position: Vec3, rotation: Vec3) -> np.ndarray:
        T = tf.translation_matrix(position.to_list())
        Rx = tf.rotation_matrix(math.radians(rotation.x), [1, 0, 0])
        Ry = tf.rotation_matrix(math.radians(rotation.y), [0, 1, 0])
        Rz = tf.rotation_matrix(math.radians(rotation.z), [0, 0, 1])
        return T @ Rz @ Ry @ Rx

    def _apply_texture(self, mesh: trimesh.Trimesh, texture_path: str):
        try:
            texture = Image.open(texture_path)
            from trimesh.visual.material import SimpleMaterial
            from trimesh.visual import TextureVisuals

            material = SimpleMaterial(image=texture)
            if mesh.visual.uv is None or len(mesh.visual.uv) == 0:
                uv = np.zeros((len(mesh.vertices), 2))
                verts = mesh.vertices
                uv[:, 0] = (verts[:, 0] - verts[:, 0].min()) / max(verts[:, 0].ptp(), 1e-6)
                uv[:, 1] = (verts[:, 1] - verts[:, 1].min()) / max(verts[:, 1].ptp(), 1e-6)
            else:
                uv = mesh.visual.uv

            mesh.visual = TextureVisuals(uv=uv, material=material)
        except Exception as e:
            logger.warning("Could not apply texture %s: %s", texture_path, e)

    def _look_at(self, eye: np.ndarray, target: np.ndarray, up: np.ndarray = np.array([0, 1, 0])) -> np.ndarray:
        forward = target - eye
        forward = forward / (np.linalg.norm(forward) + 1e-8)
        right = np.cross(forward, up)
        right = right / (np.linalg.norm(right) + 1e-8)
        true_up = np.cross(right, forward)

        mat = np.eye(4)
        mat[:3, 0] = right
        mat[:3, 1] = true_up
        mat[:3, 2] = -forward
        mat[:3, 3] = eye
        return mat

    def export_glb(self, scene: Scene, filename: str = "scene.glb") -> Path:
        t_scene = self.build_mesh_scene(scene)
        path = self.output_dir / filename
        t_scene.export(str(path), file_type="glb")
        logger.info("Exported GLB: %s", path)
        return path

    def export_obj(self, scene: Scene, filename: str = "scene.obj") -> Path:
        t_scene = self.build_mesh_scene(scene)
        path = self.output_dir / filename

        combined = trimesh.util.concatenate(
            [trimesh.Trimesh(vertices=g.vertices, faces=g.faces)
             for g in t_scene.geometry.values()
             if isinstance(g, trimesh.Trimesh)]
        )
        combined.export(str(path), file_type="obj")
        logger.info("Exported OBJ: %s", path)
        return path

    def render_preview(
        self,
        scene: Scene,
        resolution: tuple[int, int] = (1280, 720),
        filename: str = "preview.png",
    ) -> Path:
        try:
            import pyrender
            return self._render_pyrender(scene, resolution, filename)
        except ImportError:
            logger.info("pyrender not available, rendering wireframe preview")
            return self._render_wireframe(scene, resolution, filename)

    def _render_pyrender(
        self,
        scene: Scene,
        resolution: tuple[int, int],
        filename: str,
    ) -> Path:
        import pyrender

        t_scene = self.build_mesh_scene(scene)

        pr_scene = pyrender.Scene(
            bg_color=list(scene.sky_color.to_rgba()),
            ambient_light=[0.3, 0.3, 0.3],
        )

        for name, geom in t_scene.geometry.items():
            if isinstance(geom, trimesh.Trimesh):
                mesh = pyrender.Mesh.from_trimesh(geom)
                node_transform = t_scene.graph.get(name)[0] if name in t_scene.graph else np.eye(4)
                pr_scene.add(mesh, pose=node_transform)

        for light in scene.lights:
            if light.type == LightType.DIRECTIONAL:
                pr_light = pyrender.DirectionalLight(
                    color=np.array(light.color.to_rgba()[:3]),
                    intensity=light.intensity,
                )
            else:
                pr_light = pyrender.PointLight(
                    color=np.array(light.color.to_rgba()[:3]),
                    intensity=light.intensity * 100,
                )
            light_pose = tf.translation_matrix(light.position.to_list())
            pr_scene.add(pr_light, pose=light_pose)

        camera = pyrender.PerspectiveCamera(yfov=math.radians(scene.camera.fov))
        cam_pose = self._look_at(
            np.array(scene.camera.position.to_list()),
            np.array(scene.camera.target.to_list()),
        )
        pr_scene.add(camera, pose=cam_pose)

        renderer = pyrender.OffscreenRenderer(*resolution)
        color, _ = renderer.render(pr_scene)
        renderer.delete()

        path = self.output_dir / filename
        Image.fromarray(color).save(path)
        logger.info("Rendered preview (pyrender): %s", path)
        return path

    def _render_wireframe(
        self,
        scene: Scene,
        resolution: tuple[int, int],
        filename: str,
    ) -> Path:
        width, height = resolution
        img = np.full((height, width, 3), 255, dtype=np.uint8)

        sky = scene.sky_color.to_rgb_bytes()
        img[:height // 2] = sky

        t_scene = self.build_mesh_scene(scene)

        cam_pos = np.array(scene.camera.position.to_list())
        cam_target = np.array(scene.camera.target.to_list())
        fov = scene.camera.fov

        view = self._look_at(cam_pos, cam_target)
        view_inv = np.linalg.inv(view)

        f = height / (2 * math.tan(math.radians(fov / 2)))

        for name, geom in t_scene.geometry.items():
            if not isinstance(geom, trimesh.Trimesh):
                continue

            transform = np.eye(4)
            try:
                transform = t_scene.graph.get(name)[0]
            except Exception:
                pass

            color_rgba = geom.visual.face_colors[0] if len(geom.visual.face_colors) > 0 else [100, 100, 100, 255]
            edge_color = tuple(int(c * 0.6) for c in color_rgba[:3])

            verts_world = (transform @ np.column_stack([geom.vertices, np.ones(len(geom.vertices))]).T).T[:, :3]
            verts_cam = (view_inv @ np.column_stack([verts_world, np.ones(len(verts_world))]).T).T[:, :3]

            valid = verts_cam[:, 2] < -0.1

            for edge in geom.edges_unique[:500]:
                v0, v1 = edge
                if not (valid[v0] and valid[v1]):
                    continue

                p0 = verts_cam[v0]
                p1 = verts_cam[v1]

                x0 = int(width / 2 + f * p0[0] / (-p0[2]))
                y0 = int(height / 2 - f * p0[1] / (-p0[2]))
                x1 = int(width / 2 + f * p1[0] / (-p1[2]))
                y1 = int(height / 2 - f * p1[1] / (-p1[2]))

                self._draw_line(img, x0, y0, x1, y1, edge_color)

        path = self.output_dir / filename
        Image.fromarray(img).save(path)
        logger.info("Rendered wireframe preview: %s", path)
        return path

    def _draw_line(self, img: np.ndarray, x0: int, y0: int, x1: int, y1: int, color: tuple):
        h, w = img.shape[:2]
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        steps = max(dx, dy, 1)
        for i in range(steps + 1):
            t = i / steps
            x = int(x0 + t * (x1 - x0))
            y = int(y0 + t * (y1 - y0))
            if 0 <= x < w and 0 <= y < h:
                img[y, x] = color
