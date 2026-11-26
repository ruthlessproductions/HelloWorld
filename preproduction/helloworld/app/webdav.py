"""Just enough WebDAV for Open Shot Designer's "Nextcloud" panel to open and save plans here.

Open Shot Designer talks to ``<server>/OpenShotDesigner/``: PROPFIND to list ``.osd`` files, MKCOL
to create the folder, GET to open one and PUT (with If-Match / If-None-Match) to save. Here that
folder is the projects folder: ``Sample Production.osd`` is the plan of the "Sample Production"
project, and saving a new name creates a project.
"""

from __future__ import annotations

import base64
import secrets
from email.utils import formatdate
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, Response

from .projects import ProjectError, Projects, safe_name

FOLDER = "OpenShotDesigner"
PREFIX = f"/dav/{FOLDER}/"


def router(projects: Projects, password: str, on_saved=None) -> APIRouter:
    api = APIRouter()

    def authorized(request: Request) -> bool:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("basic "):
            return False
        try:
            _, _, given = base64.b64decode(header[6:]).decode().partition(":")
        except Exception:
            return False
        return secrets.compare_digest(given, password)

    def denied() -> Response:
        # No WWW-Authenticate header, so the browser doesn't pop up its own login box.
        return Response("Wrong WebDAV password: use the one shown in HelloWorld.", status_code=401)

    def entry(href: str, *, collection: bool = False, size: int = 0, etag: str = "", modified: float = 0) -> str:
        props = ["<d:resourcetype><d:collection/></d:resourcetype>" if collection else "<d:resourcetype/>"]
        if not collection:
            props += [f"<d:getcontentlength>{size}</d:getcontentlength>",
                      "<d:getcontenttype>application/zip</d:getcontenttype>",
                      f"<d:getetag>{escape(etag)}</d:getetag>"]
        if modified:
            props.append(f"<d:getlastmodified>{formatdate(modified, usegmt=True)}</d:getlastmodified>")
        return (f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>{''.join(props)}</d:prop>"
                "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")

    def multistatus(entries: list[str]) -> Response:
        body = '<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:">' + "".join(entries) + "</d:multistatus>"
        return Response(body, status_code=207, media_type="application/xml; charset=utf-8")

    def file_entry(project) -> str:
        stat = project.plan.stat()
        return entry(PREFIX + quote(f"{project.name}.osd"), size=stat.st_size,
                     etag=projects.etag(project), modified=stat.st_mtime)

    @api.api_route(f"/dav/{FOLDER}", methods=["PROPFIND", "MKCOL", "OPTIONS"], include_in_schema=False)
    @api.api_route(PREFIX, methods=["PROPFIND", "MKCOL", "OPTIONS"], include_in_schema=False)
    async def folder(request: Request):
        if request.method == "OPTIONS":
            return Response(headers={"DAV": "1", "Allow": "OPTIONS, PROPFIND, MKCOL, GET, PUT"})
        if not authorized(request):
            return denied()
        if request.method == "MKCOL":
            return Response(status_code=405)  # it always exists; Open Shot Designer reads 405 as "already there"
        entries = [entry(PREFIX, collection=True)]
        if request.headers.get("depth", "1") != "0":
            entries += [file_entry(p) for p in projects.all()]
        return multistatus(entries)

    @api.api_route(PREFIX + "{filename}", methods=["GET", "HEAD", "PUT", "PROPFIND"], include_in_schema=False)
    async def plan_file(filename: str, request: Request):
        if not authorized(request):
            return denied()
        if not filename.lower().endswith(".osd"):
            return Response("Only .osd files live here.", status_code=403)
        name = safe_name(filename[:-4])
        try:
            project = projects.get(name)
        except KeyError:
            project = None

        if request.method in ("GET", "HEAD", "PROPFIND"):
            if project is None:
                return Response(status_code=404)
            if request.method == "PROPFIND":
                return multistatus([file_entry(project)])
            body = b"" if request.method == "HEAD" else project.plan.read_bytes()
            return Response(body, media_type="application/zip",
                            headers={"ETag": projects.etag(project),
                                     "Last-Modified": formatdate(project.plan.stat().st_mtime, usegmt=True)})

        # PUT: save a plan, honouring Open Shot Designer's conflict checks.
        current = projects.etag(project) if project else None
        if_match = (request.headers.get("if-match") or "").strip()
        if if_match and (current is None or if_match not in ("*", current)):
            return Response("Changed since you opened it.", status_code=412)
        if (request.headers.get("if-none-match") or "").strip() == "*" and project is not None:
            return Response("A project with this name already exists.", status_code=412)
        try:
            saved, created = projects.save_plan(await request.body(), name=name)
        except ProjectError as exc:
            return Response(str(exc), status_code=415)
        if on_saved:
            on_saved(saved, created)
        return Response(status_code=201 if created else 204, headers={"ETag": projects.etag(saved)})

    return api
