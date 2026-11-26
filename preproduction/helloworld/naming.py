"""Shared names, so Kitsu, AYON, OTIO and Blender all refer to a shot the same way.

Scene "12" becomes sequence ``SC012``. Open Shot Designer numbers shots two ways and both are
kept recognisable: ``12/3`` (scene/index, inserts ``12/3A``) becomes shot ``SH003`` / ``SH003A``;
lettered setups ``12A`` stay ``12A``. The exact slate text travels separately as metadata.

In an OTIO timeline the clip is named ``SC012_SH003``, which Kitsu's OTIO import reads with the
naming convention ``${sequence_name}_${shot_name}`` (see :data:`KITSU_OTIO_NAMING`), so names
never contain ``_`` or ``-``.
"""

from __future__ import annotations

import re

KITSU_OTIO_NAMING = "${sequence_name}_${shot_name}"


def _clean(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", text).upper()


def sequence_name(scene_number: str) -> str:
    text = scene_number.strip()
    match = re.match(r"^(\d+)(.*)$", text)
    if match:
        return f"SC{int(match.group(1)):03d}{_clean(match.group(2))}"
    return f"SC{_clean(text) or 'X'}"


def shot_name(shot_number: str, index: int) -> str:
    text = shot_number.strip().upper()
    slashed = "/" in text
    if slashed:
        text = text.rsplit("/", 1)[1]
    match = re.match(r"^(\d+)([A-Z]*)$", text)
    if match and (slashed or not match.group(2)):
        return f"SH{int(match.group(1)):03d}{match.group(2)}"
    return _clean(text) or f"SH{index + 1:03d}"


def clip_name(sequence: str, shot: str) -> str:
    return f"{sequence}_{shot}"
