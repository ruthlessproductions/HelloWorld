"""helloworld: move a production through the open filmmaking stack.

  helloworld inspect   film.osd                         what's in an Open Shot Designer project
  helloworld animatic  film.osd -o cut.otio             board-o-matic timeline + board images
  helloworld conform   cut.otio renders/ --stage final  attach renders named after the shots
  helloworld kitsu push film.osd                        scenes, shots, camera notes, boards -> Kitsu
  helloworld kitsu pull cut.otio --task-type Layout --stage previs
                                                         newest Kitsu previews -> the cut

  helloworld app                                       the web app that runs all of this: http://localhost:8765

Kitsu credentials come from KITSU_HOST, KITSU_EMAIL and KITSU_PASSWORD (or the flags).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, naming, osd


def _load(path: str) -> osd.Production:
    production = osd.load(path)
    if production.schema_version is not None and production.schema_version not in osd.KNOWN_SCHEMA_VERSIONS:
        print(
            f"warning: project schema v{production.schema_version}; this tool knows v{osd.KNOWN_SCHEMA_VERSIONS.start}"
            f"-v{osd.KNOWN_SCHEMA_VERSIONS.stop - 1}. Re-export from a current Open Shot Designer if fields are missing.",
            file=sys.stderr,
        )
    return production


def cmd_inspect(args) -> int:
    production = _load(args.project)
    if args.json:
        out = {
            "title": production.title,
            "fps": production.fps,
            "scenes": [
                {
                    "sequence": naming.sequence_name(sc.number),
                    "number": sc.number,
                    "heading": sc.heading or sc.location,
                    "shots": [
                        {
                            "shot": naming.shot_name(sh.number, i),
                            "slate": sh.number,
                            "size": sh.size,
                            "lens_mm": sh.lens_mm,
                            "movement": sh.movement,
                            "seconds": sh.duration_seconds,
                            "status": sh.status,
                            "boards": len(sh.boards),
                        }
                        for i, sh in enumerate(sc.shots)
                    ],
                }
                for sc in production.scenes
            ],
        }
        print(json.dumps(out, indent=2))
        return 0
    print(f"{production.title}  ({production.fps:g} fps, schema v{production.schema_version})")
    for scene in production.scenes:
        print(f"  {naming.sequence_name(scene.number):8} {scene.heading or scene.location}")
        for i, shot in enumerate(scene.shots):
            lens = f"{shot.lens_mm:g}mm" if shot.lens_mm else "-"
            print(
                f"    {naming.shot_name(shot.number, i):7} slate {shot.number:6} {shot.size:4} {lens:6} {shot.movement:10} "
                f"{shot.duration_seconds:5.1f}s  {len(shot.boards)} board(s)  [{shot.status}]"
            )
    return 0


def cmd_animatic(args) -> int:
    from .otio_build import write_animatic

    production = _load(args.project)
    out = Path(args.output or Path(args.project).with_suffix(".otio").name)
    write_animatic(
        production, out, absolute_paths=args.absolute_paths, start_timecode=args.start_timecode,
        include_omitted=args.include_omitted,
    )
    shots = sum(1 for s in production.shots if args.include_omitted or s.status != "omitted")
    print(f"wrote {out} ({shots} shots, boards in {out.parent / (out.stem + '_media')})")
    return 0


def cmd_conform(args) -> int:
    import opentimelineio as otio

    from .conform import conform_folder

    timeline = otio.adapters.read_from_file(args.timeline)
    out = Path(args.output or args.timeline)
    report = conform_folder(timeline, Path(args.folder), args.stage, otio_dir=out.parent.resolve(), activate=args.activate)
    otio.adapters.write_to_file(timeline, str(out))
    for clip, media in report.matched.items():
        print(f"  {clip:16} {args.stage}: {media}")
    print(f"wrote {out}: {len(report.matched)} clips have {args.stage} media, {len(report.unmatched)} don't")
    return 0


def _kitsu_connect(args) -> None:
    from .kitsu_sync import connect

    host = args.host or os.environ.get("KITSU_HOST")
    email = args.email or os.environ.get("KITSU_EMAIL")
    password = os.environ.get("KITSU_PASSWORD")
    if not (host and email and password):
        raise SystemExit("Set KITSU_HOST, KITSU_EMAIL and KITSU_PASSWORD (or --host/--email) to reach Kitsu.")
    connect(host, email, password)


def cmd_kitsu_push(args) -> int:
    from .kitsu_sync import push

    production = _load(args.project)
    _kitsu_connect(args)
    report = push(
        production, project_name=args.kitsu_project, production_type=args.production_type,
        task_type_name=args.task_type, status_short_name=args.status, upload_boards=not args.no_boards,
        include_omitted=args.include_omitted,
    )
    print(
        f"{report.project}: {len(report.sequences_created)} sequences and {len(report.shots_created)} shots created, "
        f"{len(report.shots_updated)} shots updated, boards uploaded for {len(report.boards_uploaded)} shots "
        f"({len(report.boards_unchanged)} unchanged)"
    )
    for warning in report.warnings:
        print("warning:", warning, file=sys.stderr)
    print(report.url)
    return 0


def cmd_kitsu_pull(args) -> int:
    import opentimelineio as otio

    from .conform import conform_folder
    from .kitsu_sync import pull_previews

    timeline = otio.adapters.read_from_file(args.timeline)
    project = args.kitsu_project or timeline.metadata.get("helloworld", {}).get("title") or timeline.name
    _kitsu_connect(args)
    out = Path(args.output or args.timeline)
    folder = out.parent / f"{out.stem}_media" / args.stage
    clips = [clip.name for clip in timeline.find_clips()]
    pulled = pull_previews(clips, project_name=project, task_type_name=args.task_type, folder=folder)
    report = conform_folder(timeline, folder, args.stage, otio_dir=out.parent.resolve(), activate=args.activate)
    otio.adapters.write_to_file(timeline, str(out))
    print(f"wrote {out}: {len(pulled)} {args.task_type} previews from Kitsu as {args.stage}; {len(report.unmatched)} shots have none yet")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="helloworld", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"helloworld {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="list scenes and shots in an Open Shot Designer project")
    p.add_argument("project")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("animatic", help="write an OTIO board-o-matic from an Open Shot Designer project")
    p.add_argument("project")
    p.add_argument("-o", "--output", help="the .otio to write (default: <project>.otio here)")
    p.add_argument("--absolute-paths", action="store_true", help="file:// URLs instead of paths relative to the .otio")
    p.add_argument("--start-timecode", help="timeline start, e.g. 01:00:00:00")
    p.add_argument("--include-omitted", action="store_true")
    p.set_defaults(func=cmd_animatic)

    p = sub.add_parser("conform", help="attach media named after the shots to an OTIO timeline")
    p.add_argument("timeline")
    p.add_argument("folder")
    p.add_argument("--stage", default="final", help="media key to store them under (previs, final ...)")
    p.add_argument("--activate", action="store_true", help="make this stage the clips' active media")
    p.add_argument("-o", "--output", help="write here instead of updating the timeline in place")
    p.set_defaults(func=cmd_conform)

    kitsu = sub.add_parser("kitsu", help="Kitsu production tracker").add_subparsers(dest="kitsu_command", required=True)
    for name in ("push", "pull"):
        p = kitsu.add_parser(name)
        p.add_argument("--host", help="Kitsu URL (default $KITSU_HOST)")
        p.add_argument("--email", help="Kitsu login (default $KITSU_EMAIL; password from $KITSU_PASSWORD)")
        p.add_argument("--kitsu-project", help="Kitsu production name (default: the film's title)")
        if name == "push":
            p.add_argument("project", help="the Open Shot Designer .osd")
            p.add_argument("--production-type", default="featurefilm", choices=["short", "featurefilm", "tvshow"])
            p.add_argument("--task-type", default="Storyboard", help="task the boards are published on")
            p.add_argument("--status", default="wfa", help="task status short name for new boards")
            p.add_argument("--no-boards", action="store_true")
            p.add_argument("--include-omitted", action="store_true")
            p.set_defaults(func=cmd_kitsu_push)
        else:
            p.add_argument("timeline", help="the .otio cut")
            p.add_argument("--task-type", required=True, help="Kitsu task type to take previews from (Layout, Animation ...)")
            p.add_argument("--stage", required=True, help="media key in the cut (previs, final ...)")
            p.add_argument("--activate", action="store_true")
            p.add_argument("-o", "--output")
            p.set_defaults(func=cmd_kitsu_pull)

    p = sub.add_parser("app", help="run the HelloWorld web app (http://localhost:8765)")
    p.add_argument("--port", type=int, help="port to serve on (default 8765)")
    p.add_argument("--projects", help="projects folder (default ~/Documents/HelloWorld Projects)")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    p.set_defaults(func=cmd_app)
    return parser


def cmd_app(args) -> int:
    from .app.server import serve

    return serve(port=args.port, projects_dir=args.projects, open_browser=not args.no_browser)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except osd.OsdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
