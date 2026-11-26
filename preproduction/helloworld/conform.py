"""Add newer media (previs, final renders) to the clips of an OTIO timeline.

Files are matched to clips by name: for the clip ``SC001_SH002`` any of these count, and the
highest version wins::

    SC001_SH002.mp4         SC001_SH002_v003.mov        SC001_SH002_v004/  (numbered frames)

Each match is stored under the stage key (``previs``, ``final`` ...) next to the clip's boards;
the active media is left as it was unless ``activate`` is set. The Blender add-on picks the most
finished stage on import and can switch between them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import opentimelineio as otio

from .osd import natural_key

MOVIE_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".mxf", ".avi", ".webm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".dpx", ".webp"}
_VERSION = re.compile(r"^(?P<base>.+?)(?:[_.-]v(?P<version>\d+))?$", re.IGNORECASE)
_FRAME = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)$")


@dataclass
class ConformReport:
    matched: dict[str, str] = field(default_factory=dict)  # clip -> media
    unmatched: list[str] = field(default_factory=list)


def _candidates(folder: Path) -> dict[str, list[tuple[int, Path]]]:
    found: dict[str, list[tuple[int, Path]]] = {}
    for entry in folder.iterdir():
        if entry.name.startswith("."):
            continue
        stem = entry.name if entry.is_dir() else entry.stem
        if entry.is_file() and entry.suffix.lower() not in MOVIE_EXTS | IMAGE_EXTS:
            continue
        match = _VERSION.match(stem)
        base, version = match.group("base"), int(match.group("version") or 0)
        found.setdefault(base.upper(), []).append((version, entry))
    return found


def _sequence_reference(directory: Path, rate: float, url_for) -> Optional[otio.schema.ImageSequenceReference]:
    frames = sorted(
        (p for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTS and _FRAME.match(p.stem)),
        key=lambda p: natural_key(p.name),
    )
    if not frames:
        return None
    first = _FRAME.match(frames[0].stem)
    padding = len(first.group("number"))
    start = int(first.group("number"))
    return otio.schema.ImageSequenceReference(
        target_url_base=url_for(directory).rstrip("/") + "/",
        name_prefix=first.group("prefix"),
        name_suffix=frames[0].suffix,
        start_frame=start,
        frame_zero_padding=padding,
        rate=rate,
        available_range=otio.opentime.TimeRange(
            otio.opentime.RationalTime(start, rate), otio.opentime.RationalTime(len(frames), rate)
        ),
    )


def conform_folder(
    timeline: otio.schema.Timeline,
    folder: Path,
    stage: str,
    *,
    otio_dir: Optional[Path] = None,
    activate: bool = False,
) -> ConformReport:
    """Attach the newest file in ``folder`` for each clip as its ``stage`` media."""
    folder = Path(folder)
    report = ConformReport()
    candidates = _candidates(folder)

    def url_for(path: Path) -> str:
        if otio_dir is not None:
            return Path(os.path.relpath(path, otio_dir)).as_posix()
        return path.resolve().as_uri()

    for clip in timeline.find_clips():
        options = candidates.get(clip.name.upper())
        if not options:
            report.unmatched.append(clip.name)
            continue
        _, path = max(options, key=lambda item: (item[0], natural_key(item[1].name)))
        rate = clip.source_range.duration.rate if clip.source_range else 24
        if path.is_dir():
            ref = _sequence_reference(path, rate, url_for)
            if ref is None:
                report.unmatched.append(clip.name)
                continue
        else:
            ref = otio.schema.ExternalReference(target_url=url_for(path))
        ref.name = path.name
        refs = dict(clip.media_references())
        refs[stage] = ref
        clip.set_media_references(refs, stage if activate else clip.active_media_reference_key)
        report.matched[clip.name] = path.name
    return report
