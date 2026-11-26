"""Read-only views of a film in Kitsu and AYON, for the project page."""

from __future__ import annotations

import threading

from . import config, services

_kitsu_lock = threading.Lock()  # gazu keeps one global client


def _kitsu_login() -> dict:
    import gazu

    env = services.stack_env()
    host = services.urls(env)["kitsu"] + "/api"
    if gazu.get_host() != host or not getattr(_kitsu_login, "ok", False):
        gazu.set_host(host)
        gazu.log_in(env["KITSU_EMAIL"], env["KITSU_PASSWORD"])
        _kitsu_login.ok = True
    return env


def kitsu_project(title: str) -> dict:
    """Shots of the film in Kitsu with each task's status, keyed by clip name (SC001_SH002)."""
    import gazu

    with _kitsu_lock:
        try:
            _kitsu_login()
            project = gazu.project.get_project_by_name(title)
        except Exception:
            _kitsu_login.ok = False
            raise
        url = services.urls()["kitsu"]
        if project is None:
            return {"exists": False, "url": url}
        sequences = {s["id"]: s["name"] for s in gazu.shot.all_sequences_for_project(project)}
        shots = {s["id"]: f"{sequences.get(s.get('parent_id') or s.get('sequence_id'), '')}_{s['name']}"
                 for s in gazu.shot.all_shots_for_project(project)}
        types = {t["id"]: t for t in gazu.task.all_task_types()}
        statuses = {s["id"]: s for s in gazu.task.all_task_statuses()}
        by_clip: dict[str, list] = {}
        used_types: dict[str, dict] = {}
        for task in gazu.task.all_tasks_for_project(project):
            clip = shots.get(task.get("entity_id"))
            task_type = types.get(task.get("task_type_id"))
            status = statuses.get(task.get("task_status_id"))
            if not clip or not task_type:
                continue
            used_types[task_type["name"]] = task_type
            by_clip.setdefault(clip, []).append({
                "type": task_type["name"], "status": (status or {}).get("short_name", "?"),
                "status_name": (status or {}).get("name", ""), "color": (status or {}).get("color", "#888"),
                "priority": task_type.get("priority") or 0,
            })
        for tasks in by_clip.values():
            tasks.sort(key=lambda t: (t["priority"], t["type"]))
        shot_types = [t for t in types.values() if (t.get("for_entity") or "Shot") == "Shot"]
        return {
            "exists": True,
            "url": f"{url}/productions/{project['id']}/shots",
            "shots": len(shots),
            "tasks": by_clip,
            "task_types": sorted({t["name"] for t in shot_types} | set(used_types)),
        }


def ayon_project(title: str) -> dict:
    """Whether the film is paired with an AYON project, and how much of it has synced."""
    mod = config.stack()
    env = services.stack_env()
    ayon = mod.Ayon(env)
    import gazu

    with _kitsu_lock:
        _kitsu_login()
        project = gazu.project.get_project_by_name(title)
    if project is None:
        return {"paired": False, "url": ayon.url}
    pairings = ayon.call("GET", f"/api/addons/kitsu/{mod.KITSU_ADDON_VERSION}/pairing") or []
    paired = next((p for p in pairings if p.get("kitsuProjectId") == project["id"] and p.get("ayonProjectName")), None)
    if not paired:
        return {"paired": False, "url": ayon.url}
    name = paired["ayonProjectName"]
    folders = tasks = 0
    try:
        tree = ayon.call("GET", f"/api/projects/{name}/hierarchy") or {}
        stack = list(tree.get("hierarchy", []))
        while stack:
            node = stack.pop()
            folders += 1
            stack.extend(node.get("children", []))
        query = '{ project(name: "%s") { tasks { edges { node { id } } } } }' % name
        res = ayon.call("POST", "/graphql", {"query": query}) or {}
        tasks = len(((res.get("data") or {}).get("project") or {}).get("tasks", {}).get("edges", []))
    except Exception:
        pass
    return {"paired": True, "project": name, "folders": folders, "tasks": tasks,
            "url": f"{ayon.url}/projects/{name}/overview"}


def task_types() -> list[str]:
    import gazu

    with _kitsu_lock:
        _kitsu_login()
        return sorted(t["name"] for t in gazu.task.all_task_types() if (t.get("for_entity") or "Shot") == "Shot")


def safe(fn, *args) -> dict:
    try:
        return fn(*args)
    except Exception as exc:
        return {"error": str(exc)[:300]}
