"""The HelloWorld web app's server: the page, its JSON API, Open Shot Designer and WebDAV."""

from __future__ import annotations

import mimetypes
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

from .. import __version__
from . import config, services, tracking, webdav
from .jobs import JobRunner
from .projects import Project, ProjectError, Projects

STATIC = Path(__file__).parent / "static"
MAKE_EDIT = Path(__file__).parent / "blender_make_edit.py"
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


def create_app(settings: config.Settings) -> FastAPI:
    app = FastAPI(title="HelloWorld", docs_url=None, redoc_url=None, openapi_url=None)
    projects = Projects(settings.projects_dir)
    jobs = JobRunner()
    status = services.StatusCache()
    hw = [sys.executable, "-m", "helloworld"]
    stack_py = [sys.executable, str(config.STACK_DIR / "setup.py")]
    hosts = {f"localhost:{settings.port}", f"127.0.0.1:{settings.port}", f"[::1]:{settings.port}"}
    origins = {f"http://{h}" for h in hosts}

    # Only this machine's browser, only this page: refuse other host names (DNS rebinding) and
    # changes requested by other sites.
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host", "") not in hosts:
            return PlainTextResponse("HelloWorld only answers on localhost.", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site")
            if (origin and origin not in origins) or (site and site not in ("same-origin", "none")):
                return PlainTextResponse("Cross-site request refused.", status_code=403)
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith(("/static/", "/api/")):
            response.headers.setdefault("Cache-Control", "no-cache")
        elif request.url.path.startswith("/dav/"):
            # Plans change underneath the browser (uploads, other tabs); a cached GET would open an
            # old plan and a stale ETag would make the next save look like a conflict.
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(webdav.router(projects, settings.dav_password))

    # -- helpers --------------------------------------------------------------------------------

    def project_or_404(name: str) -> Project:
        try:
            return projects.get(name)
        except KeyError:
            raise HTTPException(404, f"No project named {name!r}")

    def kitsu_env() -> dict:
        env = services.stack_env()
        return {"KITSU_HOST": services.urls(env)["kitsu"], "KITSU_EMAIL": env.get("KITSU_EMAIL", ""),
                "KITSU_PASSWORD": env.get("KITSU_PASSWORD", "")}

    def started(job) -> dict:
        return {"job": job.summary()}

    def require_stack(ayon: bool = False) -> None:
        state = status.get()["stack"]
        if not state["kitsu"]["up"] or (ayon and not state["ayon"]["up"]):
            raise HTTPException(409, "Start Kitsu and AYON first (Start services).")

    def refresh_status(_job=None) -> None:
        status.invalidate()

    def blender_binary() -> str:
        found = services.find_blender()
        if found is None:
            raise HTTPException(409, "Blender isn't installed in /Applications.")
        return str(found)

    def cut_steps(project: Project, force: bool = False) -> list:
        """Rebuild the cut from the plan, then re-attach previews and renders already on disk."""
        steps = []
        if force or not project.cut.is_file():
            steps.append(("Build the cut from the plan",
                          hw + ["animatic", str(project.plan), "-o", str(project.cut)], project.folder, None))
            if project.media.is_dir():
                for stage_dir in sorted(p for p in project.media.iterdir() if p.is_dir()):
                    if project.has_media(stage_dir):
                        steps.append((f"Re-attach {stage_dir.name} media",
                                      hw + ["conform", str(project.cut), str(stage_dir), "--stage", stage_dir.name],
                                      project.folder, None))
            if project.has_media(project.renders):
                steps.append(("Re-attach renders as final",
                              hw + ["conform", str(project.cut), str(project.renders), "--stage", "final"],
                              project.folder, None))
        return steps

    def make_edit_step(project: Project, blender: str) -> tuple:
        return ("Make the Blender edit from the cut",
                [blender, "--background", "--app-template", "Video_Editing", "--python", str(MAKE_EDIT), "--",
                 "--otio", str(project.cut), "--save", str(project.edit)], project.folder, None)

    def launch_blender(blender: str, path: Path):
        def step(log):
            subprocess.Popen([blender, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            log(f"Opened {path.name} in Blender")
        return ("Open Blender", step)

    # -- page and static files ------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/static/{path:path}", include_in_schema=False)
    def static(path: str):
        target = (STATIC / path).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target)

    @app.get("/OpenShotDesigner", include_in_schema=False)
    def osd_root():
        return RedirectResponse(config.OSD_BASE)

    @app.get(config.OSD_BASE + "{path:path}", include_in_schema=False)
    def osd_files(path: str):
        root = config.OSD_DIST.resolve()
        target = (root / (path or "index.html")).resolve()
        if root not in target.parents and target != root:
            raise HTTPException(404)
        if not target.is_file():
            if not (root / "index.html").is_file():
                return PlainTextResponse("Open Shot Designer isn't set up yet: use Setup in HelloWorld.", status_code=404)
            target = root / "index.html"
        headers = {"Cache-Control": "no-cache"} if target.name in ("index.html", "sw.js") else {}
        return FileResponse(target, headers=headers)

    # -- status, settings and jobs --------------------------------------------------------------

    @app.get("/api/ping")
    def ping():
        return {"app": "helloworld", "version": __version__}

    @app.get("/api/status")
    def get_status():
        home = str(Path.home())
        shown = str(settings.projects_dir)
        if shown.startswith(home + "/"):
            shown = "~" + shown[len(home):]
        return {**status.get(), "projects_dir": shown, "version": __version__}

    @app.get("/api/settings")
    def get_settings():
        env = services.stack_env()
        link = services.urls(env)
        return {
            "kitsu": {"url": link["kitsu"], "email": env.get("KITSU_EMAIL", ""), "password": env.get("KITSU_PASSWORD", "")},
            "ayon": {"url": link["ayon"], "user": "admin", "password": env.get("AYON_ADMIN_PASSWORD", "")},
            "dav": {"url": f"{settings.base_url}/dav", "user": "helloworld", "password": settings.dav_password},
            "projects_dir": str(settings.projects_dir),
        }

    @app.get("/api/jobs")
    def list_jobs():
        return jobs.list()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int, offset: int = 0):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404)
        return {**job.summary(), "offset": offset, "lines": job.lines[offset:]}

    # -- services -------------------------------------------------------------------------------

    @app.post("/api/stack/{action}")
    def stack_action(action: str):
        if action == "start":
            steps = [("Start Kitsu and AYON", stack_py + ["up"], config.ROOT, None)]
            title = "Start Kitsu and AYON"
        elif action == "stop":
            steps = [("Stop Kitsu and AYON", stack_py + ["down"], config.ROOT, None)]
            title = "Stop Kitsu and AYON"
        elif action == "build":
            steps = [("Build the AYON images (this takes a while)", stack_py + ["build"], config.ROOT, None)]
            title = "Build the AYON images"
        else:
            raise HTTPException(404)
        status.invalidate()
        return started(jobs.start(title, "stack", steps, on_done=refresh_status))

    @app.post("/api/osd/setup")
    def osd_setup():
        if shutil.which("npm") is None:
            raise HTTPException(409, "Open Shot Designer needs Node.js (https://nodejs.org) to build.")
        steps = []
        if not (config.OSD_DIR / "package.json").is_file():
            steps.append(("Download Open Shot Designer",
                          ["git", "clone", "--depth", "1", config.OSD_REPO, str(config.OSD_DIR)], config.ROOT, None))
        steps.append(("Install its packages", ["npm", "ci", "--no-audit", "--no-fund"], config.OSD_DIR, None))
        steps.append(("Build it", ["npm", "run", "build"], config.OSD_DIR, {"GH_PAGES": "true"}))
        return started(jobs.start("Set up Open Shot Designer", "osd", steps, on_done=refresh_status))

    @app.post("/api/blender/install")
    def blender_install():
        blender = blender_binary()
        state = services.blender_status()
        if not state.get("supported"):
            raise HTTPException(409, f"Blender {state.get('version')} is too old; the add-on needs 4.2 or newer.")
        out_dir = config.APP_DATA / "dist"
        out_dir.mkdir(parents=True, exist_ok=True)

        def package(log):
            for old in out_dir.glob("helloworld_otio-*.zip"):
                old.unlink()
            result = subprocess.run([blender, "--command", "extension", "build", "--source-dir", str(config.ADDON_SRC),
                                     "--output-dir", str(out_dir)], capture_output=True, text=True)
            log(result.stdout.strip())
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "extension build failed")

        def install(log):
            zip_path = next(out_dir.glob("helloworld_otio-*.zip"))
            result = subprocess.run([blender, "--command", "extension", "install-file", "-r", "user_default", "-e",
                                     str(zip_path)], capture_output=True, text=True)
            log("\n".join(l for l in result.stdout.splitlines() if "Reloading" not in l))
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "extension install failed")

        steps = [("Package the HelloWorld OTIO add-on", package), ("Install it in Blender", install)]
        if not state.get("otio"):
            expr = ("import bpy, sys; r = bpy.ops.helloworld.install_otio(); print('OpenTimelineIO', r); "
                    "sys.exit(0 if r == {'FINISHED'} else 1)")
            steps.append(("Download OpenTimelineIO for Blender",
                          [blender, "--background", "--online-mode", "--python-expr", expr], None, None))
        return started(jobs.start("Install the Blender add-on", "blender", steps, on_done=refresh_status))

    # -- projects -------------------------------------------------------------------------------

    @app.get("/api/projects")
    def list_projects():
        return [projects.summary(p) for p in projects.all()]

    @app.post("/api/projects")
    async def upload_project(file: UploadFile = File(...)):
        try:
            project, created = projects.save_plan(await file.read())
        except ProjectError as exc:
            raise HTTPException(415, str(exc))
        return {"name": project.name, "created": created}

    @app.post("/api/projects/{name}/plan")
    async def update_plan(name: str, file: UploadFile = File(...)):
        project = project_or_404(name)
        try:
            project, _ = projects.save_plan(await file.read(), name=project.name)
        except ProjectError as exc:
            raise HTTPException(415, str(exc))
        return {"name": project.name}

    @app.get("/api/projects/{name}")
    def project_detail(name: str):
        project = project_or_404(name)
        try:
            return projects.detail(project)
        except Exception as exc:
            raise HTTPException(422, f"Can't read this project's plan: {exc}")

    @app.get("/api/projects/{name}/plan.osd")
    def download_plan(name: str):
        project = project_or_404(name)
        return FileResponse(project.plan, media_type="application/zip", filename=f"{project.name}.osd")

    @app.get("/api/projects/{name}/boards/{shot_id}/{index}")
    def board_image(name: str, shot_id: str, index: int):
        project = project_or_404(name)
        shot = next((s for s in projects.production(project).shots if s.id == shot_id), None)
        if shot is None or not 0 <= index < len(shot.boards):
            raise HTTPException(404)
        loaded = shot.boards[index].load()
        if loaded is None:
            raise HTTPException(404)
        body, mime = loaded
        return Response(body, media_type=mime, headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/projects/{name}/tracking")
    def project_tracking(name: str):
        project = project_or_404(name)
        title = projects.production(project).title
        state = status.get()["stack"]
        if not state["kitsu"]["up"]:
            return {"online": False}
        out = {"online": True, "kitsu": tracking.safe(tracking.kitsu_project, title)}
        out["ayon"] = tracking.safe(tracking.ayon_project, title) if state["ayon"]["up"] else {"error": "AYON is not running"}
        return out

    @app.get("/api/kitsu/task-types")
    def kitsu_task_types():
        if not status.get()["stack"]["kitsu"]["up"]:
            return []
        try:
            return tracking.task_types()
        except Exception:
            return []

    @app.post("/api/projects/{name}/actions/{action}")
    def project_action(name: str, action: str, options: Optional[dict] = Body(default=None)):
        project = project_or_404(name)
        options = options or {}
        title = projects.production(project).title
        if action == "push":
            require_stack()
            steps = [("Push the plan to Kitsu", hw + ["kitsu", "push", str(project.plan)], project.folder, kitsu_env())]
            label = "Push to Kitsu"
        elif action == "sync-ayon":
            require_stack(ayon=True)
            steps = [("Pair with AYON and sync", stack_py + ["pair", title], config.ROOT, None)]
            label = "Sync to AYON"
        elif action == "build-cut":
            steps = cut_steps(project, force=True)
            label = "Build the cut"
        elif action == "pull":
            require_stack()
            task_type = str(options.get("task_type") or "Layout")
            stage = str(options.get("stage") or "previs")
            if stage not in ("previs", "final"):
                raise HTTPException(400, "stage must be previs or final")
            steps = cut_steps(project) + [(f"Pull the newest {task_type} previews from Kitsu as {stage}",
                                           hw + ["kitsu", "pull", str(project.cut), "--task-type", task_type,
                                                 "--stage", stage, "--kitsu-project", title],
                                           project.folder, kitsu_env())]
            label = f"Pull {task_type} from Kitsu"
        elif action == "attach-renders":
            if not project.has_media(project.renders):
                raise HTTPException(409, "No renders yet. Put them in the project's renders folder, named after "
                                         "their shots (SC001_SH002_v001.mov), then attach them.")
            steps = cut_steps(project) + [("Attach renders as final",
                                           hw + ["conform", str(project.cut), str(project.renders), "--stage", "final"],
                                           project.folder, None)]
            label = "Attach renders"
        elif action in ("open-blender", "rebuild-edit"):
            blender = blender_binary()
            if services.blender_status().get("addon") == "missing":
                raise HTTPException(409, "Install the Blender add-on first (Setup).")
            steps = cut_steps(project)
            if action == "rebuild-edit" and project.edit.is_file():
                def backup(log, project=project):
                    project.history.mkdir(exist_ok=True)
                    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(project.edit.stat().st_mtime))
                    target = project.history / f"edit_{stamp}.blend"
                    shutil.move(str(project.edit), target)
                    log(f"Kept the previous edit as history/{target.name}")
                steps.append(("Set the current edit aside", backup))
            if action == "rebuild-edit" or not project.edit.is_file():
                steps.append(make_edit_step(project, blender))
            steps.append(launch_blender(blender, project.edit))
            label = "Open in Blender" if action == "open-blender" else "Rebuild the Blender edit"
        else:
            raise HTTPException(404, f"Unknown action {action}")
        return started(jobs.start(f"{label}: {project.name}", action, steps, project=project.name))

    @app.post("/api/projects/{name}/reveal")
    def reveal(name: str, target: str = Body("folder", embed=True)):
        project = project_or_404(name)
        path = {"folder": project.folder, "renders": project.renders}.get(target)
        if path is None:
            raise HTTPException(400)
        path.mkdir(exist_ok=True)
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as resp:
            return b"helloworld" in resp.read()
    except Exception:
        return False


def serve(port: Optional[int] = None, projects_dir: Optional[str] = None, open_browser: bool = True) -> int:
    import uvicorn

    settings = config.load_settings(projects_dir=projects_dir, port=port)
    url = settings.base_url + "/"
    if already_running(settings.port):
        print(f"HelloWorld is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return 0
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    print(f"HelloWorld {__version__} at {url}  (projects in {settings.projects_dir}; Ctrl-C to quit)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, log_level="warning")
    return 0
