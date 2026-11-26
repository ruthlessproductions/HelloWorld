"""Background jobs: each button in the app runs one or more commands, and the page follows their output."""

from __future__ import annotations

import itertools
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

# A step is either a command to run, or a Python function that gets a log(str) callback.
Command = tuple[str, list[str], Optional[Path], Optional[dict]]  # (label, argv, cwd, extra env)
Step = Union[Command, tuple[str, Callable[[Callable[[str], None]], None]]]


@dataclass
class Job:
    id: int
    title: str
    kind: str
    project: Optional[str] = None
    status: str = "running"  # running | ok | failed
    lines: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    ended: Optional[float] = None

    def log(self, text: str) -> None:
        for line in str(text).splitlines() or [""]:
            self.lines.append(line)
        del self.lines[:-4000]  # keep the tail of very chatty jobs

    def summary(self) -> dict:
        return {
            "id": self.id, "title": self.title, "kind": self.kind, "project": self.project, "status": self.status,
            "started": self.started, "ended": self.ended, "lines": len(self.lines),
            "last": next((l for l in reversed(self.lines) if l.strip()), ""),
        }


class JobRunner:
    def __init__(self, keep: int = 60):
        self._jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._keep = keep

    def running(self, kind: str, project: Optional[str] = None) -> Optional[Job]:
        with self._lock:
            return next((j for j in self._jobs.values()
                         if j.status == "running" and j.kind == kind and j.project == project), None)

    def start(self, title: str, kind: str, steps: list[Step], project: Optional[str] = None,
              on_done: Optional[Callable[[Job], None]] = None) -> Job:
        existing = self.running(kind, project)
        if existing:
            return existing
        with self._lock:
            job = Job(id=next(self._ids), title=title, kind=kind, project=project)
            self._jobs[job.id] = job
            for old in sorted(self._jobs)[:-self._keep]:
                if self._jobs[old].status != "running":
                    del self._jobs[old]
        threading.Thread(target=self._run, args=(job, steps, on_done), daemon=True).start()
        return job

    def _run(self, job: Job, steps: list[Step], on_done) -> None:
        try:
            for step in steps:
                label = step[0]
                job.log(f"▸ {label}")
                if callable(step[1]):
                    step[1](job.log)
                    continue
                _, argv, cwd, extra_env = step
                env = {**os.environ, "PYTHONUNBUFFERED": "1", **(extra_env or {})}
                proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1, errors="replace")
                for line in proc.stdout:
                    job.log(line.rstrip("\n"))
                code = proc.wait()
                if code != 0:
                    raise RuntimeError(f"{label} failed (exit code {code})")
            job.status = "ok"
        except Exception as exc:  # shown in the page; the server keeps going
            job.log(f"✗ {exc}")
            job.status = "failed"
        finally:
            job.ended = time.time()
            if on_done:
                try:
                    on_done(job)
                except Exception as exc:
                    job.log(f"(after-step error: {exc})")

    def list(self) -> list[dict]:
        with self._lock:
            return [j.summary() for j in sorted(self._jobs.values(), key=lambda j: j.id, reverse=True)]

    def get(self, job_id: int) -> Optional[Job]:
        return self._jobs.get(job_id)
