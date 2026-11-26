"""Where things live: the checkout, the stack, Open Shot Designer, projects and app settings."""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # the preproduction/ folder
STACK_DIR = ROOT / "stack"
VENDOR_DIR = ROOT / "vendor"
OSD_DIR = VENDOR_DIR / "osd"
OSD_DIST = OSD_DIR / "dist"
OSD_REPO = "https://github.com/koosoli/OpenShotDesigner.git"
OSD_BASE = "/OpenShotDesigner/"  # the path Open Shot Designer's own build expects (GH_PAGES=true)
ADDON_SRC = ROOT / "blender" / "helloworld_otio"
APP_DATA = ROOT / ".app"
SETTINGS_FILE = APP_DATA / "settings.json"
DEFAULT_PROJECTS = Path.home() / "Documents" / "HelloWorld Projects"
DEFAULT_PORT = 8765


@dataclass
class Settings:
    projects_dir: Path
    port: int
    dav_password: str

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.port}"


def load_settings(projects_dir: str | None = None, port: int | None = None) -> Settings:
    """Settings kept in .app/settings.json (git-ignored); command-line flags win for this run."""
    APP_DATA.mkdir(exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except ValueError:
            data = {}
    changed = False
    if not data.get("dav_password"):
        data["dav_password"] = secrets.token_urlsafe(18)  # Open Shot Designer's WebDAV login
        changed = True
    if changed:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2) + "\n")
        SETTINGS_FILE.chmod(0o600)
    folder = projects_dir or os.environ.get("HELLOWORLD_PROJECTS") or data.get("projects_dir") or DEFAULT_PROJECTS
    return Settings(
        projects_dir=Path(folder).expanduser(),
        port=port or int(data.get("port") or DEFAULT_PORT),
        dav_password=data["dav_password"],
    )


@lru_cache(maxsize=1)
def stack():
    """stack/setup.py as a module (load_env, Ayon, versions ...)."""
    spec = importlib.util.spec_from_file_location("helloworld_stack_setup", STACK_DIR / "setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
