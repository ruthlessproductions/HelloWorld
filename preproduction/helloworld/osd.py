"""Read Open Shot Designer projects.

Accepts the three files Open Shot Designer writes:

* ``.osd`` v2: a ZIP with ``manifest.json``, ``project.json`` and ``assets/<asset id>``;
* ``.osd`` v1: JSON with a ``manifest`` (formatVersion 1) and Base64 assets;
* a plain project JSON backup (images inline as data URLs, or asset ids without bytes).

The result is a small, tool-neutral model (:class:`Production` → :class:`Scene` → :class:`Shot`
→ :class:`Board`) that the Kitsu and OTIO exporters share. Field meanings follow
Open Shot Designer's ``src/types/index.ts``.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# The schema this reader was written against (Open Shot Designer 1.15.x). Older projects should
# be opened and re-exported in the app, which migrates them.
KNOWN_SCHEMA_VERSIONS = range(40, 43)

START_SLOT = "start"
END_SLOT = "end"
DEFAULT_SHOT_SECONDS = 3.0

_ASSET_REF = re.compile(r"^asset-(sha256|local)-[A-Za-z0-9-]+$")
_ASPECTS = {"16:9": 16 / 9, "2.39:1": 2.39, "1.85:1": 1.85, "4:3": 4 / 3, "9:16": 9 / 16}


class OsdError(ValueError):
    pass


@dataclass
class Board:
    """One storyboard frame of a shot."""

    slot: str  # "start", a camera waypoint id, or "end"
    label: str  # "Frame", "Start", "Beat 2", "End"
    ref: str  # asset id or data URL, as stored in the project
    note: str = ""
    _loader: Optional[Callable[[str], Optional[tuple[bytes, str]]]] = field(default=None, repr=False)

    def load(self) -> Optional[tuple[bytes, str]]:
        """Return (bytes, mime type), or None if the image isn't in this file."""
        return self._loader(self.ref) if self._loader else None


@dataclass
class Shot:
    id: str
    number: str  # "1A"
    name: str
    size: str  # ELS, WS, FS, MWS, MS, MCU, CU, ECU ...
    lens_mm: Optional[float]
    angle: str
    movement: str
    camera: str  # camera label: "A", "B" ...
    fps: float
    aspect: str  # "16:9", "2.39:1" ...
    est_seconds: float
    description: str  # framing description
    action: str  # action / script notes
    status: str  # planned, rehearsed, ready, taken, omitted
    unplanned: bool
    equipment: str
    boards: list[Board] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return self.est_seconds if self.est_seconds and self.est_seconds > 0 else DEFAULT_SHOT_SECONDS

    @property
    def aspect_ratio(self) -> float:
        return _ASPECTS.get(self.aspect, 16 / 9)


@dataclass
class Scene:
    id: str  # setup id
    number: str  # production scene number: "12", "12A"
    name: str
    location: str
    time_of_day: str  # "Day INT", "Night EXT" ...
    heading: str  # screenplay slugline when linked to the script
    shots: list[Shot] = field(default_factory=list)


@dataclass
class Production:
    id: str
    title: str
    director: str
    cinematographer: str
    company: str
    schema_version: Optional[int]
    scenes: list[Scene] = field(default_factory=list)

    @property
    def shots(self) -> list[Shot]:
        return [shot for scene in self.scenes for shot in scene.shots]

    @property
    def fps(self) -> float:
        rates = [s.fps for s in self.shots if s.fps]
        return max(set(rates), key=rates.count) if rates else 24.0


# -- loading ----------------------------------------------------------------------------------


def load(path: str | Path) -> Production:
    path = Path(path)
    raw = path.read_bytes()
    assets: dict[str, tuple[bytes, str]] = {}

    if raw[:2] == b"PK":
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "project.json" not in names:
                raise OsdError(f"{path.name}: not an Open Shot Designer package (no project.json)")
            project = json.loads(archive.read("project.json"))
            for name in names:
                if not name.startswith("assets/") or name.endswith(".meta.json") or name.endswith("/"):
                    continue
                asset_id = name[len("assets/"):]
                mime = ""
                if f"{name}.meta.json" in names:
                    meta = json.loads(archive.read(f"{name}.meta.json"))
                    mime = meta.get("mimeType") or meta.get("type") or ""
                assets[asset_id] = (archive.read(name), mime)
    else:
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OsdError(f"{path.name}: not an Open Shot Designer project ({exc})") from exc
        if isinstance(data, dict) and (data.get("manifest") or {}).get("formatVersion") == 1:
            project = data.get("project") or {}
            for asset in data.get("assets") or []:
                meta = asset.get("metadata") or {}
                assets[asset["id"]] = (base64.b64decode(asset["dataBase64"]), meta.get("mimeType", ""))
        else:
            project = data

    if not isinstance(project, dict) or "setups" not in project:
        raise OsdError(f"{path.name}: no scenes found (missing 'setups')")

    def loader(ref: str) -> Optional[tuple[bytes, str]]:
        if ref.startswith("data:"):
            header, _, payload = ref.partition(",")
            mime = header[5:].split(";")[0]
            body = base64.b64decode(payload) if ";base64" in header else payload.encode()
            return body, mime
        if ref in assets:
            body, mime = assets[ref]
            return body, mime or _sniff_mime(body)
        return None

    return _production(project, loader)


def _production(project: dict, loader) -> Production:
    version = project.get("schemaVersion")
    production = Production(
        id=str(project.get("id", "")),
        title=str(project.get("title") or "Untitled"),
        director=str(project.get("director") or ""),
        cinematographer=str(project.get("cinematographer") or ""),
        company=str(project.get("productionCompany") or ""),
        schema_version=version if isinstance(version, int) else None,
    )
    headings = _script_headings(project)

    setups = [s for s in project.get("setups") or [] if isinstance(s, dict)]
    for index, setup in enumerate(setups):
        shots = [s for s in setup.get("shots") or [] if isinstance(s, dict)]
        if setup.get("masterPlanForLocationId") and not shots:
            continue  # a location's master floor plan, not a scene
        cameras = {
            el.get("id"): el
            for el in setup.get("elements") or []
            if isinstance(el, dict) and el.get("type") == "camera"
        }
        scene = Scene(
            id=str(setup.get("id", "")),
            number=str(setup.get("sceneNumber") or index + 1),
            name=str(setup.get("name") or ""),
            location=str(setup.get("location") or ""),
            time_of_day=str(setup.get("timeOfDay") or ""),
            heading=headings.get(setup.get("scriptSceneId") or "", ""),
        )
        for raw_shot in _board_order(setup, shots):
            scene.shots.append(_shot(raw_shot, setup, cameras.get(raw_shot.get("cameraId")), loader))
        production.scenes.append(scene)

    production.scenes.sort(key=lambda s: natural_key(s.number))
    return production


def _board_order(setup: dict, shots: list[dict]) -> list[dict]:
    """Shots in storyboard order (the cut), falling back to shot-list order."""
    by_list = sorted(shots, key=lambda s: (s.get("order", 0), natural_key(str(s.get("shotNumber", "")))))
    order = [sid for sid in setup.get("storyboardOrder") or [] if isinstance(sid, str)]
    if not order:
        return by_list
    position = {sid: i for i, sid in enumerate(order)}
    return sorted(by_list, key=lambda s: position.get(s.get("id"), len(order)))


def _shot(raw: dict, setup: dict, camera: Optional[dict], loader) -> Shot:
    lens = raw.get("lensMm")
    shot = Shot(
        id=str(raw.get("id", "")),
        number=str(raw.get("shotNumber") or ""),
        name=str(raw.get("name") or ""),
        size=str(raw.get("shotSize") or ""),
        lens_mm=float(lens) if isinstance(lens, (int, float)) and lens > 0 else None,
        angle=str(raw.get("cameraAngle") or ""),
        movement=str(raw.get("movement") or ""),
        camera=str(raw.get("cameraLabel") or ""),
        fps=float(raw.get("frameRate") or 24),
        aspect=str(raw.get("aspectRatio") or setup.get("aspectRatio") or "16:9"),
        est_seconds=float(raw.get("estDurationSeconds") or 0),
        description=str(raw.get("framingDescription") or ""),
        action=str(raw.get("actionScriptNotes") or ""),
        status=str(raw.get("status") or "planned"),
        unplanned=bool(raw.get("unplanned")),
        equipment=str(raw.get("equipmentNotes") or ""),
    )
    shot.boards = _boards(raw, camera, loader)
    return shot


def _boards(raw: dict, camera: Optional[dict], loader) -> list[Board]:
    """Mirror Open Shot Designer's ``framesOf`` / ``slotsOf`` (utils/storyboardFrames.ts)."""
    frames: dict[str, dict] = {k: v for k, v in (raw.get("storyboardFrames") or {}).items() if isinstance(v, dict)}
    legacy = raw.get("storyboardImage")
    if START_SLOT not in frames and legacy and not any(f.get("image") == legacy for f in frames.values()):
        frames[START_SLOT] = {"image": legacy}
    legacy_end = raw.get("storyboardImageEnd")
    if legacy_end and not any(k != START_SLOT for k in frames):
        frames[END_SLOT] = {"image": legacy_end}

    waypoints = sorted((camera or {}).get("path") or [], key=lambda w: w.get("beat") or 0)
    slots: list[tuple[str, str, Optional[dict]]] = [
        (START_SLOT, "Start" if waypoints else "Frame", frames.get(START_SLOT))
    ]
    for i, wp in enumerate(waypoints):
        last = i == len(waypoints) - 1
        label = "End" if last else f"Beat {wp.get('beat') or i + 2}"
        slots.append((str(wp.get("id")), label, frames.get(wp.get("id")) or (frames.get(END_SLOT) if last else None)))
    if not waypoints and END_SLOT in frames:
        slots.append((END_SLOT, "End", frames[END_SLOT]))

    omitted = raw.get("omittedStoryboardSlots")
    boards = []
    for key, label, frame in slots:
        if key != START_SLOT and isinstance(omitted, list) and key in omitted:
            continue
        if not frame or not frame.get("image"):
            continue
        boards.append(Board(slot=key, label=label, ref=frame["image"], note=str(frame.get("note") or ""), _loader=loader))
    return boards


def _script_headings(project: dict) -> dict[str, str]:
    """Scene heading text by script line id (the id a setup links with ``scriptSceneId``)."""
    out = {}
    for line in project.get("scriptLines") or []:
        if isinstance(line, dict) and line.get("type") == "scene" and line.get("id"):
            out[line["id"]] = str(line.get("text") or "").strip()
    return out


# -- helpers ----------------------------------------------------------------------------------


def natural_key(text: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def extension_for(mime: str) -> str:
    if mime == "image/jpeg":
        return ".jpg"
    return mimetypes.guess_extension(mime or "") or ".png"


def _sniff_mime(body: bytes) -> str:
    if body.startswith(b"\x89PNG"):
        return "image/png"
    if body.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"
