"""Push an Open Shot Designer production into Kitsu, and pull Kitsu's latest media back out.

``push``: scenes become sequences (``SC001``), shots become shots (``SH001`` / ``1A``) with the
camera notes as shot metadata columns, and the storyboard frames become a preview revision on
each shot's Storyboard task. Running it again updates the shots and uploads boards only when
they changed. AYON's Kitsu addon mirrors the result into AYON.

``pull``: for every clip of an OTIO timeline, download the newest preview of a task type
(Layout, Animation, Compositing ...) from Kitsu, then attach them to the clips as a stage
(``previs``, ``final``) with :func:`helloworld.conform.conform_folder`.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import gazu

from . import naming
from .osd import Production, extension_for

# Shot metadata columns shown in Kitsu, filled from Open Shot Designer.
DESCRIPTORS = (
    ("Slate", "slate"),
    ("Size", "size"),
    ("Lens", "lens"),
    ("Angle", "angle"),
    ("Move", "movement"),
    ("Camera", "camera"),
    ("Plan status", "plan_status"),
)
KITSU_IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}


@dataclass
class PushReport:
    project: str = ""
    url: str = ""
    sequences_created: list[str] = field(default_factory=list)
    shots_created: list[str] = field(default_factory=list)
    shots_updated: list[str] = field(default_factory=list)
    boards_uploaded: list[str] = field(default_factory=list)
    boards_unchanged: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def connect(host: str, email: str, password: str) -> None:
    host = host.rstrip("/")
    if not host.endswith("/api"):
        host += "/api"
    gazu.set_host(host)
    gazu.log_in(email, password)


def _web_url(path: str = "") -> str:
    api = gazu.get_host()
    return api[: -len("/api")] + path if api.endswith("/api") else api + path


def _resolution(production: Production, width: int = 1920) -> str:
    """Working resolution for the production's most common aspect ratio, e.g. 1920x804 for 2.39."""
    ratios = [shot.aspect_ratio for shot in production.shots] or [16 / 9]
    ratio = max(set(ratios), key=ratios.count)
    if ratio >= 1:
        return f"{width}x{round(width / ratio / 2) * 2}"
    return f"{round(width * ratio / 2) * 2}x{width}"


def _board_files(shot, tmp: Path, report: PushReport) -> tuple[list[Path], str]:
    """Write the shot's boards as files Kitsu accepts; returns (paths, content hash)."""
    paths, digest = [], hashlib.sha256()
    for n, board in enumerate(shot.boards, start=1):
        loaded = board.load()
        if loaded is None:
            report.warnings.append(f"{shot.number}: board '{board.label}' is not in the file")
            continue
        body, mime = loaded
        if mime not in KITSU_IMAGE_TYPES:
            try:
                from PIL import Image

                with Image.open(io.BytesIO(body)) as img:
                    out = io.BytesIO()
                    img.convert("RGB").save(out, "PNG")
                body, mime = out.getvalue(), "image/png"
            except Exception:
                report.warnings.append(f"{shot.number}: can't convert board '{board.label}' ({mime}) for Kitsu")
                continue
        digest.update(body)
        path = tmp / f"{shot.id}_{n:02d}{KITSU_IMAGE_TYPES.get(mime) or extension_for(mime)}"
        path.write_bytes(body)
        paths.append(path)
    return paths, digest.hexdigest()[:16] if paths else ""


def push(
    production: Production,
    *,
    project_name: Optional[str] = None,
    production_type: str = "featurefilm",
    task_type_name: str = "Storyboard",
    status_short_name: str = "wfa",
    upload_boards: bool = True,
    include_omitted: bool = False,
    log: Callable[[str], None] = print,
) -> PushReport:
    """Create or update the production in Kitsu. Call :func:`connect` first."""
    name = project_name or production.title
    report = PushReport(project=name)

    project = gazu.project.get_project_by_name(name)
    if project is None:
        project = gazu.project.new_project(name, production_type=production_type)
        log(f"created project {name}")
    report.url = _web_url(f"/productions/{project['id']}/shots")

    # Frame rate and format come from the plan (Kitsu defaults to 25 fps, 1920x1080). AYON's
    # Kitsu sync copies them onto every shot.
    wanted = {"fps": f"{production.fps:g}", "resolution": _resolution(production)}
    if any(str(project.get(k)) != v for k, v in wanted.items()):
        gazu.project.update_project({"id": project["id"], **wanted})
        log(f"set {name} to {wanted['fps']} fps, {wanted['resolution']}")

    task_type = gazu.task.get_task_type_by_name(task_type_name)
    if task_type is None:
        raise RuntimeError(f"Kitsu has no task type named {task_type_name!r}; create it in Settings > Task Types")
    gazu.project.add_task_type(project, task_type, priority=1)
    status = gazu.task.get_task_status_by_short_name(status_short_name)
    if status is None:
        raise RuntimeError(f"Kitsu has no task status with short name {status_short_name!r}")
    project_statuses = gazu.project.get_project(project["id"]).get("task_statuses") or []
    if project_statuses and status["id"] not in project_statuses:
        gazu.project.add_task_status(project, status)

    fields = {}
    existing = {d["name"]: d for d in gazu.project.all_metadata_descriptors(project) if d.get("entity_type") == "Shot"}
    for label, key in DESCRIPTORS:
        descriptor = existing.get(label) or gazu.project.add_metadata_descriptor(project, label, "Shot")
        fields[key] = descriptor["field_name"]

    with tempfile.TemporaryDirectory(prefix="helloworld-kitsu-") as tmpdir:
        tmp = Path(tmpdir)
        for scene in production.scenes:
            seq_name = naming.sequence_name(scene.number)
            sequence = gazu.shot.get_sequence_by_name(project, seq_name)
            if sequence is None:
                sequence = gazu.shot.new_sequence(project, seq_name)
                report.sequences_created.append(seq_name)
            heading = scene.heading or scene.location
            if heading and sequence.get("description") != heading:
                sequence["description"] = heading
                gazu.shot.update_sequence(sequence)

            for index, shot in enumerate(scene.shots):
                if shot.status == "omitted" and not include_omitted:
                    continue
                shot_name = naming.shot_name(shot.number, index)
                label = f"{seq_name}/{shot_name}"
                frames = max(1, round(shot.duration_seconds * production.fps))
                description = shot.description or shot.name
                values = {
                    "slate": shot.number,
                    "size": shot.size,
                    "lens": f"{shot.lens_mm:g}mm" if shot.lens_mm else "",
                    "angle": shot.angle,
                    "movement": shot.movement,
                    "camera": shot.camera,
                    "plan_status": shot.status,
                }
                data = {fields[k]: v for k, v in values.items() if v}
                data["osd_shot_id"] = shot.id

                record = gazu.shot.get_shot_by_name(sequence, shot_name)
                if record is None:
                    record = gazu.shot.new_shot(project, sequence, shot_name, nb_frames=frames, description=description, data=data)
                    report.shots_created.append(label)
                else:
                    merged = {**(record.get("data") or {}), **data}
                    if record.get("nb_frames") != frames or record.get("description") != description or merged != record.get("data"):
                        record.update({"nb_frames": frames, "description": description, "data": merged})
                        record = gazu.shot.update_shot(record)
                        report.shots_updated.append(label)

                if not upload_boards or not shot.boards:
                    continue
                paths, board_hash = _board_files(shot, tmp, report)
                if not paths:
                    continue
                if (record.get("data") or {}).get("helloworld_boards") == board_hash:
                    report.boards_unchanged.append(label)
                    continue
                task = gazu.task.get_task_by_entity(record, task_type) or gazu.task.new_task(record, task_type)
                labels = ", ".join(b.label for b in shot.boards)
                comment, preview = gazu.task.publish_preview(
                    task, status, comment=f"Storyboard from Open Shot Designer ({labels})", preview_file_path=str(paths[0])
                )
                for extra in paths[1:]:
                    gazu.task.add_preview(task, comment, preview_file_path=str(extra))
                gazu.task.set_main_preview(preview)
                record = gazu.shot.get_shot(record["id"])
                record["data"] = {**(record.get("data") or {}), "helloworld_boards": board_hash}
                gazu.shot.update_shot(record)
                report.boards_uploaded.append(label)
                log(f"boards uploaded: {label} ({len(paths)})")
    return report


# -- pull ---------------------------------------------------------------------------------------


def _latest_preview(shot: dict, task_type: dict) -> Optional[dict]:
    task = gazu.task.get_task_by_entity(shot, task_type)
    if task is None:
        return None
    previews = gazu.task.all_previews_for_task(task)
    if isinstance(previews, dict):  # some Kitsu versions group by task type
        previews = [p for group in previews.values() for p in group]
    previews = [p for p in previews if p.get("status", "ready") != "broken"]
    if not previews:
        return None
    return max(previews, key=lambda p: (p.get("revision") or 0, p.get("position") or 0, p.get("created_at") or ""))


def pull_previews(
    clip_names: list[str],
    *,
    project_name: str,
    task_type_name: str,
    folder: Path,
    log: Callable[[str], None] = print,
) -> dict[str, Path]:
    """Download the newest ``task_type_name`` preview of each clip's shot into ``folder``.

    Files are named ``<clip>_v<revision><ext>`` so :func:`helloworld.conform.conform_folder`
    picks them up. Returns clip name -> downloaded file.
    """
    project = gazu.project.get_project_by_name(project_name)
    if project is None:
        raise RuntimeError(f"No Kitsu project named {project_name!r}")
    task_type = gazu.task.get_task_type_by_name(task_type_name)
    if task_type is None:
        raise RuntimeError(f"Kitsu has no task type named {task_type_name!r}")
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for clip in clip_names:
        seq_name, _, shot_name = clip.partition("_")
        sequence = gazu.shot.get_sequence_by_name(project, seq_name)
        shot = gazu.shot.get_shot_by_name(sequence, shot_name) if sequence else None
        preview = _latest_preview(shot, task_type) if shot else None
        if preview is None:
            continue
        ext = "." + (preview.get("extension") or "mp4").lstrip(".")
        path = folder / f"{clip}_v{int(preview.get('revision') or 1):03d}{ext}"
        if not path.exists():
            gazu.files.download_preview_file(preview, str(path))
            log(f"downloaded {path.name}")
        out[clip] = path
    return out
