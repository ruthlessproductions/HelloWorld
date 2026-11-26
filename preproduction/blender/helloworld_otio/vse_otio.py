# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenTimelineIO <-> Blender Video Sequence Editor.

Import: each OTIO track becomes a channel; clips become image, image-sequence, movie or sound
strips trimmed to their source range; gaps are kept; markers become timeline markers.
Every clip may carry several media references ("board", "previs", "final" ...). The first
stage in ``prefer`` whose file exists is loaded, and all of them are remembered on the strip
so :func:`swap_stage` can switch a strip later without losing edits made in Blender.

Export: channels become tracks; strips become clips with the source range they show, gaps
fill the space between them, and the HelloWorld metadata travels back out.

Works with Blender 4.2+ (``sequences``) and 5.x (``strips``).
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import bpy
import opentimelineio as otio

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".bmp", ".webp", ".tga", ".dpx", ".hdr"}
SOUND_EXTS = {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}

DEFAULT_PREFER = ("final", "previs", "board", "DEFAULT_MEDIA")
PROP_CLIP = "hw_clip"  # clip name
PROP_META = "hw_meta"  # JSON: the clip's helloworld metadata
PROP_MEDIA = "hw_media"  # JSON: {stage: {"path", "kind", "start", "rate", ...}}
PROP_STAGE = "hw_stage"  # stage currently shown
PROP_SOURCE = "hw_source"  # the .otio file the strip came from
PROP_PANEL = "hw_panel"  # board panel index for multi-panel shots


@dataclass
class ImportReport:
    strips: int = 0
    placeholders: int = 0
    skipped: list[str] = field(default_factory=list)
    stages: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        stages = ", ".join(f"{k}: {v}" for k, v in sorted(self.stages.items())) or "none"
        text = f"{self.strips} strips ({stages}), {self.placeholders} placeholders"
        if self.skipped:
            text += f", skipped {len(self.skipped)}"
        return text


# -- Blender version compatibility --------------------------------------------------------------


def strips_of(scene):
    sed = scene.sequence_editor or scene.sequence_editor_create()
    return sed.strips if hasattr(sed, "strips") else sed.sequences


def all_strips(scene):
    sed = scene.sequence_editor
    if sed is None:
        return []
    return list(sed.strips_all if hasattr(sed, "strips_all") else sed.sequences_all)


def new_effect(coll, name, kind, channel, start, length):
    try:
        return coll.new_effect(name=name, type=kind, channel=channel, frame_start=start, length=length)
    except TypeError:  # Blender 4.x
        return coll.new_effect(name=name, type=kind, channel=channel, frame_start=start, frame_end=start + length)


def strip_start(strip) -> int:
    """First frame the strip shows on the timeline."""
    return strip.left_handle if hasattr(strip, "left_handle") else strip.frame_final_start


def strip_end(strip) -> int:
    """First frame after the strip."""
    return strip.right_handle if hasattr(strip, "right_handle") else strip.frame_final_end


def content_start(strip) -> float:
    """Timeline frame where the strip's media begins (before trimming)."""
    return strip.content_start if hasattr(strip, "content_start") else strip.frame_start


def content_length(strip) -> int:
    if hasattr(strip, "content_end"):
        return round(strip.content_end - strip.content_start)
    return strip.frame_duration


def set_range(strip, start: int, end: int) -> None:
    """Show timeline frames [start, end). Widen before narrowing so the handles never clamp."""
    if hasattr(strip, "left_handle"):
        strip.right_handle = max(end, strip.right_handle)
        strip.left_handle = start
        strip.right_handle = end
    else:
        strip.frame_final_end = max(end, strip.frame_final_end)
        strip.frame_final_start = start
        strip.frame_final_end = end


# -- helpers ------------------------------------------------------------------------------------


def plain(value):
    """OTIO metadata (AnyDictionary / AnyVector) as plain dicts and lists."""
    if isinstance(value, (str, bytes, int, float, bool)) or value is None:
        return value
    if hasattr(value, "items"):
        return {str(k): plain(v) for k, v in value.items()}
    if hasattr(value, "__iter__"):
        return [plain(v) for v in value]
    return str(value)


def url_to_path(url: str, base_dir: str) -> Optional[str]:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "file":
        path = urllib.parse.unquote(parsed.path)
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return path
    if parsed.scheme and len(parsed.scheme) > 1:
        return None  # http(s) and other remote media are not loaded
    return os.path.normpath(os.path.join(base_dir, urllib.parse.unquote(url)))


def path_to_url(path: str, base_dir: Optional[str]) -> str:
    path = bpy.path.abspath(path)
    if base_dir:
        try:
            return os.path.relpath(path, base_dir).replace(os.sep, "/")
        except ValueError:  # another drive on Windows
            pass
    return "file://" + urllib.parse.quote(path.replace(os.sep, "/") if path.startswith("/") else "/" + path.replace(os.sep, "/"))


def media_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in SOUND_EXTS:
        return "sound"
    return "movie"


def describe_reference(ref, base_dir: str) -> Optional[dict]:
    """A JSON-able description of a media reference, or None if Blender can't load it."""
    if isinstance(ref, otio.schema.ImageSequenceReference):
        rate = ref.rate or 24
        files = [url_to_path(ref.target_url_for_image_number(i), base_dir) for i in range(ref.number_of_images_in_sequence())]
        files = [f for f in files if f]
        if not files:
            return None
        return {"kind": "sequence", "files": files, "start": ref.start_frame, "rate": rate}
    if isinstance(ref, otio.schema.ExternalReference):
        path = url_to_path(ref.target_url, base_dir)
        if not path:
            return None
        info = {"kind": media_kind(path), "path": path}
        if ref.available_range is not None:
            info["start"] = ref.available_range.start_time.value
            info["rate"] = ref.available_range.start_time.rate
        return info
    return None


def media_exists(info: dict) -> bool:
    if info["kind"] == "sequence":
        return os.path.exists(info["files"][0])
    return os.path.exists(info["path"])


def label_for(meta: dict, clip_name: str) -> str:
    parts = [p for p in (meta.get("sequence"), meta.get("shot")) if p] or [clip_name]
    camera = " ".join(
        str(p) for p in (meta.get("size"), f"{meta['lens_mm']:g}mm" if meta.get("lens_mm") else "", meta.get("movement")) if p
    )
    line = " ".join(parts) + (f"  ·  {camera}" if camera else "")
    if meta.get("description"):
        line += "\n" + str(meta["description"])[:140]
    return line


# -- import -------------------------------------------------------------------------------------


def configure_scene(scene, timeline, start_frame: int):
    rate = None
    if timeline.global_start_time is not None:
        rate = timeline.global_start_time.rate
    if not rate:
        clips = list(timeline.find_clips())
        rate = clips[0].source_range.duration.rate if clips and clips[0].source_range else 24
    fps = round(rate)
    scene.render.fps = fps
    scene.render.fps_base = fps / rate
    duration = round(timeline.duration().rescaled_to(rate).value)
    scene.frame_start = start_frame
    scene.frame_end = start_frame + max(duration, 1) - 1
    meta = plain(timeline.metadata.get("helloworld", {}))
    aspect = None
    for clip in timeline.find_clips():
        aspect = clip.metadata.get("helloworld", {}).get("aspect")
        if aspect:
            break
    ratios = {"16:9": 16 / 9, "2.39:1": 2.39, "1.85:1": 1.85, "4:3": 4 / 3, "9:16": 9 / 16}
    if aspect in ratios:
        ratio = ratios[aspect]
        if ratio >= 1:
            scene.render.resolution_x, scene.render.resolution_y = 1920, int(round(1920 / ratio / 2) * 2)
        else:
            scene.render.resolution_x, scene.render.resolution_y = int(round(1920 * ratio / 2) * 2), 1920
    if meta.get("title"):
        scene["hw_title"] = meta["title"]
    return rate


def _new_media_strip(coll, name: str, info: dict, channel: int, frame: int, length: int, source_offset: int):
    """Create a strip showing ``length`` frames of the media starting ``source_offset`` frames in."""
    kind = info["kind"]
    if kind == "image":
        strip = coll.new_image(name=name, filepath=info["path"], channel=channel, frame_start=frame, fit_method="FIT")
        set_range(strip, frame, frame + length)
        return strip
    if kind == "sequence":
        files = info["files"]
        strip = coll.new_image(name=name, filepath=files[0], channel=channel, frame_start=frame - source_offset, fit_method="FIT")
        for path in files[1:]:
            strip.elements.append(os.path.basename(path))
    elif kind == "sound":
        strip = coll.new_sound(name=name, filepath=info["path"], channel=channel, frame_start=frame - source_offset)
    else:
        strip = coll.new_movie(name=name, filepath=info["path"], channel=channel, frame_start=frame - source_offset, fit_method="FIT")
    set_range(strip, frame, frame + length)
    return strip


def _source_offset(clip, info: dict, rate: float) -> int:
    """Frames between the start of the media and the first frame the clip shows."""
    if info["kind"] == "image" or clip.source_range is None:
        return 0
    start = clip.source_range.start_time.rescaled_to(rate).value
    media_start = 0.0
    if "start" in info and info.get("rate"):
        media_start = otio.opentime.RationalTime(info["start"], info["rate"]).rescaled_to(rate).value
        if info["kind"] == "sequence":
            media_start = info["start"]
    return max(0, round(start - media_start))


def _stage_infos(clip, base_dir: str) -> dict[str, dict]:
    refs = clip.media_references()
    infos = {}
    for key, ref in refs.items():
        info = describe_reference(ref, base_dir)
        if info:
            infos[key] = info
    return infos


def _pick_stage(infos: dict[str, dict], prefer, active_key: str) -> Optional[str]:
    for key in list(prefer) + [active_key] + list(infos):
        if key in infos and media_exists(infos[key]):
            return key
    return None


def _place_clip(coll, scene, clip, meta, infos, stage, channel, frame, length, rate, source, report):
    """Create the strip(s) for one clip; returns the strips created."""
    created = []
    info = infos.get(stage) if stage else None
    common = {PROP_CLIP: clip.name, PROP_META: json.dumps(meta), PROP_MEDIA: json.dumps(infos), PROP_SOURCE: source}

    boards = meta.get("boards") or []
    if stage == "board" and len(boards) > 1:
        base_dir = os.path.dirname(source)
        panels = [p for p in (url_to_path(b.get("url", ""), base_dir) for b in boards) if p and os.path.exists(p)]
        if len(panels) > 1:
            cuts = [frame + round(i * length / len(panels)) for i in range(len(panels) + 1)]
            for i, path in enumerate(panels):
                strip = _new_media_strip(coll, f"{clip.name}.{i + 1}", {"kind": "image", "path": path}, channel, cuts[i], cuts[i + 1] - cuts[i], 0)
                for k, v in common.items():
                    strip[k] = v
                strip[PROP_STAGE] = stage
                strip[PROP_PANEL] = i
                created.append(strip)
            report.strips += len(created)
            report.stages[stage] = report.stages.get(stage, 0) + 1
            return created

    if info is None:
        strip = new_effect(coll, clip.name, "COLOR", channel, frame, length)
        strip.color = (0.12, 0.12, 0.14)
        report.placeholders += 1
    else:
        strip = _new_media_strip(coll, clip.name, info, channel, frame, length, _source_offset(clip, info, rate))
        report.strips += 1
        report.stages[stage] = report.stages.get(stage, 0) + 1
    for k, v in common.items():
        strip[k] = v
    strip[PROP_STAGE] = stage or ""
    created.append(strip)
    return created


def import_timeline(
    context,
    filepath: str,
    *,
    prefer=DEFAULT_PREFER,
    first_channel: int = 1,
    start_frame: int = 1,
    labels: bool = True,
    set_scene: bool = True,
    replace: bool = True,
) -> ImportReport:
    scene = context.scene
    timeline = otio.adapters.read_from_file(filepath)
    base_dir = os.path.dirname(os.path.abspath(filepath))
    report = ImportReport()
    coll = strips_of(scene)

    if replace:
        for strip in all_strips(scene):
            if strip.get(PROP_SOURCE) == filepath:
                coll.remove(strip)

    rate = configure_scene(scene, timeline, start_frame) if set_scene else scene.render.fps / scene.render.fps_base
    origin = start_frame

    video = [t for t in timeline.tracks if t.kind == otio.schema.TrackKind.Video]
    audio = [t for t in timeline.tracks if t.kind == otio.schema.TrackKind.Audio]
    channel = first_channel
    label_channel = first_channel + len(video) + len(audio)
    label_spans = []

    for track in video + audio:
        for item in track:
            if isinstance(item, otio.schema.Gap):
                continue
            if isinstance(item, otio.schema.Transition):
                report.skipped.append(f"transition {item.name}")
                continue
            if not isinstance(item, otio.schema.Clip):
                report.skipped.append(f"{type(item).__name__} {item.name}")
                continue
            span = item.range_in_parent()
            frame = origin + round(span.start_time.rescaled_to(rate).value)
            length = max(1, round(span.duration.rescaled_to(rate).value))
            meta = plain(item.metadata.get("helloworld", {}))
            infos = _stage_infos(item, base_dir)
            if track.kind == otio.schema.TrackKind.Audio:
                infos = {k: v for k, v in infos.items() if v["kind"] in ("sound", "movie")}
                for v in infos.values():
                    v["kind"] = "sound"
            stage = _pick_stage(infos, prefer, item.active_media_reference_key)
            _place_clip(coll, scene, item, meta, infos, stage, channel, frame, length, rate, filepath, report)
            for marker in item.markers:
                at = frame + round(marker.marked_range.start_time.rescaled_to(rate).value - (item.source_range.start_time.rescaled_to(rate).value if item.source_range else 0))
                scene.timeline_markers.new(marker.name, frame=at)
            if track.kind == otio.schema.TrackKind.Video and labels and meta:
                label_spans.append((frame, length, label_for(meta, item.name), item.name))
        channel += 1

    for frame, length, text, name in label_spans:
        strip = new_effect(coll, f"label {name}", "TEXT", label_channel, frame, length)
        strip.text = text
        strip.font_size = 28
        strip.use_box = True
        strip.box_color = (0, 0, 0, 0.6)
        strip.location = (0.03, 0.06)
        strip.anchor_x, strip.anchor_y = "LEFT", "BOTTOM"
        if hasattr(strip, "alignment_x"):
            strip.alignment_x = "LEFT"
        strip[PROP_SOURCE] = filepath
        strip[PROP_CLIP] = name
        strip["hw_label"] = True
    return report


# -- swap stage ---------------------------------------------------------------------------------


def swap_stage(context, strips, stage: str) -> tuple[int, int]:
    """Show ``stage`` media in these strips, keeping their place and length. Returns (swapped, missing)."""
    scene = context.scene
    coll = strips_of(scene)
    swapped = missing = 0
    groups: dict[tuple, list] = {}
    for strip in strips:
        if PROP_MEDIA not in strip or strip.get("hw_label"):
            continue
        key = (strip.get(PROP_SOURCE), strip.get(PROP_CLIP), strip.channel)
        groups.setdefault(key, []).append(strip)

    for (source, clip_name, channel), members in groups.items():
        infos = json.loads(members[0][PROP_MEDIA])
        if members[0].get(PROP_STAGE) == stage:
            continue
        info = infos.get(stage)
        if not info or not media_exists(info):
            missing += 1
            continue
        start = min(strip_start(s) for s in members)
        end = max(strip_end(s) for s in members)
        props = {k: members[0][k] for k in (PROP_CLIP, PROP_META, PROP_MEDIA, PROP_SOURCE)}
        for s in members:
            coll.remove(s)
        # Previs and final renders are delivered cut to the shot, so they play from their first frame.
        strip = _new_media_strip(coll, clip_name, info, channel, start, end - start, 0)
        for k, v in props.items():
            strip[k] = v
        strip[PROP_STAGE] = stage
        swapped += 1
    return swapped, missing


# -- export -------------------------------------------------------------------------------------


def _clip_from_strip(strip, rate: float, base_dir: Optional[str]):
    start_in_media = round(strip_start(strip) - content_start(strip))
    length = strip_end(strip) - strip_start(strip)
    name = strip.get(PROP_CLIP) or strip.name
    t = strip.type
    if t == "IMAGE":
        directory = bpy.path.abspath(strip.directory)
        elements = list(strip.elements)
        if len(elements) > 1:
            first = elements[0].filename
            stem, ext = os.path.splitext(first)
            digits = len(stem) - len(stem.rstrip("0123456789"))
            prefix, number = stem[: len(stem) - digits], int(stem[len(stem) - digits:] or 0)
            ref = otio.schema.ImageSequenceReference(
                target_url_base=path_to_url(directory, base_dir).rstrip("/") + "/",
                name_prefix=prefix,
                name_suffix=ext,
                start_frame=number,
                frame_zero_padding=digits,
                rate=rate,
                available_range=otio.opentime.TimeRange(
                    otio.opentime.RationalTime(number, rate), otio.opentime.RationalTime(len(elements), rate)
                ),
            )
            source = otio.opentime.TimeRange(
                otio.opentime.RationalTime(number + start_in_media, rate), otio.opentime.RationalTime(length, rate)
            )
        else:
            path = os.path.join(directory, elements[0].filename) if elements else directory
            source = otio.opentime.TimeRange(otio.opentime.RationalTime(0, rate), otio.opentime.RationalTime(length, rate))
            ref = otio.schema.ExternalReference(target_url=path_to_url(path, base_dir), available_range=source)
    elif t in ("MOVIE", "SOUND"):
        path = strip.filepath if t == "MOVIE" else strip.sound.filepath
        total = content_length(strip)
        ref = otio.schema.ExternalReference(
            target_url=path_to_url(path, base_dir),
            available_range=otio.opentime.TimeRange(otio.opentime.RationalTime(0, rate), otio.opentime.RationalTime(total, rate)),
        )
        source = otio.opentime.TimeRange(otio.opentime.RationalTime(start_in_media, rate), otio.opentime.RationalTime(length, rate))
    elif t == "COLOR":
        source = otio.opentime.TimeRange(otio.opentime.RationalTime(0, rate), otio.opentime.RationalTime(length, rate))
        ref = otio.schema.GeneratorReference(generator_kind="SolidColor", parameters={"color": list(strip.color)}, available_range=source)
    else:
        return None

    clip = otio.schema.Clip(name=name, source_range=source)
    stage = strip.get(PROP_STAGE) or "DEFAULT_MEDIA"
    refs = {stage: ref}
    # Keep the other stages known for this clip, so a round trip doesn't drop boards or renders.
    if PROP_MEDIA in strip:
        for key, info in json.loads(strip[PROP_MEDIA]).items():
            if key == stage or info["kind"] == "sequence":
                continue
            refs[key] = otio.schema.ExternalReference(target_url=path_to_url(info["path"], base_dir))
    clip.set_media_references(refs, stage)
    if PROP_META in strip:
        clip.metadata["helloworld"] = json.loads(strip[PROP_META])
    clip.metadata["blender"] = {"strip": strip.name, "channel": strip.channel}
    return clip


def export_timeline(context, filepath: str, *, relative_paths: bool = True, include_labels: bool = False) -> int:
    scene = context.scene
    rate = scene.render.fps / scene.render.fps_base
    base_dir = os.path.dirname(os.path.abspath(filepath)) if relative_paths else None
    timeline = otio.schema.Timeline(name=scene.get("hw_title") or scene.name)
    timeline.global_start_time = otio.opentime.RationalTime(0, rate)

    strips = [s for s in all_strips(scene) if not s.mute and (include_labels or not s.get("hw_label"))]
    by_channel: dict[int, list] = {}
    for strip in strips:
        if strip.type in ("IMAGE", "MOVIE", "SOUND", "COLOR"):
            by_channel.setdefault(strip.channel, []).append(strip)

    count = 0
    for channel in sorted(by_channel):
        members = sorted(by_channel[channel], key=strip_start)
        kind = otio.schema.TrackKind.Audio if all(s.type == "SOUND" for s in members) else otio.schema.TrackKind.Video
        track = otio.schema.Track(name=f"Channel {channel}", kind=kind)
        cursor = scene.frame_start
        merged: list = []
        for strip in members:
            # Panels of one multi-board shot go back out as a single clip.
            if merged and strip.get(PROP_PANEL) is not None and merged[-1][0].get(PROP_CLIP) == strip.get(PROP_CLIP) \
                    and strip_end(merged[-1][-1]) == strip_start(strip):
                merged[-1].append(strip)
            else:
                merged.append([strip])
        for group in merged:
            first, last = group[0], group[-1]
            if strip_start(first) > cursor:
                track.append(otio.schema.Gap(duration=otio.opentime.RationalTime(strip_start(first) - cursor, rate)))
            elif strip_start(first) < cursor:
                continue  # overlapping strips on one channel can't happen in Blender; be safe
            clip = _clip_from_strip(first, rate, base_dir)
            if clip is None:
                continue
            if len(group) > 1:
                clip.source_range = otio.opentime.TimeRange(
                    clip.source_range.start_time, otio.opentime.RationalTime(strip_end(last) - strip_start(first), rate)
                )
                ref = clip.media_reference
                if hasattr(ref, "available_range"):
                    ref.available_range = clip.source_range
            track.append(clip)
            cursor = strip_end(last)
            count += 1
        timeline.tracks.append(track)

    for marker in scene.timeline_markers:
        timeline.tracks.markers.append(
            otio.schema.Marker(
                name=marker.name,
                marked_range=otio.opentime.TimeRange(
                    otio.opentime.RationalTime(marker.frame - scene.frame_start, rate), otio.opentime.RationalTime(0, rate)
                ),
            )
        )
    otio.adapters.write_to_file(timeline, filepath)
    return count
