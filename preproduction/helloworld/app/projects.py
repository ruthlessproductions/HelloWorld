"""Projects on disk: one folder per film in the projects folder.

    <Projects>/<Name>/
        plan.osd            the Open Shot Designer plan (older versions in history/)
        cut/cut.otio        the cut, with boards in cut/cut_media/ and Kitsu previews in cut/cut_media/<stage>/
        renders/            drop final renders here (SC001_SH002_v003.mov, frame folders ...)
        edit.blend          the Blender edit made from the cut
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .. import naming, osd

_UNSAFE = re.compile(r'[\x00-\x1f/\\:*?"<>|]+')
MEDIA_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".mxf", ".avi", ".webm", ".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".dpx"}


def safe_name(text: str) -> str:
    name = _UNSAFE.sub("-", text or "").strip().strip(".").strip()
    name = re.sub(r"\s+", " ", name)[:80].strip()
    return name or "Untitled"


class ProjectError(ValueError):
    pass


@dataclass
class Project:
    name: str
    folder: Path

    @property
    def plan(self) -> Path:
        return self.folder / "plan.osd"

    @property
    def cut(self) -> Path:
        return self.folder / "cut" / "cut.otio"

    @property
    def media(self) -> Path:
        return self.cut.parent / "cut_media"

    @property
    def renders(self) -> Path:
        return self.folder / "renders"

    @property
    def edit(self) -> Path:
        return self.folder / "edit.blend"

    @property
    def history(self) -> Path:
        return self.folder / "history"

    def stage_folder(self, stage: str) -> Path:
        return self.media / stage

    def has_media(self, folder: Path) -> bool:
        return folder.is_dir() and any(p.suffix.lower() in MEDIA_EXTS or p.is_dir() for p in folder.iterdir()
                                       if not p.name.startswith("."))


def parse_plan(body: bytes) -> osd.Production:
    """Validate and read an .osd the way the CLI does (from a temporary file)."""
    with tempfile.NamedTemporaryFile(suffix=".osd", delete=False) as tmp:
        tmp.write(body)
    try:
        return osd.load(tmp.name)
    except Exception as exc:
        raise ProjectError(f"Not an Open Shot Designer project: {exc}") from exc
    finally:
        Path(tmp.name).unlink(missing_ok=True)


class Projects:
    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[Path, tuple[tuple, object]] = {}
        self._lock = threading.Lock()

    # -- lookup ---------------------------------------------------------------------------------

    def all(self) -> list[Project]:
        if not self.root.is_dir():
            return []
        found = [Project(p.name, p) for p in self.root.iterdir() if p.is_dir() and (p / "plan.osd").is_file()]
        return sorted(found, key=lambda p: p.plan.stat().st_mtime, reverse=True)

    def get(self, name: str) -> Project:
        folder = (self.root / name).resolve()
        if folder.parent != self.root.resolve() or not (folder / "plan.osd").is_file():
            raise KeyError(name)
        return Project(folder.name, folder)

    def production(self, project: Project) -> osd.Production:
        return self._cached(project.plan, osd.load)

    def timeline(self, project: Project):
        if not project.cut.is_file():
            return None
        import opentimelineio as otio

        return self._cached(project.cut, lambda p: otio.adapters.read_from_file(str(p)))

    def etag(self, project: Project) -> str:
        return self._cached(project.plan, lambda p: '"' + hashlib.sha1(p.read_bytes()).hexdigest()[:20] + '"', "etag")

    def _cached(self, path: Path, load, tag: str = ""):
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size, tag)
        with self._lock:
            hit = self._cache.get((path, tag))
            if hit and hit[0] == key:
                return hit[1]
        value = load(path)
        with self._lock:
            self._cache[(path, tag)] = (key, value)
        return value

    # -- saving plans ---------------------------------------------------------------------------

    def save_plan(self, body: bytes, name: Optional[str] = None) -> tuple[Project, bool]:
        """Store an .osd as a project's plan. Named after the film's title unless ``name`` is given.

        Returns (project, created). The previous plan, if any, moves to history/.
        """
        production = parse_plan(body)
        name = safe_name(name or production.title or "Untitled")
        folder = self.root / name
        created = not (folder / "plan.osd").exists()
        folder.mkdir(parents=True, exist_ok=True)
        project = Project(name, folder)
        if not created:
            if project.plan.read_bytes() == body:
                return project, False
            project.history.mkdir(exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(project.plan.stat().st_mtime))
            shutil.copy2(project.plan, project.history / f"plan_{stamp}.osd")
        tmp = folder / ".plan.osd.part"
        tmp.write_bytes(body)
        tmp.replace(project.plan)
        project.renders.mkdir(exist_ok=True)
        return project, created

    # -- what the page shows --------------------------------------------------------------------

    def summary(self, project: Project) -> dict:
        try:
            production = self.production(project)
        except Exception as exc:
            return {"name": project.name, "error": str(exc)}
        first = next(((s, 0) for s in production.shots if s.boards), None)
        return {
            "name": project.name,
            "title": production.title,
            "scenes": len(production.scenes),
            "shots": len(production.shots),
            "updated": project.plan.stat().st_mtime,
            "has_cut": project.cut.is_file(),
            "thumb": board_url(project, first[0].id, 0) if first else None,
        }

    def detail(self, project: Project) -> dict:
        production = self.production(project)
        stages = self._stages(project)
        scenes = []
        for scene in production.scenes:
            seq = naming.sequence_name(scene.number)
            shots = []
            for index, shot in enumerate(scene.shots):
                clip = naming.clip_name(seq, naming.shot_name(shot.number, index))
                clip_stages = stages.get(shot.id) or stages.get(clip) or {}
                shots.append({
                    "id": shot.id, "clip": clip, "slate": shot.number, "name": shot.name,
                    "description": shot.description or shot.action or "", "size": shot.size,
                    "lens": f"{shot.lens_mm:g}mm" if shot.lens_mm else "", "angle": shot.angle,
                    "movement": shot.movement, "camera": shot.camera, "status": shot.status,
                    "seconds": round(shot.duration_seconds, 2), "estimated": shot.est_seconds is not None,
                    "boards": [{"label": b.label, "url": board_url(project, shot.id, n)}
                               for n, b in enumerate(shot.boards)],
                    "stages": clip_stages.get("available", ["board"] if shot.boards else []),
                    "active": clip_stages.get("active"),
                })
            scenes.append({"id": scene.id, "sequence": seq, "number": scene.number,
                           "heading": scene.heading or scene.location or scene.name or "", "shots": shots})
        cut = None
        if project.cut.is_file():
            counts: dict[str, int] = {}
            for info in {id(v): v for v in stages.values()}.values():
                for stage in info.get("available", []):
                    counts[stage] = counts.get(stage, 0) + 1
            cut = {"updated": project.cut.stat().st_mtime, "stages": counts}
        return {
            **self.summary(project),
            "fps": production.fps,
            "aspect": _aspect_label(production),
            "folder": str(project.folder),
            "scenes_detail": scenes,
            "cut": cut,
            "renders": {"folder": str(project.renders), "has_media": project.has_media(project.renders)},
            "edit": {"exists": project.edit.is_file(),
                     "updated": project.edit.stat().st_mtime if project.edit.is_file() else None},
            "history": sorted((p.name for p in project.history.glob("plan_*.osd")), reverse=True)
            if project.history.is_dir() else [],
        }

    def _stages(self, project: Project) -> dict[str, dict]:
        """Shot id (and clip name) -> {"available": [...], "active": key} from the cut."""
        try:
            timeline = self.timeline(project)
        except Exception:
            return {}
        if timeline is None:
            return {}
        out: dict[str, dict] = {}
        order = ["board", "previs", "final"]
        for clip in timeline.find_clips():
            refs = clip.media_references()
            available = [k for k in refs if k in order and type(refs[k]).__name__ != "MissingReference"]
            available.sort(key=order.index)
            # What Blender will show: the add-on imports the most finished stage, whatever the
            # cut's own active key says (conform leaves that on the boards).
            info = {"available": available, "active": available[-1] if available else clip.active_media_reference_key}
            meta = clip.metadata.get("helloworld") or {}
            if meta.get("osd_shot_id"):
                out[str(meta["osd_shot_id"])] = info
            out[clip.name] = info
        return out


def board_url(project: Project, shot_id: str, index: int) -> str:
    """Board image URL; the version changes with the plan so browsers drop old boards."""
    return f"/api/projects/{quote(project.name)}/boards/{quote(shot_id)}/{index}?v={int(project.plan.stat().st_mtime)}"


def _aspect_label(production: osd.Production) -> str:
    ratios = [s.aspect_ratio for s in production.shots]
    if not ratios:
        return ""
    ratio = max(set(ratios), key=ratios.count)
    return f"{ratio:.2f}:1"
