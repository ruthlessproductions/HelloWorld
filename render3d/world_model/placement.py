"""Spatial placement engine: arranges objects using relationship constraints."""

from __future__ import annotations

import logging
from enum import Enum

import numpy as np

from render3d.schema import Scene, SceneObject, Vec3

logger = logging.getLogger(__name__)


class Relation(Enum):
    ON_TOP_OF = "on_top_of"
    NEXT_TO = "next_to"
    IN_FRONT_OF = "in_front_of"
    BEHIND = "behind"
    INSIDE = "inside"
    SURROUNDING = "surrounding"


class PlacementEngine:
    """Resolves spatial relationships between objects in the scene."""

    def apply_relation(
        self,
        scene: Scene,
        subject_name: str,
        relation: Relation,
        reference_name: str,
        gap: float = 0.1,
    ) -> Scene:
        subject = self._find_object(scene, subject_name)
        reference = self._find_object(scene, reference_name)
        if not subject or not reference:
            logger.warning("Could not find objects for relation: %s %s %s", subject_name, relation.value, reference_name)
            return scene

        ref_pos = np.array(reference.position.to_list())
        ref_scale = np.array(reference.scale.to_list())
        subj_scale = np.array(subject.scale.to_list())

        if relation == Relation.ON_TOP_OF:
            new_pos = ref_pos.copy()
            new_pos[1] = ref_pos[1] + ref_scale[1] / 2 + subj_scale[1] / 2 + gap
            subject.position = Vec3.from_list(new_pos.tolist())

        elif relation == Relation.NEXT_TO:
            new_pos = ref_pos.copy()
            new_pos[0] = ref_pos[0] + ref_scale[0] / 2 + subj_scale[0] / 2 + gap
            subject.position = Vec3.from_list(new_pos.tolist())

        elif relation == Relation.IN_FRONT_OF:
            new_pos = ref_pos.copy()
            new_pos[2] = ref_pos[2] + ref_scale[2] / 2 + subj_scale[2] / 2 + gap
            subject.position = Vec3.from_list(new_pos.tolist())

        elif relation == Relation.BEHIND:
            new_pos = ref_pos.copy()
            new_pos[2] = ref_pos[2] - ref_scale[2] / 2 - subj_scale[2] / 2 - gap
            subject.position = Vec3.from_list(new_pos.tolist())

        elif relation == Relation.INSIDE:
            subject.position = Vec3.from_list(ref_pos.tolist())
            max_ratio = max(
                subj_scale[i] / ref_scale[i] for i in range(3) if ref_scale[i] > 0
            )
            if max_ratio > 0.9:
                shrink = 0.8 / max_ratio
                subject.scale = Vec3.from_list((subj_scale * shrink).tolist())

        elif relation == Relation.SURROUNDING:
            subject.position = Vec3.from_list(ref_pos.tolist())
            min_ratio = min(
                subj_scale[i] / ref_scale[i] for i in range(3) if ref_scale[i] > 0
            )
            if min_ratio < 1.2:
                grow = 1.3 / min_ratio
                subject.scale = Vec3.from_list((subj_scale * grow).tolist())

        logger.info("Placed '%s' %s '%s'", subject_name, relation.value, reference_name)
        return scene

    def _find_object(self, scene: Scene, name: str) -> SceneObject | None:
        for obj in scene.objects:
            if obj.name == name:
                return obj
            found = self._find_in_children(obj, name)
            if found:
                return found
        return None

    def _find_in_children(self, obj: SceneObject, name: str) -> SceneObject | None:
        for child in obj.children:
            if child.name == name:
                return child
            found = self._find_in_children(child, name)
            if found:
                return found
        return None
