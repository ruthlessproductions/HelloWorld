"""Build an OpenTimelineIO board-o-matic from an Open Shot Designer production.

One video track, one clip per shot in storyboard order, each as long as the shot's estimated
duration. A clip's media is its first storyboard frame; every frame of the shot, plus the
camera notes, are in ``clip.metadata["helloworld"]`` so tools downstream (the Blender add-on,
Kitsu, an editor) can use them. Shots with no board get a MissingReference so the timing holds.

Each clip keeps its media under named keys (``board`` now; later ``previs`` and ``final``) so a
conform step can add newer media without losing the boards.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import opentimelineio as otio

from . import naming
from .osd import Production, extension_for

BOARD_KEY = "board"


def _media_url(path: Path, relative_to: Optional[Path]) -> str:
    if relative_to is not None:
        return Path(os.path.relpath(path, relative_to)).as_posix()
    return path.resolve().as_uri()


def build_timeline(
    production: Production,
    media_dir: Path,
    *,
    relative_to: Optional[Path] = None,
    start_timecode: Optional[str] = None,
    include_omitted: bool = False,
) -> otio.schema.Timeline:
    """Return the timeline, writing each board image into ``media_dir``.

    ``relative_to``: write media paths relative to this folder (the .otio file's folder) instead
    of absolute file URLs.
    """
    fps = production.fps
    media_dir.mkdir(parents=True, exist_ok=True)
    timeline = otio.schema.Timeline(name=production.title)
    if start_timecode:
        timeline.global_start_time = otio.opentime.from_timecode(start_timecode, fps)
    timeline.metadata["helloworld"] = {
        "source": "Open Shot Designer",
        "project_id": production.id,
        "title": production.title,
        "director": production.director,
        "fps": fps,
    }
    track = otio.schema.Track(name="Boards", kind=otio.schema.TrackKind.Video)
    timeline.tracks.append(track)

    for scene in production.scenes:
        seq = naming.sequence_name(scene.number)
        first_in_scene = True
        for index, shot in enumerate(scene.shots):
            if shot.status == "omitted" and not include_omitted:
                continue
            name = naming.shot_name(shot.number, index)
            frames = max(1, round(shot.duration_seconds * fps))
            span = otio.opentime.TimeRange(
                otio.opentime.RationalTime(0, fps), otio.opentime.RationalTime(frames, fps)
            )
            boards = []
            for n, board in enumerate(shot.boards, start=1):
                loaded = board.load()
                if loaded is None:
                    continue
                body, mime = loaded
                path = media_dir / f"{seq}_{name}_{n:02d}{extension_for(mime)}"
                if not path.exists() or path.read_bytes() != body:
                    path.write_bytes(body)
                boards.append({"label": board.label, "note": board.note, "url": _media_url(path, relative_to)})

            clip = otio.schema.Clip(name=naming.clip_name(seq, name), source_range=span)
            if boards:
                ref = otio.schema.ExternalReference(target_url=boards[0]["url"], available_range=span)
                ref.name = boards[0]["label"]
            else:
                ref = otio.schema.MissingReference(name="no board")
            clip.set_media_references({BOARD_KEY: ref}, BOARD_KEY)
            clip.metadata["helloworld"] = {
                "sequence": seq,
                "shot": name,
                "scene_number": scene.number,
                "shot_number": shot.number,
                "osd_scene_id": scene.id,
                "osd_shot_id": shot.id,
                "heading": scene.heading,
                "location": scene.location,
                "time_of_day": scene.time_of_day,
                "description": shot.description,
                "action": shot.action,
                "size": shot.size,
                "lens_mm": shot.lens_mm,
                "angle": shot.angle,
                "movement": shot.movement,
                "camera": shot.camera,
                "aspect": shot.aspect,
                "status": shot.status,
                "est_seconds": shot.est_seconds,
                "boards": boards,
            }
            if first_in_scene:
                title = scene.heading or scene.location or scene.time_of_day
                clip.markers.append(
                    otio.schema.Marker(
                        name=f"{seq} {title}".strip(),
                        marked_range=otio.opentime.TimeRange(span.start_time, otio.opentime.RationalTime(0, fps)),
                        color=otio.schema.MarkerColor.GREEN,
                    )
                )
                first_in_scene = False
            track.append(clip)
    return timeline


def write_animatic(
    production: Production,
    out_path: Path,
    *,
    absolute_paths: bool = False,
    start_timecode: Optional[str] = None,
    include_omitted: bool = False,
) -> Path:
    """Write ``out_path`` (.otio) and its board images to ``<stem>_media/`` next to it."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    media_dir = out_path.parent / f"{out_path.stem}_media"
    timeline = build_timeline(
        production,
        media_dir,
        relative_to=None if absolute_paths else out_path.parent,
        start_timecode=start_timecode,
        include_omitted=include_omitted,
    )
    otio.adapters.write_to_file(timeline, str(out_path))
    return out_path
