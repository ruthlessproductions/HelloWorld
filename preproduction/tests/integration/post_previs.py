"""Stand in for an artist: post a previs movie to a shot's Layout task in Kitsu.

  python tests/integration/post_previs.py "Sample Production" SC001 SH002 previs.mp4 [--task-type Layout]

Uses KITSU_HOST, KITSU_EMAIL, KITSU_PASSWORD. Waits until Kitsu has finished transcoding.
"""

import argparse
import os
import sys
import time

import gazu

parser = argparse.ArgumentParser()
parser.add_argument("project")
parser.add_argument("sequence")
parser.add_argument("shot")
parser.add_argument("movie")
parser.add_argument("--task-type", default="Layout")
parser.add_argument("--status", default="wfa")
args = parser.parse_args()

host = os.environ["KITSU_HOST"].rstrip("/")
gazu.set_host(host if host.endswith("/api") else host + "/api")
gazu.log_in(os.environ["KITSU_EMAIL"], os.environ["KITSU_PASSWORD"])

project = gazu.project.get_project_by_name(args.project)
task_type = gazu.task.get_task_type_by_name(args.task_type)
gazu.project.add_task_type(project, task_type, priority=2)
sequence = gazu.shot.get_sequence_by_name(project, args.sequence)
shot = gazu.shot.get_shot_by_name(sequence, args.shot)
task = gazu.task.get_task_by_entity(shot, task_type) or gazu.task.new_task(shot, task_type)
status = gazu.task.get_task_status_by_short_name(args.status)
_, preview = gazu.task.publish_preview(task, status, comment="previs", preview_file_path=args.movie)

for _ in range(60):
    current = gazu.files.get_preview_file(preview["id"])
    if current.get("status") == "ready":
        print(f"posted {args.task_type} revision {current.get('revision')} on {args.sequence}/{args.shot}")
        sys.exit(0)
    if current.get("status") == "broken":
        sys.exit("Kitsu could not process the movie")
    time.sleep(2)
sys.exit("timed out waiting for Kitsu to process the movie")
