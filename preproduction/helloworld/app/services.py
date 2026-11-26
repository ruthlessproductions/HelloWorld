"""What's installed and running: Docker and the Kitsu + AYON stack, Open Shot Designer, Blender."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from . import config

SERVICES = ("kitsu", "ayon", "kitsu-processor", "postgres", "redis")


def _run(argv: list[str], timeout: float = 8) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def http_up(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except Exception:
        return False


# -- the stack ----------------------------------------------------------------------------------


def stack_env() -> dict[str, str]:
    return config.stack().load_env()


def compose_argv(*args: str) -> list[str]:
    env_file = config.STACK_DIR / ".env"
    return ["docker", "compose", "-f", str(config.STACK_DIR / "compose.yml"), "--env-file", str(env_file),
            "--profile", "sync", *args]


def urls(env: Optional[dict] = None) -> dict[str, str]:
    env = env if env is not None else stack_env()
    return {"kitsu": f"http://localhost:{env.get('KITSU_PORT', '8080')}",
            "ayon": f"http://localhost:{env.get('AYON_PORT', '5005')}"}


def docker_status() -> dict:
    info = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=6)
    if info is None:
        return {"installed": shutil.which("docker") is not None, "running": False}
    running = info.returncode == 0 and bool(info.stdout.strip())
    return {"installed": True, "running": running, "version": info.stdout.strip() if running else None}


def images_status() -> dict:
    mod = config.stack()
    names = {"ayon": f"helloworld/ayon-server:{mod.AYON_VERSION}",
             "processor": f"helloworld/ayon-kitsu-processor:{mod.KITSU_ADDON_VERSION}"}
    out = {}
    for key, image in names.items():
        result = _run(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout=6)
        out[key] = {"image": image, "built": bool(result and result.returncode == 0)}
    return out


def containers() -> dict[str, dict]:
    """compose service -> {state, health}; empty when nothing was ever started."""
    if not (config.STACK_DIR / ".env").exists():
        return {}
    result = _run(compose_argv("ps", "-a", "--format", "json"), timeout=8)
    if not result or result.returncode != 0:
        return {}
    text = result.stdout.strip()
    rows = []
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return {r.get("Service"): {"state": r.get("State"), "health": r.get("Health") or ""} for r in rows}


# -- Open Shot Designer -------------------------------------------------------------------------


def osd_status() -> dict:
    index = config.OSD_DIST / "index.html"
    built = index.is_file() and config.OSD_BASE in index.read_text(errors="ignore")
    return {
        "checkout": (config.OSD_DIR / "package.json").is_file(),
        "built": built,
        "npm": shutil.which("npm") is not None,
        "url": config.OSD_BASE,
    }


# -- Blender ------------------------------------------------------------------------------------


def find_blender() -> Optional[Path]:
    candidates = [os.environ.get("HELLOWORLD_BLENDER"), "/Applications/Blender.app/Contents/MacOS/Blender",
                  str(Path.home() / "Applications/Blender.app/Contents/MacOS/Blender"), shutil.which("blender")]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return Path(c)
    return None


def blender_version(binary: Path) -> Optional[str]:
    plist = binary.parent.parent / "Info.plist"
    if plist.is_file():
        try:
            return plistlib.loads(plist.read_bytes()).get("CFBundleShortVersionString")
        except Exception:
            pass
    result = _run([str(binary), "--version"], timeout=20)
    if result and result.stdout.startswith("Blender "):
        return result.stdout.split()[1]
    return None


def blender_config_dir(version: str) -> Path:
    if os.environ.get("BLENDER_USER_RESOURCES"):  # Blender's own override for its user folder
        return Path(os.environ["BLENDER_USER_RESOURCES"])
    major_minor = ".".join(version.split(".")[:2])
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Blender"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / "Blender Foundation" / "Blender"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "blender"
    return base / major_minor


def _addon_digest(folder: Path) -> str:
    digest = hashlib.sha1()
    for name in ("__init__.py", "vse_otio.py", "blender_manifest.toml"):
        path = folder / name
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()


def blender_status() -> dict:
    binary = find_blender()
    if binary is None:
        return {"found": False}
    version = blender_version(binary) or "?"
    cfg = blender_config_dir(version)
    installed = cfg / "extensions" / "user_default" / "helloworld_otio"
    deps = cfg / "extensions" / ".user" / "user_default" / "helloworld_otio" / "site-packages"
    addon = "missing"
    if (installed / "blender_manifest.toml").is_file():
        addon = "installed" if _addon_digest(installed) == _addon_digest(config.ADDON_SRC) else "outdated"
    return {
        "found": True, "path": str(binary), "version": version, "addon": addon,
        "otio": (deps / "opentimelineio").is_dir(),
        "supported": tuple(int(x) for x in version.split(".")[:2] if x.isdigit()) >= (4, 2),
    }


# -- cached snapshot for the page ---------------------------------------------------------------


class StatusCache:
    """The page polls the status, and collecting it takes a few seconds (docker, Blender).

    Answer from the last snapshot right away and refresh it in the background when it's stale.
    """

    def __init__(self, ttl: float = 2.5):
        self.ttl = ttl
        self._value: Optional[dict] = None
        self._at = 0.0
        self._refreshing = False
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        self._at = 0.0
        self._refresh_soon()

    def get(self, fresh: bool = False) -> dict:
        with self._lock:
            value, age = self._value, time.monotonic() - self._at
        if value is None or fresh:
            return self._refresh()
        if age > self.ttl:
            self._refresh_soon()
        return value

    def _refresh_soon(self) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self) -> dict:
        try:
            value = self._collect()
            with self._lock:
                self._value, self._at = value, time.monotonic()
            return value
        finally:
            with self._lock:
                self._refreshing = False

    def _collect(self) -> dict:
        env = stack_env()
        link = urls(env)
        with ThreadPoolExecutor(max_workers=6) as pool:
            docker_f = pool.submit(docker_status)
            rows_f = pool.submit(containers)
            images_f = pool.submit(images_status)
            blender_f = pool.submit(blender_status)
            kitsu_f = pool.submit(http_up, link["kitsu"] + "/api")
            ayon_f = pool.submit(http_up, link["ayon"] + "/api/info")
            docker, rows, images = docker_f.result(), rows_f.result(), images_f.result()
            blender, kitsu_up, ayon_up = blender_f.result(), kitsu_f.result(), ayon_f.result()
        if not docker.get("running"):
            rows, images = {}, {}
        services = {name: rows.get(name, {"state": "absent", "health": ""}) for name in SERVICES}
        running = [n for n, s in services.items() if s["state"] == "running"]
        if len(running) == len(SERVICES) and kitsu_up and ayon_up:
            overall = "running"
        elif running:
            overall = "starting"  # some containers up, or Kitsu/AYON not answering yet
        else:
            overall = "stopped"
        return {
            "docker": docker,
            "images": images,
            "stack": {"state": overall, "services": services, "configured": bool(env),
                      "kitsu": {"url": link["kitsu"], "up": kitsu_up and services["kitsu"]["state"] == "running"},
                      "ayon": {"url": link["ayon"], "up": ayon_up and services["ayon"]["state"] == "running"}},
            "osd": osd_status(),
            "blender": blender,
        }
